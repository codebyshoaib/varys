# Smart Content Scheduler v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a daily content pipeline that scans trending topics, scores them, creates visual-first content via NotebookLM for 3 tracks (fitness, tech, vlog), auto-posts tech to LinkedIn, and DMs Kamal on Slack with everything ready to post.

**Architecture:** `trend-scanner.py` handles isolated web search + scoring logic; `content-scheduler.py` (rewrite) orchestrates the full pipeline — trend scan → topic pick from Notion DB → NLM research + 3 visual artifacts → image generation → LinkedIn post (tech) → Slack DM. Notion Content Calendar DB is created first and seeded with 25 topics.

**Tech Stack:** Python 3, `nlm` CLI (`/home/oye/.local/bin/nlm`), `image_generator.py`, `vertical_converter.py`, `linkedin_poster.py`, `kamil_log.py`, Notion MCP (via subprocess claude call for DB creation), Slack Bot API, WebSearch via subprocess claude call.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `.claude/hooks/trend-scanner.py` | **Create** | Web search for trending topics, score 0–100, return ranked list |
| `.claude/hooks/content-scheduler.py` | **Rewrite** | Full pipeline orchestrator — calls all other modules |
| `vault/notion-map.md` | **Update** | Add new Content Calendar DB ID once created |

---

### Task 1: Create Notion Content Calendar Database and seed 25 topics

**Files:**
- Run: Notion MCP via claude subprocess

- [ ] **Step 1: Create the Notion DB via MCP**

Run this command (uses the Notion MCP connected in the session):

```bash
claude --dangerously-skip-permissions --print -p "
Create a Notion database called 'Content Calendar' as a child of page 364d8747b3b1813d8ac8c248800f0a4d (Kamal's Agent Brain).

Properties to create:
- Topic (title)
- Track (select): options = fitness, tech, vlog
- Status (select): options = Pending, In Progress, Done
- EngagementScore (number)
- EngagementReason (rich_text)
- Source (select): options = queue, trending
- NLMNotebookID (rich_text)
- PostedDate (date)
- PostType (select): options = qa, steps, info, tip, script

After creating the DB, print the DB ID on a line by itself prefixed with 'DB_ID:'.
" 2>&1 | grep "DB_ID:"
```

- [ ] **Step 2: Note the DB ID from output**

Copy the ID printed after `DB_ID:` — you'll need it in the next step.
Format: `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` (32 hex chars) or UUID.

- [ ] **Step 3: Seed all 25 topics via MCP**

```bash
claude --dangerously-skip-permissions --print -p "
Add the following pages to Notion DB [PASTE_DB_ID_HERE]:

FITNESS topics (Track=fitness, Status=Pending, Source=queue, EngagementScore=60):
1. Calisthenics Pull-Up Progression for Beginners
2. Swimming Freestyle Breathing Mistakes
3. Hiking Essentials Pakistan Trails
4. Cycling Training Zones Explained
5. Calisthenics vs Gym — Which Is Better
6. Weekly Calisthenics Split for Beginners
7. Recovery and Avoiding Overtraining
8. Swimming Workouts for Non-Swimmers
9. Pakistan Hiking Trails Islamabad to Kashmir
10. 30-Day Calisthenics Challenge Plan

TECH topics (Track=tech, Status=Pending, Source=queue, EngagementScore=60):
11. Build a Personal AI Agent in a Weekend
12. Claude Code vs ChatGPT for Developers
13. Django Multi-Tenant Architecture Explained
14. How I Reduced API Latency 40 Percent
15. 5 Claude Prompts Every Developer Needs
16. Building Kamil What I Learned About Autonomous Agents
17. AWS ECS vs Traditional Servers When to Use Which
18. Zero-Downtime Database Migrations Explained
19. How to Use NotebookLM for Research
20. AI Tools That Actually Save Developer Time 2026

VLOG topics (Track=vlog, Status=Pending, Source=queue, EngagementScore=60, PostType=script):
21. Morning Routine Islamabad
22. F-7 Markaz Street Food Day
23. Margalla Hills Sunrise Hike
24. Islamabad Cafe Culture
25. Weekend Road Trip from Islamabad

Create all 25 pages. Confirm when done.
" 2>&1
```

- [ ] **Step 4: Update vault/notion-map.md with the new DB ID**

Edit `vault/notion-map.md`. In the Databases table, update the Content Calendar row with the real DB ID from Step 2:

```markdown
| Content Calendar | `PASTE_REAL_ID_HERE` | Social media topics (Pending/In Progress/Done) |
```

