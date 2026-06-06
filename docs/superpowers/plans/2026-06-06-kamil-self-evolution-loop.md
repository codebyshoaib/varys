# Kamil Self-Evolution Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every time Kamil researches a topic in NotebookLM and posts it on LinkedIn, he also extracts what he should *build* from those insights and creates concrete Harness tickets — so research drives improvement, not just content.

**Architecture:** NLM research → `brain_seed_from_content.py` stores structured learnings in `brain.db` → `kamil-apply-learnings.py` (Application Agent) reads those learnings, asks Claude to identify gaps vs Kamil's current harness, and writes Notion Harness tickets. Both scripts are already created and working. This plan hardens them, adds dedup to avoid duplicate tickets, improves the Slack DM format, ensures `stop.py` also seeds learnings from engineering sessions, and adds a session-start summary of pending [Auto] Harness tickets.

**Tech Stack:** Python 3, SQLite (brain.db), Notion API (urllib), Slack API (urllib), `claude` CLI subprocess, cron via `cron-wrap.sh`

---

## File Map

| File | Status | Role |
|---|---|---|
| `.claude/hooks/kamil-apply-learnings.py` | **Exists** — needs dedup + richer Slack DM | Application Agent: reads brain.db → finds gaps → creates Harness tickets |
| `.claude/hooks/brain_seed_from_content.py` | **Exists** — needs `_run_application_agent` test coverage | Seeder: NLM insights → brain.db learning entities |
| `.claude/hooks/stop.py` | **Modify** — add engineering session seed call | Session end hook: currently only git commits, should also seed engineering decisions |
| `.claude/hooks/session-start.py` | **Modify** — add pending [Auto] ticket surface | Session start: surface pending Harness tickets derived from learnings |
| `tests/test_apply_learnings.py` | **Create** | Unit tests for gap dedup, ticket creation, Slack DM formatting |

---

### Task 1: Dedup — don't create the same ticket twice

**Problem:** Running `kamil-apply-learnings.py --days 7` twice creates duplicate Harness tickets (same title). Need a local dedup check before writing to Notion.

**Files:**
- Modify: `.claude/hooks/kamil-apply-learnings.py`
- Create: `tests/test_apply_learnings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_apply_learnings.py
import sys
sys.path.insert(0, ".claude/hooks")
from unittest.mock import patch, MagicMock
import kamil_apply_learnings as kal

def test_dedup_skips_existing_title():
    """Gap with same normalised title as existing Notion ticket should be skipped."""
    gap = {"title": "Durable execution for kamil-listener", "what_to_build": "x", "why": "y", "priority": "P1", "effort": "medium"}
    existing_titles = {"[auto] durable execution for kamil-listener"}
    assert kal._is_duplicate(gap, existing_titles) is True

def test_dedup_allows_new_title():
    gap = {"title": "Brand new feature nobody built yet", "what_to_build": "x", "why": "y", "priority": "P1", "effort": "medium"}
    existing_titles = {"[auto] durable execution for kamil-listener"}
    assert kal._is_duplicate(gap, existing_titles) is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m pytest tests/test_apply_learnings.py -v 2>&1 | head -30
```

Expected: `AttributeError: module 'kamil_apply_learnings' has no attribute '_is_duplicate'`

- [ ] **Step 3: Add `_is_duplicate` and `_fetch_existing_ticket_titles` to `kamil-apply-learnings.py`**

Add these two functions right before `create_harness_ticket`:

