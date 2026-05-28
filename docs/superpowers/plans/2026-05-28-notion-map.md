# Notion Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `vault/notion-map.md` — a complete, always-current reference of every Notion DB, page, and script relationship — auto-updated on session end (stop hook) and nightly cron.

**Architecture:** A single `notion-map-updater.py` script with two modes: `--mode session` appends a timestamped activity line to the existing MD; `--mode daily` full-regenerates the MD by scanning all hook scripts for DB IDs and merging with the known static map. Stop hook runs session mode; 2am cron runs daily mode.

**Tech Stack:** Python 3, pathlib, re, subprocess (git commit), existing `kamil_log.py`, existing stop hook chain in `.claude/settings.json`.

---

### Task 1: Write `vault/notion-map.md` — the static master map

**Files:**
- Create: `vault/notion-map.md`

- [ ] **Step 1: Create the file with the complete known Notion inventory**

Write `vault/notion-map.md` with this exact content:

```markdown
# Notion Map — Kamil's Brain

> Auto-updated: session end (stop hook) + 2am daily cron via `notion-map-updater.py`.
> To regenerate manually: `python3 .claude/hooks/notion-map-updater.py --mode daily`

Last full scan: <!-- LAST_SCAN -->

---

## Databases

| Name | DB ID | Purpose |
|---|---|---|
| My PRs | `18017a67136a4561ada9818c239b8f33` | Kamal's PRs, CI state, review status |
| Work Log | `0b71db855f914d18ac6d97c0f77fc21e` | Daily session summaries |
| Slack Inbox | `6d14f1b6b8cd4ff68fd40efdfc3f304e` | Classified Slack messages needing action |
| Harness | `de10157da3e34ef58a74ea240f31fe98` | Kamil's task backlog + self-evolution |
| Job Tracker | `0d69c6ff83d844c794c2d341c4ded8d7` | Freelance job postings + applications |
| People Intelligence | `c976d58ea4e34b0585f245529cdc4528` | Team profiles, mood, communication style |
| Eval Log | `94017dd157b44f3ca96423ad2ad989da` | Conversation quality scores (Good/Partial/Wrong) |
| Health Log | `27e287b7a3d146c6b5e8eb0d862d746f` | Operational health, errors, self-heals |
| Content Calendar | `36bd8747b3b1810da374e059835f00cd` | Social media topics (Pending/In Progress/Done) |

---

## Pages (non-database)

| Name | Page ID | Purpose |
|---|---|---|
| Kamal's Agent Brain | `364d8747b3b1813d8ac8c248800f0a4d` | Parent container for all Kamil Notion content |
| Kamil Self-Questions | `365d8747b3b181b281b8ef5820e15881` | Personality-building questions, read every 30min |
| Master Plan / Freelance | `369d8747b3b181d59775dcb4297d7dbd` | Freelance outreach strategy + portfolio updates |

---

## Data Source IDs (for MCP create-pages)

| DB | Data Source ID |
|---|---|
| Slack Inbox | `8749992f-6140-4e72-8b48-7362533cb792` |
| Eval Log | `2e46d119-159e-4634-9195-a7343e590dbe` |
| People Intelligence | `c00daef1-c072-4263-b23d-e1b5e2ba596c` |
| Harness | `a173fd5a-b953-4a53-a020-4545db41ccb5` |

---

## Script → Database Matrix

| Script | Reads | Writes |
|---|---|---|
| `session-start.py` | My PRs, Work Log, Harness, Slack Inbox | — |
| `stop-notion.py` | — | Work Log |
| `stop.py` | — | git commit, STANDUP.md |
| `kamil-task-interceptor.py` | Harness | Harness (create) |
| `kamil-slack-listener.py` | My PRs, Harness, Slack Inbox, Job Tracker, People | Slack Inbox, Work Log, Job Tracker |
| `kamil_eval.py` | Eval Log | Eval Log (create) |
| `kamil_eval_tracker.py` | Health Log | Health Log (update) |
| `kamil_health.py` | — | Health Log (create) |
| `kamil_people.py` | People Intelligence | People Intelligence (create/update) |
| `job-finder.py` | Job Tracker | Job Tracker (create) |
| `auto-apply.py` | Job Tracker | Job Tracker (update) |
| `portfolio-updater.py` | Job Tracker, Brain Page | Plan Page (update) |
| `openoutreach-monitor.py` | Job Tracker | Job Tracker (create) |
| `content-scheduler.py` | Content Calendar | Content Calendar (update) |
| `slack-poller.py` | Self-Questions Page, Slack Inbox | Work Log, Slack Inbox |
| `inbox-processor.py` | Brain Page, Work Log, Slack Inbox | Work Log |
| `notion-map-updater.py` | — | vault/notion-map.md (this file) |

---

## Auth / Token Locations

| Token | File | Key |
|---|---|---|
| Notion API Key | `~/.claude/hooks/.notion` | `NOTION_API_KEY=` |
| Slack Bot Token | `~/.claude/hooks/.slack` | `BOT_TOKEN=` |
| LinkedIn Access Token | `~/.claude/hooks/.linkedin` | `LINKEDIN_ACCESS_TOKEN=` (expires 2 months) |
| Axiom Token | `~/.claude/hooks/.axiom` | `AXIOM_TOKEN=` |

---

## Troubleshooting

**Notion writes failing?**
→ Check `~/.claude/hooks/.notion` has a valid `NOTION_API_KEY`
→ Token from: Notion Settings → Integrations → Internal Integration

**Content not posting?**
→ LinkedIn token expires every 2 months — re-run OAuth
→ Check `tail -50 /tmp/kamil-content.log`
→ Ensure Notion Content Calendar has pages with `Status=Pending`

**Slack listener not responding?**
→ `tail -20 /tmp/kamil-slack-listener.log`
→ Self-healer auto-restarts it every 10min via cron

**Job finder not running?**
→ `tail -20 /tmp/kamil-jobs.log`
→ Cron: `*/30 * * * *` — check `crontab -l`

---

## Activity Log
<!-- ACTIVITY_LOG_START -->
<!-- ACTIVITY_LOG_END -->
```