- [ ] **Step 5: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add vault/notion-map.md
git commit -m "feat: create Notion Content Calendar DB, seed 25 topics"
```

---

### Task 2: Build trend-scanner.py

**Files:**
- Create: `.claude/hooks/trend-scanner.py`

- [ ] **Step 1: Create the file**

```python
#!/usr/bin/env python3
"""
trend-scanner.py — Scans web for trending topics for a given track.

Returns ranked list of candidate topics with engagement scores.

Usage:
    from trend_scanner import scan_trends
    results = scan_trends("fitness")
    # returns: [{"topic": "...", "score": 82, "reason": "..."}, ...]

Score breakdown (0-100):
    +35  trending on Reddit or Twitter right now
    +25  high search interest (recent articles/videos this week)
    +20  tight match to track niche
    +15  timely (seasonal, news event, viral moment)
    +5   baseline for any found result
"""

import json
import subprocess
import sys
from datetime import datetime

TRACK_NICHES = {
    "fitness": "calisthenics bodyweight fitness swimming hiking cycling workout",
    "tech":    "Claude AI coding Python Django software engineering developer tools",
    "vlog":    "Islamabad Pakistan daily life food travel vlog",
}

TRACK_SEARCH_QUERIES = {
    "fitness": [
        "calisthenics trending workout site:reddit.com",
        "bodyweight fitness viral tips {month} {year}",
        "swimming hiking cycling trending social media {year}",
    ],
    "tech": [
        "Claude AI developer tips trending site:reddit.com",
        "Python Django coding viral post {month} {year}",
        "AI tools developer trending Twitter {month} {year}",
    ],
    "vlog": [
        "Islamabad things to do {month} {year}",
        "Pakistan travel vlog trending {year}",
        "Islamabad food street events {month}",
    ],
}


def _web_search(query: str) -> str:
    """Run a web search via claude subprocess. Returns text results."""
    prompt = (
        f"Search the web for: {query}\n"
        f"Return a JSON list of up to 5 results, each with: "
        f'{{\"title\": \"...\", \"summary\": \"...\", \"url\": \"...\", \"recency\": \"today|this week|this month|older\"}}\n'
        f"Return ONLY valid JSON, no other text."
    )
    try:
        r = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt],
            capture_output=True, text=True, timeout=60
        )
        return r.stdout.strip()
    except Exception as e:
        return f"[]"


def _score_result(result: dict, track: str) -> int:
    """Score a single search result 0-100."""
    score = 5  # baseline
    summary = (result.get("summary", "") + result.get("title", "")).lower()
    recency = result.get("recency", "older")
    niche_words = TRACK_NICHES.get(track, "").lower().split()

    # Recency signals
    if recency == "today":
        score += 35
    elif recency == "this week":
        score += 20
    elif recency == "this month":
        score += 10

    # Search interest
    if any(w in summary for w in ["viral", "trending", "popular", "top", "best"]):
        score += 25
    elif any(w in summary for w in ["guide", "tips", "how to", "tutorial"]):
        score += 15

    # Niche match
    matches = sum(1 for w in niche_words if w in summary)
    score += min(matches * 4, 20)

    # Timeliness
    current_month = datetime.now().strftime("%B").lower()
    current_year  = str(datetime.now().year)
    if current_month in summary or current_year in summary:
        score += 15

    return min(score, 100)


def _extract_topic(result: dict, track: str) -> str:
    """Convert a search result title into a clean content topic."""
    title = result.get("title", "")
    # Strip site names, dates, clickbait patterns
    for noise in ["- Reddit", "| Twitter", "- YouTube", " r/", " via "]:
        title = title.split(noise)[0]
    return title.strip()[:80]


def scan_trends(track: str) -> list[dict]:
    """
    Scan web for trending topics for this track.
    Returns list of dicts sorted by score desc:
      [{"topic": str, "score": int, "reason": str}, ...]
    Only returns results with score >= 50.
    """
    if track not in TRACK_SEARCH_QUERIES:
        return []

    month = datetime.now().strftime("%B")
    year  = str(datetime.now().year)
    candidates: list[dict] = []

    for query_tmpl in TRACK_SEARCH_QUERIES[track]:
        query = query_tmpl.format(month=month, year=year)
        raw   = _web_search(query)
        try:
            results = json.loads(raw)
            if not isinstance(results, list):
                continue
        except Exception:
            continue

        for r in results:
            score = _score_result(r, track)
            if score < 50:
                continue
            topic  = _extract_topic(r, track)
            reason = (
                f"Found: '{r.get('title','')}' "
                f"(recency={r.get('recency','?')}, score={score})"
            )
            candidates.append({"topic": topic, "score": score, "reason": reason})

    # Deduplicate by topic similarity (simple: exact match)
    seen: set[str] = set()
    unique = []
    for c in candidates:
        key = c["topic"].lower()[:40]
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return sorted(unique, key=lambda x: x["score"], reverse=True)