```python
def _fetch_existing_ticket_titles(notion_token: str) -> set[str]:
    """Return normalised set of existing [Auto] ticket titles from Harness DB."""
    data = json.dumps({
        "filter": {"property": "Feature", "title": {"contains": "[Auto]"}},
        "page_size": 100,
    }).encode()
    req = urllib.request.Request(
        f"{NOTION_API}/databases/{HARNESS_DB_ID}/query", data=data,
        headers={
            "Authorization":  f"Bearer {notion_token}",
            "Content-Type":   "application/json",
            "Notion-Version": "2022-06-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())
            titles = set()
            for page in result.get("results", []):
                raw = page["properties"].get("Feature", {}).get("title", [])
                if raw:
                    titles.add(raw[0]["plain_text"].lower())
            return titles
    except Exception as e:
        print(f"[apply-learnings] Could not fetch existing titles: {e}")
        return set()


def _is_duplicate(gap: dict, existing_titles: set[str]) -> bool:
    """Return True if a ticket for this gap already exists."""
    normalised = f"[auto] {gap['title'].lower()}"
    return normalised in existing_titles
```

- [ ] **Step 4: Update `run()` to fetch existing titles and skip duplicates**

In `run()`, replace the `for gap in gaps:` loop:

```python
    notion_token = _notion_token()
    slack_token  = _load_slack_token()
    existing     = _fetch_existing_ticket_titles(notion_token) if notion_token else set()
    created      = []

    for gap in gaps:
        if _is_duplicate(gap, existing):
            print(f"[apply-learnings] Skip duplicate: {gap['title']}")
            continue
        page_id = create_harness_ticket(gap, notion_token) if notion_token else ""
        if page_id:
            existing.add(f"[auto] {gap['title'].lower()}")  # prevent double-create in same run
        created.append({"gap": gap, "page_id": page_id})
        klog("apply_learning_ticket", component="kamil-apply-learnings",
             title=gap["title"], priority=gap.get("priority"), page_id=page_id[:8] if page_id else "")
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_apply_learnings.py -v 2>&1
```

Expected: both tests PASS.

- [ ] **Step 6: Commit**

```bash
git add .claude/hooks/kamil-apply-learnings.py tests/test_apply_learnings.py
git commit -m "feat: dedup [Auto] Harness tickets in apply-learnings"
```

---

### Task 2: Richer Slack DM — include the "why" and link to Notion

**Problem:** Current Slack DM shows title + what_to_build but omits the `why` (the research insight that justifies the ticket) and has no Notion link. Kamal can't triage without context.

**Files:**
- Modify: `.claude/hooks/kamil-apply-learnings.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_apply_learnings.py`:

```python
def test_slack_message_includes_why():
    item = {
        "gap": {
            "title": "Adversarial checker agent",
            "what_to_build": "Add an agent that verifies Kamil outputs",
            "why": "Lesson: silent failures are invisible without an adversary",
            "priority": "P0",
            "effort": "medium",
        },
        "page_id": "abc123def456",
    }
    import kamil_apply_learnings as kal
    msg = kal._format_slack_message([item], ["[tech] harness research"])
    assert "silent failures" in msg
    assert "abc123" in msg  # page_id prefix in Notion URL
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_apply_learnings.py::test_slack_message_includes_why -v
```

Expected: `AttributeError: module has no attribute '_format_slack_message'`

- [ ] **Step 3: Extract `_format_slack_message` from inline code in `slack_dm` call**

Add this function above `slack_dm`:

```python
def _format_slack_message(created: list[dict], learning_names: list[str]) -> str:
    topics = ", ".join(f"*{n.split(']')[-1].strip()[:30]}*" for n in learning_names)
    lines  = [f"🧠 *Kamil learned + applied:* {topics}\n"]
    for item in created:
        g        = item["gap"]
        page_id  = item.get("page_id", "")
        notion_url = (
            f"https://notion.so/{page_id.replace('-', '')}"
            if page_id else ""
        )
        lines.append(f"• *[{g.get('priority','P1')}]* {g['title']}")
        lines.append(f"  _{g['what_to_build'][:100]}_")
        lines.append(f"  > {g.get('why','')[:120]}")
        if notion_url:
            lines.append(f"  <{notion_url}|Open in Notion>")
    lines.append(f"\n{len(created)} ticket(s) created — Kamil will build these.\n🤖 Kamil")
    return "\n".join(lines)
```

