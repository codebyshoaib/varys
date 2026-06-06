# Kamil Capability Honesty System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop Kamil from confabulating capabilities — add an intent router for visual requests, an infographic generation pipeline, a pre-send honesty gate, and a self-updating learning loop so every capability gap is recorded and eventually built.

**Architecture:** `is_visual_request()` in the listener intercepts image/infographic intents before the generic Claude call and routes them to `infographic_handler.py` (NLM → image_generator.py → Slack upload). `honesty_gate.py` sits between `run_claude()` and `chat_postMessage()` for all other responses, catching false delivery claims. Every gap is written to `capability_gaps` in harness.db; `kamil-gap-watcher.py` promotes confirmed gaps into `CAPABILITIES.md` weekly and opens Notion Harness tickets for high-priority ones.

**Tech Stack:** Python 3.10+, SQLite (harness.db), Pillow (image_generator.py already uses it), Slack SDK (WebClient already imported), notebooklm_handler.py (run_nlm, registry_search, upload_file_to_slack, create_notebook, deep_research already exist), kamil_harness_db.py (get_db, migrate_db pattern), kamil_log.py (klog, klog_error)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `.claude/rules/CAPABILITIES.md` | CREATE | Machine-readable capability manifest; injected into every Claude prompt |
| `.claude/hooks/infographic_handler.py` | CREATE | NLM → key points → image_generator.py → upload → honest fallback |
| `.claude/hooks/honesty_gate.py` | CREATE | Pre-send false-claim detector; rewrites + logs gaps |
| `.claude/hooks/kamil_harness_db.py` | MODIFY | Add `capability_gaps` table + `log_capability_gap()` helper |
| `.claude/hooks/kamil-gap-watcher.py` | MODIFY | Replace .jsonl logic with harness.db query + CAPABILITIES.md promotion + Notion ticket |
| `.claude/hooks/kamil-slack-listener.py` | MODIFY | `is_visual_request()`, visual routing, honesty gate wiring, manifest injection |
| `tests/test_capability_honesty.py` | CREATE | Unit tests for all new modules |

---

## Task 1: `capability_gaps` table + `log_capability_gap()` in `kamil_harness_db.py`

**Files:**
- Modify: `.claude/hooks/kamil_harness_db.py`
- Test: `tests/test_capability_honesty.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_capability_honesty.py`:

```python
import sys, os, sqlite3, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))

# Patch HARNESS_DB to a temp file before importing
import kamil_harness_db
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
kamil_harness_db.HARNESS_DB = Path(_tmp.name)
kamil_harness_db.HARNESS_DIR = Path(_tmp.name).parent

from kamil_harness_db import get_db, log_capability_gap, get_capability_gaps

def test_log_and_read_gap():
    db = get_db()
    log_capability_gap(db, gap_type="inline_image", request_text="make infographic",
                       failed_step="nlm_query", fallback_used="text_summary")
    log_capability_gap(db, gap_type="inline_image", request_text="create image",
                       failed_step="upload", fallback_used="text_summary")
    gaps = get_capability_gaps(db, days=7)
    assert len(gaps) == 1
    assert gaps[0]["gap_type"] == "inline_image"
    assert gaps[0]["count"] == 2

def test_gap_reaction_update():
    db = get_db()
    log_capability_gap(db, gap_type="video_gen", request_text="make video",
                       failed_step="no_tool", fallback_used="none")
    update_gap_reaction(db, gap_type="video_gen", reaction="rejected")
    gaps = get_capability_gaps(db, days=7)
    video = next(g for g in gaps if g["gap_type"] == "video_gen")
    assert video["rejected_count"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python -m pytest tests/test_capability_honesty.py::test_log_and_read_gap -v
```
Expected: `ImportError: cannot import name 'log_capability_gap'`

- [ ] **Step 3: Add `capability_gaps` schema to `_SCHEMA` in `kamil_harness_db.py`**

In `.claude/hooks/kamil_harness_db.py`, find the `_SCHEMA` string (line ~37) and append before the closing `"""`:

```python
CREATE TABLE IF NOT EXISTS capability_gaps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    gap_type      TEXT NOT NULL,
    request_text  TEXT,
    failed_step   TEXT,
    fallback_used TEXT,
    reaction      TEXT DEFAULT 'pending',
    ts            TEXT NOT NULL DEFAULT (datetime('now')),
    session_id    TEXT
);
CREATE INDEX IF NOT EXISTS idx_gaps_type_ts ON capability_gaps(gap_type, ts);
```

- [ ] **Step 4: Add `migrate_db` migration for existing databases**

In the `migrate_db` function (line ~104), add after the existing phase migration:

```python
# Migration 002: capability_gaps table
tables = [r[0] for r in db.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
).fetchall()]
if "capability_gaps" not in tables:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS capability_gaps (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            gap_type      TEXT NOT NULL,
            request_text  TEXT,
            failed_step   TEXT,
            fallback_used TEXT,
            reaction      TEXT DEFAULT 'pending',
            ts            TEXT NOT NULL DEFAULT (datetime('now')),
            session_id    TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_gaps_type_ts ON capability_gaps(gap_type, ts);
    """)
    db.commit()
```

- [ ] **Step 5: Add `log_capability_gap()`, `get_capability_gaps()`, `update_gap_reaction()` functions**

Add at the end of `.claude/hooks/kamil_harness_db.py`, before `if __name__ == "__main__"`:

```python
# ── Capability gap tracking ───────────────────────────────────────────────────

def log_capability_gap(
    db: sqlite3.Connection,
    gap_type: str,
    request_text: str = "",
    failed_step: str = "",
    fallback_used: str = "",
    session_id: str = "",
) -> None:
    """Record one capability gap occurrence."""
    with _db_lock:
        db.execute(
            "INSERT INTO capability_gaps "
            "(gap_type, request_text, failed_step, fallback_used, session_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (gap_type, request_text[:300], failed_step, fallback_used, session_id),
        )
        db.commit()


def get_capability_gaps(
    db: sqlite3.Connection,
    days: int = 7,
    min_count: int = 1,
) -> list[dict]:
    """
    Return aggregated gap counts for the last N days.
    Each dict: {gap_type, count, rejected_count, sample_requests, last_seen}
    """
    rows = db.execute(
        """
        SELECT
            gap_type,
            COUNT(*) as count,
            SUM(CASE WHEN reaction='rejected' THEN 1 ELSE 0 END) as rejected_count,
            MAX(ts) as last_seen,
            GROUP_CONCAT(DISTINCT request_text) as samples
        FROM capability_gaps
        WHERE ts >= datetime('now', ?)
        GROUP BY gap_type
        HAVING count >= ?
        ORDER BY count DESC
        """,
        (f"-{days} days", min_count),
    ).fetchall()
    return [
        {
            "gap_type":       r[0],
            "count":          r[1],
            "rejected_count": r[2] or 0,
            "last_seen":      r[3],
            "sample_requests": (r[4] or "").split(",")[:3],
        }
        for r in rows
    ]


def update_gap_reaction(
    db: sqlite3.Connection,
    gap_type: str,
    reaction: str,
) -> None:
    """Mark the most recent gap entry for this type with a reaction."""
    with _db_lock:
        db.execute(
            "UPDATE capability_gaps SET reaction=? "
            "WHERE gap_type=? AND id=("
            "  SELECT id FROM capability_gaps WHERE gap_type=? ORDER BY ts DESC LIMIT 1"
            ")",
            (reaction, gap_type, gap_type),
        )
        db.commit()
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
python -m pytest tests/test_capability_honesty.py -v
```
Expected: `2 passed`

- [ ] **Step 7: Commit**

```bash
git add .claude/hooks/kamil_harness_db.py tests/test_capability_honesty.py
git commit -m "feat: add capability_gaps table and helpers to harness_db"
```

---

## Task 2: `CAPABILITIES.md` — the manifest

**Files:**
- Create: `.claude/rules/CAPABILITIES.md`

- [ ] **Step 1: Create the file**

```bash
cat > /home/oye/Documents/free_work/personal-agent-v2/.claude/rules/CAPABILITIES.md << 'EOF'
# Kamil Capability Manifest

## WHAT KAMIL CANNOT DO

When asked to do something on this list, Kamil MUST:
1. Attempt the closest available tool first.
2. If that fails, say exactly what wasn't possible and why.
3. Offer 1-2 concrete alternatives that ARE possible.
4. Never claim to have done something that didn't happen.

| gap_type | Cannot do | Honest fallback |
|---|---|---|
| inline_image_arbitrary | Generate arbitrary images on demand without image_generator.py | Use `image_generator.py --type info` for structured infographics (NLM-sourced). Offer text summary if PIL missing. |
| nlm_visual_export_sync | Post NLM slide/mindmap exports inline immediately — they take 2–5 min async | Start the generation, say "I'll post it here when ready (2–5 min)", use poll_and_post_artifact() |
| canva_inline_post | Post Canva design URLs as viewable inline images — they require login | Export PNG via Canva MCP then upload_file_to_slack(), or describe what was designed |
| video_generation | Generate video content | Say so plainly. Offer: NLM podcast (audio), slides (PDF), or infographic (PNG) |
| arbitrary_file_download | Download external binary URLs as files | Use WebFetch for text content. For binaries, say it's not possible and explain why |
| chart_rendering | Render dynamic data charts or graphs | Use image_generator.py info type for static lists. For real data charts, suggest building a chart renderer as a Harness ticket |

## Rule

If you are about to say "here it is", "I posted", "I generated", "done — here",
"I've sent", or "check it out" — STOP and verify the file/upload actually happened.
If it didn't, tell the truth.
EOF
```

- [ ] **Step 2: Verify the file exists and is readable**

```bash
cat /home/oye/Documents/free_work/personal-agent-v2/.claude/rules/CAPABILITIES.md | head -5
```
Expected: `# Kamil Capability Manifest`

- [ ] **Step 3: Commit**

```bash
git add .claude/rules/CAPABILITIES.md
git commit -m "feat: add CAPABILITIES.md manifest for Kamil honesty system"
```

---

## Task 3: `infographic_handler.py`

**Files:**
- Create: `.claude/hooks/infographic_handler.py`
- Test: `tests/test_capability_honesty.py` (add tests)

- [ ] **Step 1: Add tests for the handler**

Append to `tests/test_capability_honesty.py`:

```python
import unittest.mock as mock

def test_extract_topic_from_text():
    from infographic_handler import extract_topic
    assert extract_topic("create an infographic about pull-up progression") == "pull-up progression"
    assert extract_topic("make an infographic on swimming") == "swimming"
    assert extract_topic("infographic for cycling training zones") == "cycling training zones"

def test_detect_palette():
    from infographic_handler import detect_palette
    assert detect_palette("pull-up progression calisthenics") == "fitness"
    assert detect_palette("Django REST API performance") == "tech"
    assert detect_palette("something random") == "tech"  # default

def test_parse_nlm_points():
    from infographic_handler import parse_nlm_points
    raw = "1. Keep your core tight\n2. Dead hang first\n3. Scapular pulls before full pull-ups"
    points = parse_nlm_points(raw)
    assert len(points) == 3
    assert points[0] == "Keep your core tight"

def test_parse_nlm_points_fallback():
    from infographic_handler import parse_nlm_points
    # Handles non-numbered output
    raw = "Keep your core tight. Dead hang first. Scapular pulls are key."
    points = parse_nlm_points(raw)
    assert len(points) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_capability_honesty.py::test_extract_topic_from_text -v
```
Expected: `ImportError: No module named 'infographic_handler'`

- [ ] **Step 3: Create `infographic_handler.py`**

Create `.claude/hooks/infographic_handler.py`:

```python
#!/usr/bin/env python3
"""
infographic_handler.py — NLM-sourced infographic generator for Kamil.

Flow:
  extract_topic() → resolve NLM notebook → query for key points
  → image_generator.py --type info → upload_file_to_slack()
  → honest fallback on any step failure + log_capability_gap()
"""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_log import klog, klog_error

KAMIL_DIR   = Path(__file__).parent.parent.parent
IMAGE_GEN   = Path(__file__).parent / "image_generator.py"

_TOPIC_PATTERNS = [
    r"infographic\s+(?:about|on|for|of)\s+(.+)",
    r"(?:create|make|generate|build)\s+(?:an?\s+)?infographic\s+(?:about|on|for|of)?\s*(.+)",
    r"(?:create|make|generate|build)\s+(?:an?\s+)?image\s+(?:about|on|for|of)\s+(.+)",
    r"image\s+(?:about|on|for|of)\s+(.+)",
    r"visual\s+(?:for|about|on)\s+(.+)",
]

_FITNESS_KEYWORDS = {
    "fitness", "workout", "exercise", "training", "pull", "push", "swim",
    "cycle", "cycling", "calisthenics", "running", "gym", "muscle",
    "strength", "cardio", "hiit", "yoga", "sport", "health", "nutrition",
    "diet", "weight", "body", "stretching", "flexibility", "pullup",
}

_SLACK_CFG = Path.home() / ".claude" / "hooks" / ".slack"


def _load_bot_token() -> str:
    for key in ("SLACK_BOT_TOKEN", "BOT_TOKEN"):
        val = os.environ.get(key)
        if val:
            return val
    if _SLACK_CFG.exists():
        for line in _SLACK_CFG.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() in ("BOT_TOKEN", "SLACK_BOT_TOKEN"):
                    return v.strip()
    return ""


def extract_topic(text: str) -> str:
    """Extract the infographic topic from a natural language request."""
    clean = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    for pattern in _TOPIC_PATTERNS:
        m = re.search(pattern, clean, re.IGNORECASE)
        if m:
            topic = m.group(1).strip().rstrip(".,!?")
            # Strip trailing filler words
            topic = re.sub(r"\s+(please|now|quickly|for me)$", "", topic, flags=re.IGNORECASE)
            return topic
    # Fallback: strip common trigger words and return the rest
    fallback = re.sub(
        r"^.*?(infographic|image|visual|picture)\s*", "", clean, flags=re.IGNORECASE
    ).strip()
    return fallback or clean[:60]


def detect_palette(topic: str) -> str:
    """Return 'fitness' or 'tech' based on topic keywords."""
    words = set(topic.lower().split())
    if words & _FITNESS_KEYWORDS:
        return "fitness"
    return "tech"


def parse_nlm_points(raw: str) -> list[str]:
    """
    Parse NLM query output into a list of clean point strings (5-7 items).
    Handles numbered lists (1. ...) and plain sentences.
    """
    # Try numbered list first: "1. text" or "1) text"
    numbered = re.findall(r"^\s*\d+[.)]\s+(.+)", raw, re.MULTILINE)
    if len(numbered) >= 3:
        return [p.strip() for p in numbered[:7]]

    # Try bullet list: "- text" or "• text" or "* text"
    bulleted = re.findall(r"^\s*[-•*]\s+(.+)", raw, re.MULTILINE)
    if len(bulleted) >= 3:
        return [p.strip() for p in bulleted[:7]]

    # Split on sentences as fallback
    sentences = re.split(r"(?<=[.!?])\s+", raw.strip())
    points = [s.strip() for s in sentences if len(s.strip()) > 15][:7]
    return points if points else [raw.strip()[:100]]


def _log_gap(gap_type: str, request_text: str, failed_step: str, fallback: str) -> None:
    """Write a capability gap to harness.db (best-effort — never raises)."""
    try:
        from kamil_harness_db import get_db, log_capability_gap
        db = get_db()
        log_capability_gap(
            db,
            gap_type=gap_type,
            request_text=request_text[:300],
            failed_step=failed_step,
            fallback_used=fallback,
        )
    except Exception as e:
        klog_error("infographic_log_gap_fail", component="infographic_handler", error=str(e))


def _post_text(web, channel: str, thread_ts: str, text: str) -> None:
    web.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)


def handle(
    text: str,
    channel: str,
    thread_ts: str,
    web,
    bot_token: str = None,
    sender_id: str = None,
) -> None:
    """
    Main entry point. Called from kamil-slack-listener when is_visual_request() is True.
    Runs synchronously in a background thread.
    """
    if not bot_token:
        bot_token = _load_bot_token()

    topic = extract_topic(text)
    if not topic:
        _post_text(web, channel, thread_ts,
                   "What topic should the infographic cover? 🤖 Kamil")
        return

    _post_text(web, channel, thread_ts,
               f"🖼️ Generating infographic: *{topic}*... (1–2 min)\n🤖 Kamil")

    # ── Step 1: Resolve NLM notebook ──────────────────────────────────────────
    try:
        from notebooklm_handler import (
            registry_search, resolve_notebook, run_nlm,
            create_notebook, deep_research, upload_file_to_slack,
        )
    except ImportError as e:
        klog_error("infographic_import_fail", component="infographic_handler", error=str(e))
        _log_gap("inline_image_arbitrary", text, "import_notebooklm", "none")
        _post_text(web, channel, thread_ts,
                   f"⚠️ NotebookLM module not available. Can't generate infographic right now.\n🤖 Kamil")
        return

    keywords = topic.lower().split()
    hits = registry_search(keywords)
    nb_id = hits[0]["id"] if hits else None

    if not nb_id:
        # Create notebook + do research (this takes 1-3 min — already told user to wait)
        nb_id = create_notebook(topic, bot_token)
        if nb_id:
            deep_research(topic, bot_token, notebook_id=nb_id)
        else:
            _log_gap("inline_image_arbitrary", text, "nlm_notebook_create", "text_summary")
            _post_text(web, channel, thread_ts,
                       f"⚠️ NotebookLM isn't responding right now. "
                       f"Can't create a notebook for *{topic}*.\n"
                       f"Try `nlm research {topic}` later, or I can give you a text summary. Which?\n🤖 Kamil")
            return

    # ── Step 2: Query for structured key points ────────────────────────────────
    query = f"List exactly 7 key facts about {topic}, one per line, starting each with a number."
    ok, raw = run_nlm(["notebook", "query", nb_id, query, "--json",
                        "--profile", "default"], timeout=120)

    if not ok or not raw.strip():
        _log_gap("inline_image_arbitrary", text, "nlm_query", "text_summary")
        _post_text(web, channel, thread_ts,
                   f"⚠️ Got the notebook but couldn't extract points for *{topic}*.\n"
                   f"Try: `nlm ask pullups \"{query}\"`\n🤖 Kamil")
        return

    import json as _json
    try:
        data = _json.loads(raw)
        answer_raw = data.get("value", {}).get("answer", raw)
    except Exception:
        answer_raw = raw

    points = parse_nlm_points(answer_raw)
    if len(points) < 3:
        _log_gap("inline_image_arbitrary", text, "nlm_parse", "text_summary")
        _post_text(web, channel, thread_ts,
                   f"⚠️ Couldn't extract enough points from the research on *{topic}* "
                   f"(got {len(points)}).\n"
                   f"Here's the raw research:\n```{answer_raw[:600]}```\n🤖 Kamil")
        return

    # ── Step 3: Render PNG ─────────────────────────────────────────────────────
    palette  = detect_palette(topic)
    ts_stamp = str(int(time.time()))
    outfile  = f"/tmp/infographic-{ts_stamp}.png"
    points_arg = "|".join(points[:7])  # image_generator uses | as separator in --points

    try:
        result = subprocess.run(
            [
                sys.executable, str(IMAGE_GEN),
                "--type",    "info",
                "--title",   topic[:40],
                "--points",  points_arg,
                "--palette", palette,
                "--handle",  "@oykamal",
                "--output",  outfile,
            ],
            capture_output=True, text=True, timeout=30,
            cwd=str(KAMIL_DIR),
        )
        if result.returncode != 0 or not Path(outfile).exists():
            raise RuntimeError(result.stderr.strip() or "no output file")
    except Exception as e:
        _log_gap("inline_image_arbitrary", text, "image_render", "text_points")
        klog_error("infographic_render_fail", component="infographic_handler", error=str(e))
        # Fallback: post the points as a structured text message
        lines = [f"🖼️ *{topic}* — research points (image render failed)\n"]
        for i, p in enumerate(points, 1):
            lines.append(f"{i}. {p}")
        lines.append("\n_Install Pillow to enable image rendering: `pip install Pillow`_\n🤖 Kamil")
        _post_text(web, channel, thread_ts, "\n".join(lines))
        return

    # ── Step 4: Upload to Slack ────────────────────────────────────────────────
    comment = f"🖼️ *{topic}* — sourced from NotebookLM\n🤖 Kamil"
    ok = upload_file_to_slack(bot_token, channel, outfile,
                               title=f"Infographic: {topic}", comment=comment)

    if not ok:
        _log_gap("inline_image_arbitrary", text, "slack_upload", "file_path_fallback")
        _post_text(web, channel, thread_ts,
                   f"🖼️ Generated the infographic for *{topic}* but can't upload it — "
                   f"Kamil app needs `files:write` scope.\n"
                   f"Fix: api.slack.com/apps → Kamil → OAuth Scopes → add `files:write` → Reinstall.\n"
                   f"File saved at: `{outfile}`\n🤖 Kamil")
        return

    klog("infographic_posted", component="infographic_handler",
         topic=topic, nb_id=nb_id, palette=palette, points=len(points))
    # Clean up temp file
    try:
        Path(outfile).unlink(missing_ok=True)
    except Exception:
        pass