if __name__ == "__main__":
    track = sys.argv[1] if len(sys.argv) > 1 else "fitness"
    results = scan_trends(track)
    print(f"\nTrending topics for '{track}':")
    for r in results:
        print(f"  [{r['score']:3d}] {r['topic']}")
        print(f"         {r['reason']}")
```

- [ ] **Step 2: Smoke test**

```bash
python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/trend-scanner.py fitness
# Expected: list of scored topics, at least 1 result
python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/trend-scanner.py tech
# Expected: list of scored topics
python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/trend-scanner.py vlog
# Expected: list of Islamabad-related topics
```

- [ ] **Step 3: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/hooks/trend-scanner.py
git commit -m "feat: add trend-scanner.py — web search + 0-100 engagement scoring"
```

---

### Task 3: Rewrite content-scheduler.py — full v2 pipeline

**Files:**
- Rewrite: `.claude/hooks/content-scheduler.py`

- [ ] **Step 1: Replace the file entirely**

```python
#!/usr/bin/env python3
"""
content-scheduler.py — Smart Content Scheduler v2.

Daily pipeline at 11am PKT (6am UTC via cron):
  1. Trend scan (fitness or tech alternating) + vlog always
  2. Insert trending topics into Notion Content Calendar DB
  3. Pick highest-scored Pending topic per track
  4. NLM: research + slides + infographic + mindmap (visual-first)
  5. image_generator: branded 1080x1350 portrait image
  6. vertical_converter: convert NLM infographic to portrait
  7. LinkedIn auto-post (tech track only)
  8. Slack DM: 3 images + caption (fitness/tech) or script (vlog)
  9. Mark Done in Notion

Cron: 0 6 * * * python3 .claude/hooks/content-scheduler.py >> /tmp/kamil-content.log 2>&1

Notion Content Calendar DB ID: set NOTION_CONTENT_DB below after Task 1.
"""

import json
import os
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_log import klog, klog_error

# ─── Config ───────────────────────────────────────────────────────────────────

HOOKS_DIR          = Path(__file__).parent
KAMIL_DIR          = HOOKS_DIR.parent.parent
SLACK_CFG          = Path.home() / ".claude" / "hooks" / ".slack"
KAMAL_DM           = "D0B415M06SK"
NLM                = "/home/oye/.local/bin/nlm"

# !! UPDATE THIS after Task 1 creates the DB !!
NOTION_CONTENT_DB  = "PASTE_DB_ID_HERE"

# Which track runs today (fitness/tech alternate by day-of-year parity)
def todays_ft_track() -> str:
    return "fitness" if date.today().toordinal() % 2 == 0 else "tech"

HANDLES = {"fitness": "@oykamal", "tech": "@oykamal", "vlog": "@oykamal"}

# ─── Slack ────────────────────────────────────────────────────────────────────

def load_slack_token() -> str:
    if SLACK_CFG.exists():
        for line in SLACK_CFG.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def slack_dm(token: str, text: str):
    if not token:
        print(f"[scheduler] No token, would DM: {text[:60]}")
        return
    data = json.dumps({"channel": KAMAL_DM, "text": text}).encode()
    req  = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", data=data,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
            if not resp.get("ok"):
                print(f"[scheduler] Slack DM failed: {resp.get('error')}")
    except Exception as e:
        print(f"[scheduler] Slack DM error: {e}")


def slack_upload(token: str, filepath: str, title: str, comment: str = ""):
    """Upload a file to Kamal's DM."""
    try:
        with open(filepath, "rb") as f:
            file_data = f.read()

        params = f"filename={Path(filepath).name}&length={len(file_data)}"
        req = urllib.request.Request(
            f"https://slack.com/api/files.getUploadURLExternal?{params}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
        if not resp.get("ok"):
            print(f"[scheduler] Upload URL failed: {resp.get('error')}")
            return

        upload_url = resp["upload_url"]
        file_id    = resp["file_id"]

        req2 = urllib.request.Request(upload_url, data=file_data, method="POST")
        req2.add_header("Content-Type", "application/octet-stream")
        with urllib.request.urlopen(req2, timeout=30):
            pass

        payload = json.dumps({
            "files": [{"id": file_id, "title": title}],
            "channel_id": KAMAL_DM,
            "initial_comment": comment,
        }).encode()
        req3 = urllib.request.Request(
            "https://slack.com/api/files.completeUploadExternal",
            data=payload,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req3, timeout=10) as r:
            result = json.loads(r.read())
        if not result.get("ok"):
            print(f"[scheduler] Upload complete failed: {result.get('error')}")
    except Exception as e:
        print(f"[scheduler] File upload error: {e}")

# ─── Notion ───────────────────────────────────────────────────────────────────

def _notion_token() -> str:
    for path in [KAMIL_DIR / ".claude" / "settings.json",
                 Path.home() / ".claude" / "settings.json"]:
        if not path.exists():
            continue
        try:
            cfg = json.loads(path.read_text())
            for name, srv in cfg.get("mcpServers", {}).items():
                if "notion" in name.lower():
                    for k, v in srv.get("env", {}).items():
                        if "token" in k.lower() or "key" in k.lower():
                            return v
        except Exception:
            pass
    return os.environ.get("NOTION_TOKEN", "")


def notion_query(db_id: str, filter_body: dict) -> list[dict]:
    token = _notion_token()
    if not token:
        return []
    body = json.dumps(filter_body).encode()
    req  = urllib.request.Request(
        f"https://api.notion.com/v1/databases/{db_id}/query",
        data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Notion-Version": "2022-06-28",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()).get("results", [])
    except Exception as e:
        print(f"[scheduler] Notion query error: {e}")
        return []


def notion_create_page(db_id: str, properties: dict):
    token = _notion_token()
    if not token:
        return
    body = json.dumps({"parent": {"database_id": db_id},
                       "properties": properties}).encode()
    req  = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Notion-Version": "2022-06-28",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
    except Exception as e:
        print(f"[scheduler] Notion create page error: {e}")


def notion_update_page(page_id: str, properties: dict):
    token = _notion_token()
    if not token:
        return
    body = json.dumps({"properties": properties}).encode()
    req  = urllib.request.Request(
        f"https://api.notion.com/v1/pages/{page_id}",
        data=body, method="PATCH",
        headers={"Authorization": f"Bearer {token}",
                 "Notion-Version": "2022-06-28",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
    except Exception as e:
        print(f"[scheduler] Notion update error: {e}")


def prop_text(page: dict, key: str) -> str:
    prop  = page.get("properties", {}).get(key, {})
    ptype = prop.get("type", "")
    if ptype == "title":
        return "".join(t["plain_text"] for t in prop.get("title", []))
    if ptype == "rich_text":
        return "".join(t["plain_text"] for t in prop.get("rich_text", []))
    if ptype == "select":
        sel = prop.get("select")
        return sel["name"] if sel else ""
    if ptype == "number":
        return str(prop.get("number") or "")
    return ""

# ─── Trend scanning + Notion insert ──────────────────────────────────────────

def run_trend_scan(track: str, token: str):
    """Scan trends, insert scoring ≥50 into Notion as Pending topics."""
    print(f"[scheduler] Trend scan: {track}")
    sys.path.insert(0, str(HOOKS_DIR))
    try:
        from trend_scanner import scan_trends
        results = scan_trends(track)
    except Exception as e:
        print(f"[scheduler] Trend scan error: {e}")
        return

    inserted = 0
    for r in results:
        score  = r["score"]
        topic  = r["topic"]
        reason = r["reason"]
        source = "trending"
        notion_create_page(NOTION_CONTENT_DB, {
            "Topic":           {"title": [{"text": {"content": topic}}]},
            "Track":           {"select": {"name": track}},
            "Status":          {"select": {"name": "Pending"}},
            "EngagementScore": {"number": score},
            "EngagementReason":{"rich_text": [{"text": {"content": reason}}]},
            "Source":          {"select": {"name": source}},
        })
        inserted += 1
        print(f"[scheduler]   +{score} {topic}")

    print(f"[scheduler] Trend scan done: {inserted} topics added")

# ─── Topic selection ──────────────────────────────────────────────────────────

def pick_topic(track: str) -> tuple[str, str, str, int, str] | None:
    """
    Pick highest-scored Pending topic for track.
    Returns (page_id, topic, post_type, score, reason) or None.
    """
    pages = notion_query(NOTION_CONTENT_DB, {
        "filter": {"and": [
            {"property": "Status", "select": {"equals": "Pending"}},
            {"property": "Track",  "select": {"equals": track}},
        ]},
        "sorts":    [{"property": "EngagementScore", "direction": "descending"}],
        "page_size": 1,
    })
    if not pages:
        return None
    page      = pages[0]
    page_id   = page["id"]
    topic     = prop_text(page, "Topic")
    post_type = prop_text(page, "PostType") or "steps"
    score     = int(prop_text(page, "EngagementScore") or "60")
    reason    = prop_text(page, "EngagementReason") or "pre-planned queue topic"
    notion_update_page(page_id, {"Status": {"select": {"name": "In Progress"}}})
    return page_id, topic, post_type, score, reason

# ─── NLM ─────────────────────────────────────────────────────────────────────

def run_nlm(args: list, timeout: int = 240) -> tuple[bool, str]:
    try:
        r = subprocess.run([NLM] + args, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout.strip() or r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def nlm_create_notebook(topic: str) -> str | None:
    """Create NLM notebook, return notebook ID."""
    ok, out = run_nlm(["notebook", "create", "--json", "--title", topic], timeout=60)
    if ok:
        try:
            return json.loads(out).get("id")
        except Exception:
            import re
            m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', out)
            return m.group(0) if m else None
    print(f"[scheduler] NLM notebook create failed: {out[:100]}")
    return None


def nlm_research(nb_id: str, topic: str):
    ok, out = run_nlm(["research", "start", nb_id, "--query", topic, "--confirm"], timeout=300)
    print(f"[scheduler] NLM research: {'ok' if ok else 'failed'}")


def nlm_trigger_visuals(nb_id: str, topic: str):
    """Trigger slides + infographic + mindmap — all async in NLM."""
    # Visual-first: slides max 6 words per slide, large visuals
    run_nlm(["studio", "create", nb_id, "--type", "slide_deck",
             "--focus", topic, "--confirm"], timeout=60)
    run_nlm(["studio", "create", nb_id, "--type", "infographic",
             "--focus", topic, "--confirm"], timeout=60)
    run_nlm(["studio", "create", nb_id, "--type", "mind_map",
             "--focus", topic, "--confirm"], timeout=60)
    print(f"[scheduler] NLM visuals triggered (slides+infographic+mindmap)")


def nlm_poll_and_send(nb_id: str, artifact_type: str, topic: str,
                       token: str, max_wait: int = 600):
    """Background thread: poll until artifact ready, convert to portrait, upload to Slack."""
    import time
    import re as _re

    ext_map = {
        "slide_deck":  ".pdf",
        "infographic": ".png",
        "mind_map":    ".json",
    }
    ext     = ext_map.get(artifact_type, ".bin")
    outfile = f"/tmp/nlm-{nb_id[:8]}-{artifact_type}{ext}"
    waited  = 0

    while waited < max_wait:
        ok, out = run_nlm(["studio", "list", nb_id, "--json"], timeout=30)
        if ok:
            try:
                artifacts = json.loads(out)
                for a in artifacts:
                    if a.get("type") == artifact_type and a.get("status") == "completed":
                        dl_ok, _ = run_nlm(
                            ["download", artifact_type.replace("_", "-"),
                             nb_id, "--output", outfile, "--no-progress"],
                            timeout=120,
                        )
                        if dl_ok and Path(outfile).exists():
                            # Convert image artifacts to portrait
                            if ext == ".png":
                                portrait = outfile.replace(".png", "-portrait.png")
                                r = subprocess.run(
                                    ["python3", str(HOOKS_DIR / "vertical_converter.py"),
                                     "--input", outfile, "--output", portrait,
                                     "--title", topic.upper(), "--handle", "@oykamal"],
                                    capture_output=True, timeout=30
                                )
                                send_path = portrait if Path(portrait).exists() else outfile
                            else:
                                send_path = outfile

                            icon = {"slide_deck": "📊", "infographic": "🖼️", "mind_map": "🗺️"}.get(artifact_type, "✅")
                            slack_upload(token, send_path,
                                         title=f"{topic} — {artifact_type}",
                                         comment=f"{icon} *{topic}* — {artifact_type.replace('_',' ')} (visual-first)\n🤖 Kamil")
                        return
                    elif a.get("type") == artifact_type and a.get("status") == "failed":
                        print(f"[scheduler] NLM {artifact_type} failed for {nb_id[:8]}")
                        return
            except Exception:
                pass
        time.sleep(20)
        waited += 20

    print(f"[scheduler] NLM {artifact_type} timed out after {max_wait}s")

# ─── Image generation ─────────────────────────────────────────────────────────

def generate_image(topic: str, track: str, post_type: str) -> str | None:
    outfile = f"/tmp/kamil-content-{datetime.now().strftime('%Y%m%d-%H%M')}.png"
    palette = "fitness" if track == "fitness" else "tech"
    handle  = HANDLES.get(track, "@oykamal")
    gen     = str(HOOKS_DIR / "image_generator.py")

    if post_type == "tip":
        cmd = ["python3", gen, "--type", "tip",
               "--tip", topic.upper(), "--context", f"#{track}",
               "--handle", handle, "--palette", palette, "--output", outfile]
    elif post_type == "qa":
        cmd = ["python3", gen, "--type", "tip",
               "--tip", topic.upper(), "--context", f"#{track} #learn",
               "--handle", handle, "--palette", palette, "--output", outfile]
    else:
        # Default: info format with topic as title
        cmd = ["python3", gen, "--type", "tip",
               "--tip", topic.upper()[:40], "--context", f"#{track}",
               "--handle", handle, "--palette", palette, "--output", outfile]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and Path(outfile).exists():
            print(f"[scheduler] Image: {outfile}")
            return outfile
        print(f"[scheduler] Image gen failed: {r.stderr[:80]}")
        return None
    except Exception as e:
        print(f"[scheduler] Image error: {e}")
        return None

# ─── Caption generation ───────────────────────────────────────────────────────

def generate_caption(topic: str, track: str, score: int, reason: str) -> str:
    """Claude writes a visual-first caption with live hashtag research."""
    prompt = (
        f"Write a social media caption for a {track} post about: {topic}\n"
        f"Engagement score: {score}/100. Reason: {reason}\n\n"
        f"Rules:\n"
        f"- Under 150 words\n"
        f"- First line = scroll-stopping hook (no emoji at start)\n"
        f"- 3-4 bullet points — each is a visual cue or quick insight\n"
        f"- Include 'Save this' or 'Swipe to see' CTA (audience is visual learners)\n"
        f"- End with a question to drive comments\n"
        f"- 4 hashtags — research what's trending in {track} right now\n"
        f"- Sound like a practitioner, not a marketer\n"
        f"Return ONLY the caption text, nothing else."
    )
    try:
        r = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt],
            capture_output=True, text=True, timeout=90
        )
        caption = r.stdout.strip()
        if caption and len(caption) > 30:
            return caption
    except Exception as e:
        print(f"[scheduler] Caption error: {e}")

    tags = "#calisthenics #fitness #workout #health" if track == "fitness" else "#coding #AI #developer #tech"
    return f"{topic}\n\nSave this for later.\n\n{tags}"

# ─── Vlog script generation ───────────────────────────────────────────────────

def generate_vlog_script(topic: str, score: int, reason: str) -> str:
    """Claude writes a Casey Neistat-style vlog script."""
    prompt = (
        f"Write a Casey Neistat-style vlog script for a daily Islamabad life video about: {topic}\n"
        f"Trending signal: {reason}\n\n"
        f"Format exactly like this:\n"
        f"🎬 VLOG TOPIC: {topic} — {score}/100\n"
        f"WHY TODAY: [what's trending/timely about this]\n\n"
        f"HOOK (first 3 sec on camera):\n"
        f'\"[exact line to open with — punchy, visual, no intro]\"\n\n'
        f"SCENES:\n"
        f"1. [specific Islamabad location] — [what to film, how long, camera angle]\n"
        f"2. [location] — [action]\n"
        f"3. [location] — [action]\n"
        f"4. [location] — [action]\n"
        f"5. [location] — [action]\n\n"
        f"B-ROLL: [3 specific shots to grab while moving around]\n"
        f"TRENDING AUDIO: [specific song name or sound that fits]\n"
        f'CTA: \"[exact closing line — drives follows/comments]\"\n\n'
        f"HASHTAGS: [10 tags for Pakistan/Islamabad/travel/vlog]\n"
        f"CAPTION: [ready-to-paste caption for YouTube/TikTok/Reels]\n\n"
        f"Be specific about Islamabad locations (F-7, F-6, Blue Area, Margalla Hills, etc).\n"
        f"Return ONLY the script, nothing else."
    )
    try:
        r = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt],
            capture_output=True, text=True, timeout=90
        )
        script = r.stdout.strip()
        if script and len(script) > 100:
            return script
    except Exception as e:
        print(f"[scheduler] Vlog script error: {e}")

    return (
        f"🎬 VLOG TOPIC: {topic} — {score}/100\n"
        f"WHY TODAY: {reason}\n\n"
        f"Script generation failed — write this one manually.\n"
        f"Topic: {topic}"
    )

# ─── LinkedIn posting ─────────────────────────────────────────────────────────

def post_linkedin(caption: str, image_path: str | None) -> str:
    try:
        from linkedin_poster import post_to_linkedin
        return post_to_linkedin(caption, image_path)
    except Exception as e:
        return f"❌ LinkedIn error: {e}"

# ─── Track runners ────────────────────────────────────────────────────────────

def run_fitness_or_tech(track: str, token: str):
    """Full pipeline for fitness or tech track."""
    print(f"[scheduler] === {track.upper()} track ===")

    # 1. Trend scan → insert into Notion
    run_trend_scan(track, token)

    # 2. Pick topic
    result = pick_topic(track)
    if not result:
        slack_dm(token,
            f"📅 *{track} content* — no Pending topics in Notion.\n"
            f"Add topics to Content Calendar with Status=Pending, Track={track}\n🤖 Kamil")
        return

    page_id, topic, post_type, score, reason = result
    print(f"[scheduler] Topic: {topic} ({score}/100)")

    slack_dm(token,
        f"🚀 *{track} pipeline started* — *{topic}*\n"
        f"Score: {score}/100 | {reason}\nResearching + generating visuals...\n🤖 Kamil")

    # 3. NLM
    nb_id = nlm_create_notebook(topic)
    if nb_id:
        nlm_research(nb_id, topic)
        nlm_trigger_visuals(nb_id, topic)
        # Async poll for each artifact — posts to Slack when ready
        for artifact in ["slide_deck", "infographic", "mind_map"]:
            threading.Thread(
                target=nlm_poll_and_send,
                args=(nb_id, artifact, topic, token),
                daemon=True,
            ).start()

    # 4. Branded image
    image_path = generate_image(topic, track, post_type)

    # 5. Caption
    caption = generate_caption(topic, track, score, reason)

    # 6. LinkedIn (tech only)
    li_result = ""
    if track == "tech":
        li_result = post_linkedin(caption, image_path)
        print(f"[scheduler] LinkedIn: {li_result}")

    # 7. Notion mark done
    notion_update_page(page_id, {
        "Status":      {"select": {"name": "Done"}},
        "PostedDate":  {"date": {"start": date.today().isoformat()}},
        "NLMNotebookID": {"rich_text": [{"text": {"content": nb_id or ""}}]},
    })

    # 8. Slack DM summary
    li_line  = f"\n✅ Auto-posted to LinkedIn: {li_result}" if track == "tech" else ""
    nb_line  = f"\n📓 NLM `{nb_id[:8]}...` — slides + infographic + mindmap delivering to Slack shortly" if nb_id else ""
    img_note = f"\n🖼️ Branded image attached" if image_path else ""

    slack_dm(token,
        f"📊 *{track.upper()} content ready — {topic}*\n"
        f"Score: {score}/100 — {reason}\n"
        f"{li_line}{nb_line}{img_note}\n\n"
        f"*Caption (paste this):*\n{caption}\n\n"
        f"📱 Post to Instagram + TikTok (images coming above)\n🤖 Kamil")

    if image_path:
        slack_upload(token, image_path,
                     title=f"{topic} — branded",
                     comment=f"🎨 Branded image for *{topic}*")

    klog("content_posted", component="content-scheduler",
         topic=topic, track=track, score=score,
         linkedin=bool(li_result), nlm=bool(nb_id))


def run_vlog(token: str):
    """Vlog track — trend scan + script generation."""
    print(f"[scheduler] === VLOG track ===")

    run_trend_scan("vlog", token)

    result = pick_topic("vlog")
    if not result:
        slack_dm(token,
            "📅 *Vlog* — no Pending topics in Notion.\n"
            "Add vlog topics with Track=vlog, Status=Pending\n🤖 Kamil")
        return

    page_id, topic, _, score, reason = result

    script = generate_vlog_script(topic, score, reason)

    notion_update_page(page_id, {
        "Status":     {"select": {"name": "Done"}},
        "PostedDate": {"date": {"start": date.today().isoformat()}},
    })

    slack_dm(token,
        f"🎬 *Vlog script ready — {topic}*\n"
        f"Score: {score}/100 — {reason}\n\n"
        f"{script}\n\n"
        f"📱 Film this today → post to YouTube/TikTok/Reels/Shorts\n🤖 Kamil")

    klog("vlog_script", component="content-scheduler",
         topic=topic, score=score)

# ─── Main ─────────────────────────────────────────────────────────────────────

def run():
    token = load_slack_token()
    print(f"[scheduler] Starting — {datetime.now().isoformat()}")

    if NOTION_CONTENT_DB == "PASTE_DB_ID_HERE":
        slack_dm(token,
            "⚠️ *Content scheduler* — Notion DB ID not set.\n"
            "Run Task 1 to create the DB, then set NOTION_CONTENT_DB in content-scheduler.py\n🤖 Kamil")
        return

    ft_track = todays_ft_track()
    print(f"[scheduler] Today's ft track: {ft_track}")

    # Run fitness/tech + vlog in parallel
    ft_thread   = threading.Thread(target=run_fitness_or_tech, args=(ft_track, token))
    vlog_thread = threading.Thread(target=run_vlog, args=(token,))

    ft_thread.start()
    vlog_thread.start()

    ft_thread.join()
    vlog_thread.join()

    print(f"[scheduler] Done — {datetime.now().isoformat()}")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        klog_error("content_scheduler", e)
        token = load_slack_token()
        slack_dm(token,
            f"⚠️ *Content scheduler crashed*: {e}\n"
            f"Check: `tail -50 /tmp/kamil-content.log`\n🤖 Kamil")
        raise
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/content-scheduler.py').read()); print('syntax ok')"
# Expected: syntax ok
```