- [ ] **Step 4: Update `run()` to use `_format_slack_message`**

Replace the inline Slack message building block in `run()`:

```python
    if notify_slack and slack_token and created:
        text = _format_slack_message(created, [l["name"] for l in learnings])
        slack_dm(slack_token, text)
```

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/test_apply_learnings.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add .claude/hooks/kamil-apply-learnings.py tests/test_apply_learnings.py
git commit -m "feat: richer Slack DM for apply-learnings (why + Notion link)"
```

---

### Task 3: Seed engineering session decisions into brain.db on session end

**Problem:** `stop.py` only does a git commit. When Kamil engineers something (a new hook, a pattern, a decision), that knowledge is lost. `stop.py` should ask Claude: "What did this session decide or build?" and seed that into brain.db.

**Files:**
- Modify: `.claude/hooks/stop.py`

- [ ] **Step 1: Read current `stop.py` to understand entry point**

```bash
grep -n "def main\|subprocess\|git commit\|sys.exit" /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/stop.py | head -20
```

- [ ] **Step 2: Add `_seed_session_to_brain` at bottom of `stop.py`, before `main()`**

```python
def _seed_session_to_brain():
    """
    On session end, extract what was built/decided and seed into brain.db.
    Non-fatal — never blocks the stop hook.
    """
    import subprocess
    from pathlib import Path
    hooks_dir = Path(__file__).parent

    # Get today's session log for context
    log_path = Path("/home/oye/Documents/free_work/personal-agent-v2/vault/logs") / \
               f"{__import__('datetime').date.today()}.md"
    if not log_path.exists():
        return

    log_text = log_path.read_text()[-3000:]  # last 3000 chars = recent work
    if len(log_text) < 100:
        return

    prompt = (
        f"From this engineering session log, extract what was built or decided.\n"
        f"Output ONLY valid JSON with:\n"
        f"  key_insights: list of up to 3 concrete patterns or decisions (max 20 words each)\n"
        f"  lessons_learned: list of up to 2 lessons for future Kamil (what to do / avoid)\n"
        f"  tools_mentioned: list of tools/scripts/files that were created or significantly changed\n"
        f"  one_line_summary: single sentence, the most important outcome of this session\n\n"
        f"Session log:\n{log_text}\n\nJSON only."
    )
    try:
        r = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt],
            capture_output=True, text=True, timeout=60,
        )
        raw = r.stdout.strip()
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start < 0 or end <= start:
            return
        structured = __import__("json").loads(raw[start:end])
    except Exception:
        return

    try:
        seed_mod = hooks_dir / "brain_seed_from_content.py"
        spec = __import__("importlib.util", fromlist=["util"]).util.spec_from_file_location(
            "brain_seed", str(seed_mod)
        )
        mod = __import__("importlib.util", fromlist=["util"]).util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Reuse _write_to_brain directly
        mod._write_to_brain(
            topic=f"Engineering session {__import__('datetime').date.today()}",
            track="tech",
            nb_id="session-stop",
            structured=structured,
            session_id="",
            source="session_stop",
        )
        print("[stop] Session decisions seeded to brain.db")
    except Exception as e:
        print(f"[stop] Brain seed failed (non-fatal): {e}")
```

- [ ] **Step 3: Call `_seed_session_to_brain()` in `main()` before git commit**

Find the line in `main()` that does the git commit and add the call before it:

```python
    _seed_session_to_brain()
    # ... existing git commit code ...
```

- [ ] **Step 4: Manually verify it runs without error**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "
import sys
sys.path.insert(0, '.claude/hooks')
# Simulate a session log existing
from pathlib import Path
import datetime
log = Path('vault/logs') / f'{datetime.date.today()}.md'
print('log exists:', log.exists(), 'size:', log.stat().st_size if log.exists() else 0)
"
```

Then run directly:
```bash
python3 .claude/hooks/stop.py --dry-run 2>&1 | tail -5
```