```

- [ ] **Step 4: Check image_generator.py `--points` separator**

```bash
grep -n "points\|split\|\|" /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/image_generator.py | grep -i "split\|sep\|join\|points" | head -10
```

If `--points` uses a different separator than `|`, update the `points_arg` line in Step 3 to match. The `make_info()` function signature is `make_info(title, points: list[str], ...)` so check how argparse converts the `--points` string to a list.

- [ ] **Step 5: Fix `--points` parsing if needed**

Read lines 388-420 of image_generator.py to see exactly how `--points` is parsed:

```bash
sed -n '388,430p' /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/image_generator.py
```

Update `points_arg` in `infographic_handler.py` to use the correct separator.

- [ ] **Step 6: Run the new tests**

```bash
python -m pytest tests/test_capability_honesty.py -v
```
Expected: all tests pass (4 from Task 1 + 4 new)

- [ ] **Step 7: Commit**

```bash
git add .claude/hooks/infographic_handler.py tests/test_capability_honesty.py
git commit -m "feat: add infographic_handler — NLM research to PNG pipeline"
```

---

## Task 4: `honesty_gate.py`

**Files:**
- Create: `.claude/hooks/honesty_gate.py`
- Test: `tests/test_capability_honesty.py` (add tests)

- [ ] **Step 1: Add tests**

Append to `tests/test_capability_honesty.py`:

```python
def test_honesty_gate_passes_clean_response():
    from honesty_gate import check
    result = check("Here's what I found about Django migrations.", uploaded=False, request="tell me about migrations")
    assert result == "Here's what I found about Django migrations."

def test_honesty_gate_flags_false_claim_no_upload():
    from honesty_gate import contains_delivery_claim
    assert contains_delivery_claim("Here it is! I posted the infographic.") is True
    assert contains_delivery_claim("I've sent you the image.") is True
    assert contains_delivery_claim("Here's what I know about pullups.") is False

def test_honesty_gate_passes_with_confirmed_upload():
    from honesty_gate import check
    # uploaded=True means the file was actually sent — gate should not block
    result = check("Here it is — your infographic! 🤖 Kamil", uploaded=True, request="make infographic")
    assert "Here it is" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_capability_honesty.py::test_honesty_gate_flags_false_claim_no_upload -v
```
Expected: `ImportError: No module named 'honesty_gate'`

- [ ] **Step 3: Create `honesty_gate.py`**

Create `.claude/hooks/honesty_gate.py`:

```python
#!/usr/bin/env python3
"""
honesty_gate.py — Pre-send filter for Kamil's Slack responses.

Detects false delivery claims ("here it is", "I posted X") when no actual
file/upload happened. Rewrites to an honest fallback and logs the gap.

Usage:
    from honesty_gate import check, contains_delivery_claim

    answer = run_claude(prompt)
    answer = check(answer, uploaded=_upload_succeeded, request=text)
    web.chat_postMessage(..., text=answer)
"""

import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_log import klog, klog_error

KAMIL_DIR = Path(__file__).parent.parent.parent

DELIVERY_CLAIMS = [
    "here it is",
    "here you go",
    "i've posted",
    "i posted",
    "i've sent",
    "i sent it",
    "i generated",
    "i created the image",
    "done — here",
    "done - here",
    "posted it",
    "uploaded it",
    "i've uploaded",
    "check it out",
    "here's the infographic",
    "here's the image",
    "here's your image",
    "here's your infographic",
    "i've created",
    "i made the",
    "i built the image",
    "i designed the",
]


def contains_delivery_claim(text: str) -> bool:
    """Return True if the text contains a false delivery claim phrase."""
    lower = text.lower()
    return any(claim in lower for claim in DELIVERY_CLAIMS)