- [ ] **Step 3: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/hooks/content-scheduler.py
git commit -m "feat: content-scheduler v2 — 3 tracks, trend scan, visual-first NLM, vlog scripts"
```

---

### Task 4: Wire NOTION_CONTENT_DB ID into scheduler

**Files:**
- Modify: `.claude/hooks/content-scheduler.py` line with `NOTION_CONTENT_DB`

- [ ] **Step 1: Get the DB ID from Task 1 output**

If you didn't save it, run:
```bash
claude --dangerously-skip-permissions --print -p "
Search Notion for a database called 'Content Calendar' that is a child of page 364d8747b3b1813d8ac8c248800f0a4d.
Return only the database ID on a single line prefixed with 'DB_ID:'
" 2>&1 | grep "DB_ID:"
```

- [ ] **Step 2: Replace the placeholder in content-scheduler.py**

```bash
# Replace PASTE_DB_ID_HERE with the real ID
sed -i 's/NOTION_CONTENT_DB  = "PASTE_DB_ID_HERE"/NOTION_CONTENT_DB  = "REAL_DB_ID_HERE"/' \
  /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/content-scheduler.py
```

Also update `vault/notion-map.md` Content Calendar DB ID row with the real ID.

- [ ] **Step 3: Verify**

```bash
grep "NOTION_CONTENT_DB" /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/content-scheduler.py
# Expected: NOTION_CONTENT_DB  = "32-char-hex-or-uuid"  (NOT "PASTE_DB_ID_HERE")
```

- [ ] **Step 4: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/hooks/content-scheduler.py vault/notion-map.md
git commit -m "config: set Notion Content Calendar DB ID in content-scheduler"
```