Expected: `[stop] Session decisions seeded to brain.db` (or `log too short` if log is empty today)

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks/stop.py
git commit -m "feat: seed engineering session decisions to brain.db on session end"
```

---

### Task 4: Surface pending [Auto] Harness tickets at session start

**Problem:** Tickets are created but Kamil doesn't see them unless he checks Notion. `session-start.py` already surfaces Slack inbox and recent learnings — it should also show pending [Auto] Harness tickets so Kamal knows what the Application Agent queued.

**Files:**
- Modify: `.claude/hooks/session-start.py`

- [ ] **Step 1: Add `_fetch_auto_tickets` function to `session-start.py`**

Add right before `build_system_message`:

```python
def _fetch_auto_tickets() -> list[dict]:
    """
    Fetch pending [Auto] Harness tickets from Notion.
    Returns list of dicts with 'title' and 'phase'.
    """
    import urllib.request as _ur
    notion_cfg = Path("/home/oye/.claude/hooks/.notion")
    token = ""
    if notion_cfg.exists():
        for line in notion_cfg.read_text().splitlines():
            if line.startswith("NOTION_API_KEY="):
                token = line.split("=", 1)[1].strip()
    if not token:
        return []

    data = json.dumps({
        "filter": {
            "and": [
                {"property": "Feature", "title": {"contains": "[Auto]"}},
                {"property": "Phase",   "select": {"does_not_equal": "Done"}},
            ]
        },
        "page_size": 10,
    }).encode()

    try:
        req = _ur.Request(
            "https://api.notion.com/v1/databases/de10157da3e34ef58a74ea240f31fe98/query",
            data=data,
            headers={
                "Authorization":  f"Bearer {token}",
                "Content-Type":   "application/json",
                "Notion-Version": "2022-06-28",
            },
        )
        with _ur.urlopen(req, timeout=8) as r:
            result = json.loads(r.read())
            tickets = []
            for page in result.get("results", []):
                title = page["properties"].get("Feature", {}).get("title", [])
                phase = page["properties"].get("Phase",   {}).get("select") or {}
                tickets.append({
                    "title": title[0]["plain_text"] if title else "?",
                    "phase": phase.get("name", "Backlog"),
                })
            return tickets
    except Exception:
        return []
```

- [ ] **Step 2: Call `_fetch_auto_tickets()` inside `build_system_message()` and append section**

Add after the learnings block (after the `except Exception: pass` that closes the brain.db block):

```python
    # Surface pending [Auto] tickets from Application Agent
    try:
        auto_tickets = _fetch_auto_tickets()
        if auto_tickets:
            lines.append("## 🔧 Pending Self-Improvement Tickets (from research)")
            lines.append("*(These were auto-created by Kamil's Application Agent — derived from NLM research)*")
            for t in auto_tickets:
                lines.append(f"- [{t['phase']}] {t['title']}")
            lines.append("")
    except Exception:
        pass
```

- [ ] **Step 3: Verify manually**

```bash
python3 .claude/hooks/session-start.py 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['systemMessage'])" | grep -A 10 "Self-Improvement"
```

Expected output includes the 5 tickets just created:
```
## 🔧 Pending Self-Improvement Tickets (from research)
- [Backlog] [Auto] Durable execution for kamil-listener and subagents
- [Backlog] [Auto] LLM-based fact extraction from session logs
...
```

- [ ] **Step 4: Commit**

```bash
git add .claude/hooks/session-start.py
git commit -m "feat: surface pending [Auto] Harness tickets at session start"
```

---

### Task 5: End-to-end smoke test

**Goal:** Prove the full loop works in one pass — seed → analyse → dedup → notify — without hitting real Notion or Slack.

**Files:**
- Create: `tests/test_self_evolution_e2e.py`

- [ ] **Step 1: Write the e2e test**

```python
# tests/test_self_evolution_e2e.py
"""
End-to-end smoke test for the self-evolution loop.
Uses a real (temp) brain.db but mocks Notion and Slack API calls.
"""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, ".claude/hooks")