- [ ] **Step 2: Verify file was written**

```bash
wc -l /home/oye/Documents/free_work/personal-agent-v2/vault/notion-map.md
# Expected: ~90+ lines
```

- [ ] **Step 3: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add vault/notion-map.md
git commit -m "feat: add vault/notion-map.md — complete Notion DB/page inventory"
```

---

### Task 2: Write `notion-map-updater.py`

**Files:**
- Create: `.claude/hooks/notion-map-updater.py`

- [ ] **Step 1: Write the script**

Create `.claude/hooks/notion-map-updater.py`:

```python
#!/usr/bin/env python3
"""
notion-map-updater.py — Keeps vault/notion-map.md current.

Two modes:
  --mode session  (stop hook): appends timestamped 1-line activity entry
  --mode daily    (2am cron):  full regenerate — scans all hooks for DB IDs,
                               updates Last full scan timestamp, rewrites file

Usage:
  python3 notion-map-updater.py --mode session --summary "posted content, updated harness"
  python3 notion-map-updater.py --mode daily
"""

import argparse
import re
import subprocess
from datetime import datetime
from pathlib import Path

KAMIL_DIR  = Path(__file__).parent.parent.parent
MAP_FILE   = KAMIL_DIR / "vault" / "notion-map.md"
HOOKS_DIR  = Path(__file__).parent

# Known DB IDs with names — source of truth
KNOWN_DBS = {
    "18017a67136a4561ada9818c239b8f33": "My PRs",
    "0b71db855f914d18ac6d97c0f77fc21e": "Work Log",
    "6d14f1b6b8cd4ff68fd40efdfc3f304e": "Slack Inbox",
    "de10157da3e34ef58a74ea240f31fe98": "Harness",
    "0d69c6ff83d844c794c2d341c4ded8d7": "Job Tracker",
    "c976d58ea4e34b0585f245529cdc4528": "People Intelligence",
    "94017dd157b44f3ca96423ad2ad989da": "Eval Log",
    "27e287b7a3d146c6b5e8eb0d862d746f": "Health Log",
    "36bd8747b3b1810da374e059835f00cd": "Content Calendar",
    # UUID variants (with dashes) also recognized
    "0d69c6ff-83d8-44c7-94c2-d341c4ded8d7": "Job Tracker",
    "27e287b7-a3d1-46c6-b5e8-eb0d862d746f": "Health Log",
    "36bd8747b3b181-0da374e059835f00cd": "Content Calendar",
}

# DB ID regex — matches both 32-char hex and UUID formats
DB_ID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'  # UUID
    r'|[0-9a-f]{32}',  # 32-char hex
    re.IGNORECASE,
)

ACTIVITY_START = "<!-- ACTIVITY_LOG_START -->"
ACTIVITY_END   = "<!-- ACTIVITY_LOG_END -->"
LAST_SCAN_TAG  = "<!-- LAST_SCAN -->"


def session_mode(summary: str):
    """Append a timestamped line to the Activity Log section."""
    if not MAP_FILE.exists():
        print(f"[notion-map] {MAP_FILE} not found — skipping session update")
        return

    content = MAP_FILE.read_text()
    ts      = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry   = f"- {ts} — {summary}"

    if ACTIVITY_START in content and ACTIVITY_END in content:
        # Insert before the end marker
        content = content.replace(
            ACTIVITY_END,
            f"{entry}\n{ACTIVITY_END}"
        )
    else:
        # Append at end if markers missing
        content += f"\n{entry}\n"

    MAP_FILE.write_text(content)
    print(f"[notion-map] Session entry added: {entry}")