---

### Task 5: Smoke test the full pipeline

- [ ] **Step 1: Test trend scanner standalone**

```bash
python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/trend-scanner.py fitness
# Expected: at least 1 scored topic printed
```

- [ ] **Step 2: Test vlog script generation (dry run)**

```bash
python3 -c "
import sys
sys.path.insert(0, '/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks')
from content_scheduler import generate_vlog_script
print(generate_vlog_script('Morning Routine Islamabad', 65, 'pre-planned queue'))
"
# Expected: full Casey Neistat-style script with HOOK, SCENES, B-ROLL, CTA
```

- [ ] **Step 3: Test caption generation**

```bash
python3 -c "
import sys
sys.path.insert(0, '/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks')
from content_scheduler import generate_caption
print(generate_caption('Pull-up Progression', 'fitness', 82, 'trending on r/bodyweightfitness'))
"
# Expected: caption with hook, bullets, CTA, hashtags, under 150 words
```

- [ ] **Step 4: Dry-run the full scheduler (no Slack, no LinkedIn)**

```bash
python3 -c "
import sys
sys.path.insert(0, '/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks')
# Patch slack_dm to print instead of send
import content_scheduler as cs
cs.slack_dm = lambda t, m: print('[DRY RUN SLACK]', m[:100])
cs.slack_upload = lambda *a, **k: print('[DRY RUN UPLOAD]', a[2] if len(a)>2 else '')
cs.post_linkedin = lambda *a: '[DRY RUN LINKEDIN]'
cs.run()
" 2>&1 | head -60
# Expected: pipeline runs, prints [DRY RUN SLACK/UPLOAD/LINKEDIN] lines, no crash
```

- [ ] **Step 5: Final commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add -A
git commit -m "feat: smart content scheduler v2 complete — trend scan + 3 tracks + visual NLM"
```