import kamil_apply_learnings as kal


def _make_brain_db(path: str) -> None:
    """Create a minimal brain.db with one learning entity and facts."""
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE entities (
        id TEXT PRIMARY KEY, type TEXT, name TEXT, created_at TEXT DEFAULT (datetime('now'))
    )""")
    db.execute("""CREATE TABLE facts (
        id TEXT PRIMARY KEY, subject_id TEXT, predicate TEXT, object_val TEXT,
        source TEXT, session_id TEXT, created_at TEXT DEFAULT (datetime('now'))
    )""")
    db.execute("INSERT INTO entities VALUES ('learn-test-1', 'learning', '[tech] adversarial agents', datetime('now'))")
    db.execute("INSERT INTO facts VALUES ('f1', 'learn-test-1', 'key_insight',     'Use multiple agents to verify each other', 'test', '', datetime('now'))")
    db.execute("INSERT INTO facts VALUES ('f2', 'learn-test-1', 'lesson_learned',  'Silent failures are invisible without adversarial checks', 'test', '', datetime('now'))")
    db.execute("INSERT INTO facts VALUES ('f3', 'learn-test-1', 'one_line_summary','Adversarial multi-agent design catches what single agents miss', 'test', '', datetime('now'))")
    db.commit()
    db.close()


def test_full_loop_no_real_apis():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    _make_brain_db(db_path)

    fake_gaps = [
        {"title": "Add adversarial checker", "what_to_build": "Spawn a verifier agent after each output.",
         "why": "Silent failures are invisible without adversarial checks", "priority": "P1", "effort": "medium"},
    ]

    with patch.object(kal, "BRAIN_DB", Path(db_path)), \
         patch.object(kal, "analyse_gaps",             return_value=fake_gaps), \
         patch.object(kal, "_fetch_existing_ticket_titles", return_value=set()), \
         patch.object(kal, "create_harness_ticket",    return_value="fake-page-id-001"), \
         patch.object(kal, "slack_dm") as mock_slack:

        kal.run(days=1, notify_slack=True)

        # Slack was called once with the formatted message
        mock_slack.assert_called_once()
        msg = mock_slack.call_args[0][1]
        assert "adversarial checker" in msg.lower()
        assert "silent failures" in msg.lower()

    Path(db_path).unlink(missing_ok=True)
```

- [ ] **Step 2: Run the e2e test**

```bash
python3 -m pytest tests/test_self_evolution_e2e.py -v
```

Expected: PASS

- [ ] **Step 3: Run all tests**

```bash
python3 -m pytest tests/test_apply_learnings.py tests/test_self_evolution_e2e.py -v
```

Expected: 4 tests PASS, 0 failed.

- [ ] **Step 4: Commit**

```bash
git add tests/test_self_evolution_e2e.py
git commit -m "test: e2e smoke test for self-evolution loop"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|---|---|
| Dedup — no repeated Notion tickets | Task 1 |
| Richer Slack DM with why + Notion link | Task 2 |
| Engineering sessions also seed brain.db | Task 3 |
| Pending tickets surfaced at session start | Task 4 |
| Full loop verified with tests | Task 5 |

**Placeholder scan:** None found — all steps include real code.

**Type consistency:**
- `_is_duplicate(gap: dict, existing_titles: set[str]) -> bool` — defined Task 1, used Task 1. ✓
- `_fetch_existing_ticket_titles(notion_token: str) -> set[str]` — defined Task 1, called Task 1. ✓
- `_format_slack_message(created: list[dict], learning_names: list[str]) -> str` — defined Task 2, called Task 2. ✓
- `_fetch_auto_tickets() -> list[dict]` — defined Task 4, called Task 4. ✓
- `_seed_session_to_brain()` — defined Task 3, called Task 3. ✓