def _rewrite_honest(draft: str, request: str) -> str:
    """
    Run a fast Claude call to rewrite the false-claim response honestly.
    Falls back to a canned message if Claude is unavailable.
    """
    prompt = (
        f"Rewrite this message to be honest. The agent claimed to have produced "
        f"or sent something but did not actually do it. "
        f"Remove the false claim. State clearly what wasn't possible "
        f"and offer 1-2 concrete alternatives that ARE possible. "
        f"Keep it under 3 lines. Sign off: 🤖 Kamil\n\n"
        f"Original request: \"{request[:200]}\"\n\n"
        f"Draft to rewrite:\n\"{draft[:600]}\""
    )
    try:
        nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
        env = os.environ.copy()
        env["_HONESTY_PROMPT"] = prompt
        result = subprocess.run(
            ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$_HONESTY_PROMPT"'],
            capture_output=True, text=True,
            cwd=str(KAMIL_DIR),
            timeout=30, env=env,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        klog_error("honesty_gate_rewrite_fail", component="honesty_gate", error=str(e))

    # Canned fallback if Claude unavailable
    return (
        "I wasn't able to produce that — something went wrong during generation. "
        "Try `nlm slides [topic]` for a slide deck, or ask me to describe the research instead. "
        "🤖 Kamil"
    )


def _log_gap(gap_type: str, request: str, draft: str) -> None:
    """Log to harness.db and Notion Observability. Never raises."""
    try:
        from kamil_harness_db import get_db, log_capability_gap
        db = get_db()
        log_capability_gap(
            db,
            gap_type=gap_type,
            request_text=request[:300],
            failed_step="false_claim_in_response",
            fallback_used="honesty_gate_rewrite",
        )
    except Exception as e:
        klog_error("honesty_gate_log_fail", component="honesty_gate", error=str(e))

    klog("honesty_gate_fired", component="honesty_gate",
         gap_type=gap_type, request=request[:100], draft=draft[:100],
         severity="warning")


def check(draft: str, uploaded: bool, request: str, gap_type: str = "inline_image_arbitrary") -> str:
    """
    Main gate function. Call between run_claude() and chat_postMessage().

    Args:
        draft:    The response Claude produced.
        uploaded: True if a file was actually uploaded to Slack this request.
        request:  The original user request text (for context in rewrite).
        gap_type: The capability gap type to log if firing.

    Returns:
        Safe response text — either the original draft (if clean) or an honest rewrite.
    """
    if not contains_delivery_claim(draft):
        return draft  # Nothing to fix

    if uploaded:
        return draft  # Claim is true — let it through

    # False claim detected and no upload happened
    _log_gap(gap_type, request, draft)
    rewritten = _rewrite_honest(draft, request)
    klog("honesty_gate_rewritten", component="honesty_gate",
         original_len=len(draft), rewritten_len=len(rewritten))
    return rewritten
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_capability_honesty.py -v
```
Expected: all 11 tests pass

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks/honesty_gate.py tests/test_capability_honesty.py
git commit -m "feat: add honesty_gate — pre-send false claim detector and rewriter"
```

---

## Task 5: Wire everything into `kamil-slack-listener.py`

**Files:**
- Modify: `.claude/hooks/kamil-slack-listener.py`

There are 4 targeted edits. Read the file before each edit to confirm line numbers haven't shifted.

- [ ] **Step 1: Add imports at top of listener (after existing hook imports, ~line 51)**

Find the block ending with `from notebooklm_handler import handle as nlm_handle, is_notebooklm_command` and add below it:

```python
try:
    from infographic_handler import handle as infographic_handle
    _infographic_available = True
except ImportError:
    _infographic_available = False

try:
    from honesty_gate import check as honesty_check
    _honesty_gate_available = True
except ImportError:
    _honesty_gate_available = False
```

- [ ] **Step 2: Add `is_visual_request()` function (after `_is_question()`, ~line 113)**

```python
_VISUAL_TRIGGERS = (
    "infographic", "create image", "make image", "generate image",
    "create a visual", "make a visual", "make me a visual",
    "create an image", "generate a picture", "make an infographic",
    "visual for", "image for", "create me an infographic",
    "make me an infographic", "build an infographic",
)

def is_visual_request(text: str) -> bool:
    """Return True if the message is requesting image/infographic generation."""
    t = text.lower()
    return any(trigger in t for trigger in _VISUAL_TRIGGERS)
```

- [ ] **Step 3: Add visual routing in the event dispatcher (find the NLM fast-path block at ~line 856)**

Find this block:
```python
    if sender_id == KAMAL_USER_ID and is_notebooklm_command(clean):
```

Add the visual routing block AFTER that entire `if` block (after its `return`):

```python
    # ── Visual request fast-path ──────────────────────────────────────────────
    if sender_id == KAMAL_USER_ID and is_visual_request(clean) and _infographic_available:
        cfg           = load_config()
        bot_token_cfg = cfg.get("BOT_TOKEN")
        if _context_available and job_id:
            mark_job_processing(job_id)
        threading.Thread(
            target=infographic_handle,
            args=(clean, channel, thread_ts, web, bot_token_cfg, sender_id),
            daemon=True,
        ).start()
        return
```

- [ ] **Step 4: Inject CAPABILITIES.md into the Claude prompt in `handle_message()`**

Find the `handle_message()` function. Locate where the `prompt` string is built (the large f-string starting with `"""You are Kamil — Kamal's personal AI agent`). Find the `## YOUR SKILLS` section near line 597.

Add the capabilities block **before** the `## THREAD HISTORY` section:

```python
    # Load capability manifest for injection
    _caps_path = KAMIL_DIR / ".claude" / "rules" / "CAPABILITIES.md"
    _caps_block = _caps_path.read_text() if _caps_path.exists() else ""
```

Then in the prompt f-string, add after `## YOUR SKILLS` block:

```
## WHAT KAMIL CANNOT DO
{_caps_block}
```

- [ ] **Step 5: Wire honesty gate between `run_claude()` and `chat_postMessage()`**

In `handle_message()`, find the line:
```python
    answer = run_claude(prompt, cwd=str(KAMIL_DIR), timeout=300, event_context=source)
```

Add immediately after it:

```python
    # Honesty gate: catches false delivery claims before sending
    if _honesty_gate_available:
        answer = honesty_check(answer, uploaded=False, request=text)
```

Note: `uploaded=False` here because `handle_message()` is the generic text path — it never uploads files. The visual path (Task 3) uses `infographic_handler` directly and doesn't go through this gate.

- [ ] **Step 6: Restart the listener and smoke-test**

```bash
# Kill existing listener
pkill -f kamil-slack-listener.py

# Start fresh (setsid so it survives terminal close)
setsid python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-slack-listener.py >> /tmp/kamil-slack-listener.log 2>&1 &

# Tail log for 10s to confirm clean startup
tail -f /tmp/kamil-slack-listener.log &
sleep 10 && kill %1
```
Expected: no ImportError lines in the log.

- [ ] **Step 7: Commit**

```bash
git add .claude/hooks/kamil-slack-listener.py
git commit -m "feat: wire visual router, honesty gate, and CAPABILITIES manifest into listener"
```

---

## Task 6: `kamil-gap-watcher.py` — promote gaps to CAPABILITIES.md + Notion tickets

**Files:**
- Modify: `.claude/hooks/kamil-gap-watcher.py`
- Test: `tests/test_capability_honesty.py` (add test)

- [ ] **Step 1: Add test**

Append to `tests/test_capability_honesty.py`:

```python
def test_gap_watcher_promotion_logic():
    """promote_gaps() should return gap_types that meet the threshold."""
    import kamil_harness_db as hdb
    db = hdb.get_db()
    # Insert 2 gaps of the same type
    hdb.log_capability_gap(db, gap_type="chart_rendering",
                           request_text="show me a chart", failed_step="no_tool",
                           fallback_used="none")
    hdb.log_capability_gap(db, gap_type="chart_rendering",
                           request_text="bar chart please", failed_step="no_tool",
                           fallback_used="none")
    gaps = hdb.get_capability_gaps(db, days=7, min_count=2)
    assert any(g["gap_type"] == "chart_rendering" for g in gaps)
```

- [ ] **Step 2: Run test to verify it passes (uses existing code from Task 1)**

```bash
python -m pytest tests/test_capability_honesty.py::test_gap_watcher_promotion_logic -v
```
Expected: PASS

- [ ] **Step 3: Rewrite `kamil-gap-watcher.py`**

Replace the entire content of `.claude/hooks/kamil-gap-watcher.py` with:

```python
#!/usr/bin/env python3
"""
kamil-gap-watcher.py — Weekly capability gap promoter.

Reads capability_gaps from harness.db. For any gap_type with 2+ occurrences
in the last 7 days that isn't already in CAPABILITIES.md:
  1. Appends it to CAPABILITIES.md under CANNOT DO
  2. DMes Kamal
  3. If priority score >= 4, creates a Notion Harness ticket

Run: weekly via cron (cron-wrap.sh)
"""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from kamil_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

KAMIL_DIR      = Path(__file__).parent.parent.parent
CAPABILITIES_MD = KAMIL_DIR / ".claude" / "rules" / "CAPABILITIES.md"
SLACK_CFG      = Path.home() / ".claude" / "hooks" / ".slack"
KAMAL_SLACK_ID = "U0AV1DX3WSE"
HARNESS_DB_ID  = "de10157da3e34ef58a74ea240f31fe98"
NOTION_API     = "https://api.notion.com/v1"


def _load_bot_token() -> str:
    for key in ("SLACK_BOT_TOKEN", "BOT_TOKEN"):
        val = os.environ.get(key)
        if val:
            return val
    if SLACK_CFG.exists():
        for line in SLACK_CFG.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() in ("BOT_TOKEN", "SLACK_BOT_TOKEN"):
                    return v.strip()
    return ""


def _dm_kamal(bot_token: str, text: str) -> None:
    data = json.dumps({"users": KAMAL_SLACK_ID}).encode()
    req  = urllib.request.Request(
        "https://slack.com/api/conversations.open", data=data,
        headers={"Authorization": f"Bearer {bot_token}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        result = json.loads(r.read())
    channel = result.get("channel", {}).get("id")
    if not channel:
        return
    data = json.dumps({"channel": channel, "text": text}).encode()
    req  = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", data=data,
        headers={"Authorization": f"Bearer {bot_token}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        pass


def _already_in_capabilities(gap_type: str) -> bool:
    """Return True if gap_type is already documented in CAPABILITIES.md."""
    if not CAPABILITIES_MD.exists():
        return False
    return gap_type in CAPABILITIES_MD.read_text()


def _append_to_capabilities(gap_type: str, sample_requests: list[str]) -> None:
    """Append a new CANNOT DO entry to CAPABILITIES.md."""
    samples = "; ".join(sample_requests[:2])
    entry = (
        f"| {gap_type} | Not yet implemented (auto-detected from {len(sample_requests)} requests)"
        f" | Tell Kamal: `@Kamil I need {gap_type}` to trigger a build ticket |"
        f"  _(sample: {samples[:100]})_ |\n"
    )
    with open(CAPABILITIES_MD, "a") as f:
        f.write(entry)
    klog("gap_watcher_capabilities_updated", component="gap-watcher", gap_type=gap_type)


def _create_notion_ticket(gap_type: str, count: int, samples: list[str]) -> bool:
    """Create a Notion Harness ticket for building this capability. Best-effort."""
    token = os.environ.get("NOTION_API_KEY", "")
    if not token:
        return False
    try:
        sample_text = "\n".join(f"- {s}" for s in samples[:3])
        page = {
            "parent": {"type": "database_id",
                       "database_id": HARNESS_DB_ID.replace("-", "")},
            "properties": {
                "Name": {"title": [{"text": {"content": f"Build capability: {gap_type}"}}]},
                "Status": {"status": {"name": "Not started"}},
            },
            "children": [{
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {
                    "content": (
                        f"Auto-detected capability gap: {gap_type}\n"
                        f"Hit {count} times in the last 7 days.\n\n"
                        f"Sample requests:\n{sample_text}\n\n"
                        f"Suggested: build a handler in infographic_handler.py or a new module."
                    )
                }}]},
            }],
        }
        data = json.dumps(page).encode()
        req  = urllib.request.Request(
            f"{NOTION_API}/pages", data=data,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json",
                     "Notion-Version": "2022-06-28"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())
        return bool(result.get("id"))
    except Exception as e:
        klog_error("gap_watcher_notion_fail", component="gap-watcher", error=str(e))
        return False


def run() -> None:
    from kamil_harness_db import get_db, get_capability_gaps

    db   = get_db()
    gaps = get_capability_gaps(db, days=7, min_count=2)

    if not gaps:
        klog("gap_watcher_no_gaps", component="gap-watcher", action="scan_complete")
        return

    bot_token  = _load_bot_token()
    promoted   = []

    for gap in gaps:
        gap_type = gap["gap_type"]
        count    = gap["count"]
        rejected = gap["rejected_count"]
        samples  = gap["sample_requests"]

        if _already_in_capabilities(gap_type):
            continue

        _append_to_capabilities(gap_type, samples)
        promoted.append(gap_type)

        # Priority score: rejected occurrences weight 3x
        priority = rejected * 3 + count
        ticket_created = False
        if priority >= 4 and bot_token:
            ticket_created = _create_notion_ticket(gap_type, count, samples)

        if bot_token:
            ticket_line = " Created a Harness ticket to build it." if ticket_created else ""
            _dm_kamal(bot_token,
                f"📚 *Capability gap learned:* `{gap_type}`\n"
                f"Hit {count} times this week ({rejected} rejected).\n"
                f"Added to my limits in `CAPABILITIES.md`.{ticket_line}\n"
                f"Want me to start building it? 🤖 Kamil")

    if promoted:
        klog("gap_watcher_promoted", component="gap-watcher",
             promoted=promoted, count=len(promoted))


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Add to crontab via cron-wrap.sh**

```bash
# Check existing crontab
crontab -l | grep gap-watcher
```

If not present, add weekly Sunday 3am run:

```bash
(crontab -l 2>/dev/null; echo "0 3 * * 0 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/cron-wrap.sh kamil-gap-watcher /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-gap-watcher.py >> /tmp/kamil-gap-watcher.log 2>&1") | crontab -
```

- [ ] **Step 5: Smoke-test the watcher manually**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 .claude/hooks/kamil-gap-watcher.py
```
Expected: exits cleanly (no gaps yet since gaps require 2+ occurrences). No tracebacks.

- [ ] **Step 6: Commit**

```bash
git add .claude/hooks/kamil-gap-watcher.py
git commit -m "feat: rewrite gap-watcher — harness.db query, CAPABILITIES.md promotion, Notion tickets"
```

---

## Task 7: End-to-end smoke test

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/test_capability_honesty.py -v
```
Expected: all tests pass.

- [ ] **Step 2: Verify listener imports cleanly**

```bash
python3 -c "
import sys
sys.path.insert(0, '.claude/hooks')
from infographic_handler import extract_topic, detect_palette, parse_nlm_points
from honesty_gate import check, contains_delivery_claim
from kamil_harness_db import get_db, log_capability_gap, get_capability_gaps
print('All imports OK')
print('extract_topic:', extract_topic('make an infographic about pullups'))
print('detect_palette:', detect_palette('calisthenics pullup'))
print('honesty check (clean):', check('Here is what I know.', uploaded=False, request='tell me')[:30])
print('honesty flag:', contains_delivery_claim('Here it is! I posted the image.'))
"
```
Expected:
```
All imports OK
extract_topic: pullups
detect_palette: fitness
honesty check (clean): Here is what I know.
honesty flag: True
```

- [ ] **Step 3: Test the gap logging end-to-end**

```bash
python3 -c "
import sys
sys.path.insert(0, '.claude/hooks')
from kamil_harness_db import get_db, log_capability_gap, get_capability_gaps
db = get_db()
log_capability_gap(db, 'inline_image_arbitrary', 'test request', 'render', 'text')
log_capability_gap(db, 'inline_image_arbitrary', 'test request 2', 'render', 'text')
gaps = get_capability_gaps(db, days=7, min_count=2)
print('Gaps with 2+ occurrences:', [g['gap_type'] for g in gaps])
"
```
Expected: `Gaps with 2+ occurrences: ['inline_image_arbitrary']`

- [ ] **Step 4: Final commit**

```bash
git add -p  # review any unstaged changes
git commit -m "test: end-to-end smoke tests for capability honesty system"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| `CAPABILITIES.md` machine-readable manifest | Task 2 |
| Inject manifest into Claude prompt | Task 5, Step 4 |
| `is_visual_request()` intent detection | Task 5, Step 2 |
| Visual routing before generic Claude call | Task 5, Step 3 |
| `infographic_handler.py` — NLM → PNG → upload | Task 3 |
| Honest fallback per failure step | Task 3, Step 3 (5 fallback paths) |
| `honesty_gate.py` — pre-send false claim check | Task 4 |
| Gate wired between run_claude and chat_postMessage | Task 5, Step 5 |
| `capability_gaps` table in harness.db | Task 1 |
| `log_capability_gap()` called from both handler and gate | Tasks 3 + 4 |
| `kamil-gap-watcher.py` promotes gaps → CAPABILITIES.md | Task 6 |
| Gap watcher DMs Kamal | Task 6, Step 3 |
| Gap watcher opens Notion Harness ticket at priority >= 4 | Task 6, Step 3 |
| reaction signal from eval_tracker feeds gap priority | Not yet wired — out of scope for this plan, `update_gap_reaction()` is available for a follow-up |
| Listener restarts cleanly | Task 5, Step 6 |

All spec requirements covered. Reaction signal wiring is the one item deferred — `update_gap_reaction()` exists in harness_db, but wiring it to `record_reaction()` in `kamil_eval_tracker.py` is a separate clean task that doesn't block the core system.