def daily_mode():
    """
    Full regenerate:
    1. Scan all .py and .sh in hooks dir for Notion DB IDs
    2. Find any new IDs not in KNOWN_DBS
    3. Update Last full scan timestamp in the map file
    4. Append a daily scan summary to Activity Log
    5. Git commit the updated file
    """
    if not MAP_FILE.exists():
        print(f"[notion-map] {MAP_FILE} not found — cannot regenerate")
        return

    content = MAP_FILE.read_text()

    # Scan hooks for all DB IDs
    found_ids: dict[str, list[str]] = {}  # id -> [script names]
    for ext in ("*.py", "*.sh"):
        for script in HOOKS_DIR.glob(ext):
            text = script.read_text(errors="ignore")
            for m in DB_ID_RE.finditer(text):
                db_id = m.group(0).replace("-", "").lower()
                if db_id not in found_ids:
                    found_ids[db_id] = []
                found_ids[db_id].append(script.name)

    # Also scan root *.sh
    for script in KAMIL_DIR.glob("*.sh"):
        text = script.read_text(errors="ignore")
        for m in DB_ID_RE.finditer(text):
            db_id = m.group(0).replace("-", "").lower()
            if db_id not in found_ids:
                found_ids[db_id] = []
            found_ids[db_id].append(script.name)

    # Find unknown IDs
    known_normalized = {k.replace("-", "").lower() for k in KNOWN_DBS}
    unknown = {k: v for k, v in found_ids.items() if k not in known_normalized}

    # Build scan summary
    ts      = datetime.now().strftime("%Y-%m-%d %H:%M")
    summary_lines = [f"Daily scan: {len(found_ids)} DB IDs found across {len(HOOKS_DIR.glob('*.py'))} scripts"]
    if unknown:
        for uid, scripts in unknown.items():
            summary_lines.append(f"  ⚠️ Unknown DB ID `{uid}` in: {', '.join(set(scripts))}")
    else:
        summary_lines.append("  All IDs accounted for ✅")

    summary = " | ".join(summary_lines)

    # Update Last full scan timestamp
    content = re.sub(
        r"Last full scan:.*",
        f"Last full scan: {ts}",
        content,
    )

    # Append activity entry
    entry = f"- {ts} — {summary}"
    if ACTIVITY_START in content and ACTIVITY_END in content:
        content = content.replace(ACTIVITY_END, f"{entry}\n{ACTIVITY_END}")
    else:
        content += f"\n{entry}\n"

    MAP_FILE.write_text(content)
    print(f"[notion-map] Daily scan complete. {summary}")

    # Git commit
    try:
        subprocess.run(["git", "add", str(MAP_FILE)], cwd=str(KAMIL_DIR), check=False)
        subprocess.run(
            ["git", "commit", "-m", f"chore: notion-map daily scan {ts}"],
            cwd=str(KAMIL_DIR), capture_output=True, check=False
        )
        print("[notion-map] Committed updated map")
    except Exception as e:
        print(f"[notion-map] Git commit failed: {e}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["session", "daily"], required=True)
    p.add_argument("--summary", default="session ended", help="Session mode: 1-line summary")
    args = p.parse_args()

    if args.mode == "session":
        session_mode(args.summary)
    else:
        daily_mode()
```

- [ ] **Step 2: Make executable and smoke test**

```bash
chmod +x /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/notion-map-updater.py
python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/notion-map-updater.py --mode session --summary "smoke test"
# Expected: [notion-map] Session entry added: - 2026-... — smoke test
grep "smoke test" /home/oye/Documents/free_work/personal-agent-v2/vault/notion-map.md
# Expected: line with "smoke test"
```

- [ ] **Step 3: Run daily mode to verify scan**

```bash
python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/notion-map-updater.py --mode daily
# Expected: [notion-map] Daily scan complete. Daily scan: N DB IDs found...
tail -20 /home/oye/Documents/free_work/personal-agent-v2/vault/notion-map.md
# Expected: activity lines + "Last full scan: 2026-..."
```

- [ ] **Step 4: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/hooks/notion-map-updater.py
git commit -m "feat: add notion-map-updater.py (session + daily modes)"
```

---

### Task 3: Wire session mode into stop hook

**Files:**
- Modify: `.claude/hooks/stop.py` (append call at end)

- [ ] **Step 1: Add notion-map-updater call to stop.py**

Open `.claude/hooks/stop.py`. At the very end of the `main()` function (after the git commit block), add:

```python
    # Update notion-map.md with session summary
    try:
        today_log = workspace_root / "vault" / "logs" / f"{datetime.now().strftime('%Y-%m-%d')}.md"
        if today_log.exists():
            # Extract last 3 log lines as summary
            lines = [l.strip() for l in today_log.read_text().splitlines() if l.strip().startswith("-")]
            summary = " | ".join(lines[-3:]) if lines else "session ended"
        else:
            summary = "session ended"
        subprocess.run(
            ["python3", str(workspace_root / ".claude" / "hooks" / "notion-map-updater.py"),
             "--mode", "session", "--summary", summary[:200]],
            cwd=str(workspace_root), capture_output=True, timeout=10
        )
    except Exception as e:
        print(f"[stop] notion-map update failed (non-fatal): {e}", file=sys.stderr)
```

- [ ] **Step 2: Verify stop.py still runs cleanly**

```bash
python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/stop.py
# Expected: no crash, notion-map.md gets a new activity line
tail -5 /home/oye/Documents/free_work/personal-agent-v2/vault/notion-map.md
```

- [ ] **Step 3: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/hooks/stop.py
git commit -m "feat: wire notion-map session update into stop hook"
```

---

### Task 4: Wire daily mode into 2am cron

**Files:**
- Modify: crontab

- [ ] **Step 1: Add daily cron entry**

```bash
crontab -l > /tmp/current_cron.txt
echo "# Kamil — Notion map daily scan at 2am" >> /tmp/current_cron.txt
echo "30 2 * * * python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/notion-map-updater.py --mode daily >> /tmp/kamil-notion-map.log 2>&1" >> /tmp/current_cron.txt
crontab /tmp/current_cron.txt
```

- [ ] **Step 2: Verify cron was added**

```bash
crontab -l | grep notion-map
# Expected: 30 2 * * * python3 .../notion-map-updater.py --mode daily ...
```

- [ ] **Step 3: Wire into self-healer log monitoring**

Open `.claude/hooks/kamil-self-healer.py`. In the `SERVICES` list, add:

```python
    {
        "name": "notion-map-updater",
        "script": str(HOOKS_DIR / "notion-map-updater.py"),
        "log": "/tmp/kamil-notion-map.log",
        "pid_file": None,
        "start_cmd": None,  # cron-driven
        "check_process": None,
    },
```

- [ ] **Step 4: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/hooks/kamil-self-healer.py
git commit -m "feat: wire notion-map daily cron + self-healer monitoring"
```

---

### Task 5: Save memory so this is never forgotten

**Files:**
- Create: `/home/oye/.claude/projects/-home-oye-Documents-free-work-personal-agent-v2/memory/project_notion_map.md`
- Modify: `MEMORY.md` index

- [ ] **Step 1: Write memory file**

```markdown
---
name: project-notion-map
description: vault/notion-map.md is the single source of truth for all Notion DB IDs, page IDs, script relationships — auto-updated on session end and 2am cron
metadata:
  type: project
---

# Notion Map

vault/notion-map.md — complete Notion inventory, always current.

## Where to look

- Full map: `vault/notion-map.md`
- Updater script: `.claude/hooks/notion-map-updater.py`
- Session update: wired into `.claude/hooks/stop.py` (runs on every session end)
- Daily update: cron at 2:30am via `notion-map-updater.py --mode daily`
- Log: `/tmp/kamil-notion-map.log`

## DB IDs quick ref

| DB | ID |
|---|---|
| My PRs | 18017a67136a4561ada9818c239b8f33 |
| Work Log | 0b71db855f914d18ac6d97c0f77fc21e |
| Slack Inbox | 6d14f1b6b8cd4ff68fd40efdfc3f304e |
| Harness | de10157da3e34ef58a74ea240f31fe98 |
| Job Tracker | 0d69c6ff83d844c794c2d341c4ded8d7 |
| People Intelligence | c976d58ea4e34b0585f245529cdc4528 |
| Eval Log | 94017dd157b44f3ca96423ad2ad989da |
| Health Log | 27e287b7a3d146c6b5e8eb0d862d746f |
| Content Calendar | 36bd8747b3b1810da374e059835f00cd |

**Why:** Built because Kamil kept forgetting which DB ID was which and what script used what.
**How to apply:** Any time someone asks about Notion structure, DB IDs, or "where did you put X" — read vault/notion-map.md first.
```

- [ ] **Step 2: Update MEMORY.md index**

Add this line to `/home/oye/.claude/projects/-home-oye-Documents-free-work-personal-agent-v2/memory/MEMORY.md`:

```
- [Notion Map](project_notion_map.md) — vault/notion-map.md has all DB IDs, page IDs, script matrix; auto-updated session end + 2am cron
```

- [ ] **Step 3: Final commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add -A
git commit -m "feat: notion-map complete — map + updater + hooks + memory"
```
