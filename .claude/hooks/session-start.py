#!/usr/bin/env python3
"""
session-start hook: Runs at every Claude Code session start.

Outputs a system message that:
1. Establishes Varys's identity
2. Surfaces any unsynced Slack inbox items from /tmp/varys-slack-inbox.json
3. Tells Claude to use Notion MCP tools to fetch live DB state (PRs, Work Log, Harness)

Notion reads/writes are done by Claude via MCP — no API key needed here.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
import sys as _sys, time as _time
_sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
try:
    import varys_log as _k
except Exception:
    _k = None

INBOX_FILE = Path("/tmp/agent-slack-inbox.json")

# Notion DB page IDs — used by Claude's MCP fetch calls
from agent_config import cfg
DB_PAGE_SLACK_INBOX = cfg("NOTION_INBOX_DB_ID",    "6d14f1b6b8cd4ff68fd40efdfc3f304e")
DB_PAGE_MY_PRS      = cfg("NOTION_MY_PRS_DB_ID",   "18017a67136a4561ada9818c239b8f33")
DB_PAGE_WORK_LOG    = cfg("NOTION_WORK_LOG_DB_ID",  "0b71db855f914d18ac6d97c0f77fc21e")
DB_PAGE_HARNESS     = cfg("NOTION_HARNESS_DB_ID",   "de10157da3e34ef58a74ea240f31fe98")


def load_slack_inbox() -> list:
    if not INBOX_FILE.exists():
        return []
    try:
        items = json.loads(INBOX_FILE.read_text())
        # Return only unsynced items, newest first
        unsynced = [i for i in items if not i.get("notion_synced")]
        return unsynced[-20:]  # cap at 20 for briefing
    except Exception:
        return []


def _notion_query(token: str, db_id: str, body: dict) -> list:
    """Shared Notion DB query helper. Returns raw results list."""
    import urllib.request as _ur
    data = json.dumps(body).encode()
    req = _ur.Request(
        f"https://api.notion.com/v1/databases/{db_id}/query",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        },
    )
    with _ur.urlopen(req, timeout=8) as r:
        return json.loads(r.read()).get("results", [])


def _get_notion_token() -> str:
    notion_cfg = Path.home() / ".claude" / "hooks" / ".notion"
    if notion_cfg.exists():
        for line in notion_cfg.read_text().splitlines():
            if line.startswith("NOTION_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def _fetch_work_log() -> list[dict]:
    """Fetch last 2 Work Log entries."""
    token = _get_notion_token()
    if not token:
        return []
    try:
        pages = _notion_query(token, DB_PAGE_WORK_LOG, {
            "sorts": [{"timestamp": "created_time", "direction": "descending"}],
            "page_size": 2,
        })
        results = []
        for page in pages:
            props = page["properties"]
            def txt(p): return (props.get(p, {}).get("rich_text") or [{}])[0].get("plain_text", "") if props.get(p) else ""
            def ttl(p): return (props.get(p, {}).get("title") or [{}])[0].get("plain_text", "") if props.get(p) else ""
            def dt(p):  return (props.get(p, {}).get("date") or {}).get("start", "")
            results.append({
                "session": ttl("Session"),
                "date": dt("Date"),
                "done": txt("What Was Done"),
                "prs": txt("PRs Worked On"),
                "next": txt("Next Steps"),
            })
        return results
    except Exception:
        return []


def _fetch_open_prs() -> list[dict]:
    """Fetch open/in-review PRs."""
    token = _get_notion_token()
    if not token:
        return []
    try:
        pages = _notion_query(token, DB_PAGE_MY_PRS, {
            "filter": {"or": [
                {"property": "Status", "select": {"equals": "Open"}},
                {"property": "Status", "select": {"equals": "Needs Review"}},
                {"property": "Status", "select": {"equals": "CI Failing"}},
                {"property": "Status", "select": {"equals": "Draft"}},
            ]},
            "page_size": 10,
        })
        results = []
        for page in pages:
            props = page["properties"]
            def ttl(p): return (props.get(p, {}).get("title") or [{}])[0].get("plain_text", "") if props.get(p) else ""
            def sel(p): return (props.get(p, {}).get("select") or {}).get("name", "")
            def num(p): return props.get(p, {}).get("number")
            def url(p): return props.get(p, {}).get("url", "")
            results.append({
                "title": ttl("PR Title"),
                "status": sel("Status"),
                "ci": sel("CI Status"),
                "number": num("PR Number"),
                "url": url("userDefined:URL"),
            })
        return results
    except Exception:
        return []


def _fetch_auto_tickets() -> list[dict]:
    """Fetch pending [Auto] Harness tickets. Returns list of {title, phase} dicts."""
    token = _get_notion_token()
    if not token:
        return []
    try:
        pages = _notion_query(token, DB_PAGE_HARNESS, {
            "filter": {
                "and": [
                    {"property": "Feature", "title":  {"contains": "[Auto]"}},
                    {"property": "Phase",   "select": {"does_not_equal": "Done"}},
                ]
            },
            "page_size": 10,
        })
        tickets = []
        for page in pages:
            title = page["properties"].get("Feature", {}).get("title", [])
            phase = (page["properties"].get("Phase", {}).get("select") or {})
            tickets.append({
                "title": title[0]["plain_text"] if title else "?",
                "phase": phase.get("name", "Backlog"),
            })
        return tickets
    except Exception:
        return []


def build_system_message() -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    inbox = load_slack_inbox()

    lines = [
        "## YOU ARE {{AGENT_NAME}}",
        "You are {{AGENT_NAME}} — {{USER_NAME}}'s personal AI agent.",
        "You are NOT a general assistant. You do NOT invoke superpowers skills or feature-dev skills unless {{USER_NAME}} explicitly asks.",
        "When {{USER_NAME}} says '{{AGENT_NAME}}, work on [project] — [task]', follow the CLAUDE.md harness protocol exactly.",
        "Your memory is in MEMORY.md. Your harness is in CLAUDE.md.",
        "",
        f"## Session Start — {now}",
        "",
    ]

    # Surface unsynced Slack inbox items
    if inbox:
        lines.append(f"## 📬 Slack Inbox — {len(inbox)} unsynced items")
        lines.append("*(These came from slack-poller.py — write them to Notion Slack Inbox DB via MCP when ready)*")
        for item in inbox[:10]:
            status  = item.get("status", "")
            msg     = item.get("message", "")[:100]
            frm     = item.get("from", "")
            channel = item.get("channel", "")
            lines.append(f"- **[{status}]** {msg} ← {frm} ({channel})")
        if len(inbox) > 10:
            lines.append(f"- ... and {len(inbox) - 10} more")
        lines.append("")
    else:
        lines.append("## 📬 Slack Inbox — Nothing new since last session\n")

    # Active work state — written by poll-work-state.py cron every 30min
    work_state_file = Path("/tmp/varys-work-state.json")
    if work_state_file.exists():
        try:
            ws = json.loads(work_state_file.read_text())
            lines.append("## 🔨 Active Work State (live — updated every 30min)")
            updated = ws.get("updated_at", "")[:16].replace("T", " ")
            branch  = ws.get("active_branch", "")
            if branch:
                lines.append(f"**Branch:** `{branch}` (taleemabad-core) — as of {updated}")
            tickets = ws.get("harness_active", [])
            if tickets:
                lines.append("**Harness (In Progress / Blocked):**")
                for t in tickets:
                    pr   = f" → {t['pr']}" if t.get("pr") else ""
                    jira = f" [{t['jira']}]" if t.get("jira") else ""
                    lines.append(f"  - [{t['phase']}]{jira} {t['title']}{pr}")
                    if t.get("plan"):
                        lines.append(f"    _{t['plan']}_")
            prs = ws.get("open_prs", [])
            if prs:
                lines.append("**Open PRs:**")
                for pr in prs:
                    draft = " [DRAFT]" if pr.get("isDraft") else ""
                    lines.append(f"  - #{pr['number']}{draft} {pr['title']} ({pr.get('headRefName','')})")
            commits = ws.get("recent_commits", [])
            if commits:
                lines.append(f"**Recent commits (7d):** {len(commits)} commits")
                for c in commits[:5]:
                    lines.append(f"  - {c}")
                if len(commits) > 5:
                    lines.append(f"  - ... and {len(commits)-5} more")
            lines.append("")
        except Exception:
            pass

    # Pre-fetch live Notion context (reliable in --print mode; MCP instruction alone is not)
    try:
        work_log = _fetch_work_log()
        open_prs = _fetch_open_prs()
        lines.append("## 📋 Live Notion Context (pre-fetched)")
        if work_log:
            lines.append("### Recent Work Log")
            for entry in work_log:
                lines.append(f"**{entry['date'] or 'recent'} — {entry['session']}**")
                if entry["done"]:  lines.append(f"  Done: {entry['done'][:200]}")
                if entry["prs"]:   lines.append(f"  PRs: {entry['prs'][:150]}")
                if entry["next"]:  lines.append(f"  Next: {entry['next'][:150]}")
        else:
            lines.append("  Work Log: no recent entries found")
        if open_prs:
            lines.append("### Open PRs")
            for pr in open_prs:
                num = f"#{pr['number']}" if pr["number"] else ""
                ci  = f" CI:{pr['ci']}" if pr["ci"] and pr["ci"] != "N/A" else ""
                url = f" {pr['url']}" if pr["url"] else ""
                lines.append(f"  - {pr['status']} {num} {pr['title']}{ci}{url}")
        else:
            lines.append("  Open PRs: none")
        lines.append("")
    except Exception:
        pass  # live context is best-effort

    # Surface recent learnings from brain.db
    try:
        import sqlite3
        from pathlib import Path as _Path
        brain_db = _Path.home() / ".varys-harness" / "brain.db"
        if brain_db.exists():
            db = sqlite3.connect(str(brain_db))
            # Get learnings from last 7 days with their key insights
            recent = db.execute("""
                SELECT e.name, f.object_val, f.predicate, e.created_at
                FROM entities e
                JOIN facts f ON f.subject_id = e.id
                WHERE e.type = 'learning'
                  AND f.predicate IN ('one_line_summary', 'key_insight', 'lesson_learned')
                  AND e.created_at >= datetime('now', '-7 days')
                ORDER BY e.created_at DESC
                LIMIT 30
            """).fetchall()
            db.close()

            if recent:
                # Group by entity name
                grouped = {}
                for name, val, pred, ts in recent:
                    if name not in grouped:
                        grouped[name] = {"summary": "", "insights": [], "lessons": [], "ts": ts[:10]}
                    if pred == "one_line_summary":
                        grouped[name]["summary"] = val
                    elif pred == "key_insight" and len(grouped[name]["insights"]) < 2:
                        grouped[name]["insights"].append(val)
                    elif pred == "lesson_learned" and len(grouped[name]["lessons"]) < 1:
                        grouped[name]["lessons"].append(val)

                lines.append("## 🧠 Recent Learnings — What Varys Researched (last 7 days)")
                lines.append("*(Use these when advising on architecture, agents, or content — Varys already knows this)*")
                for name, data in list(grouped.items())[:5]:
                    lines.append(f"\n**{data['ts']} — {name}**")
                    if data["summary"]:
                        lines.append(f"  → {data['summary']}")
                    for ins in data["insights"]:
                        lines.append(f"  • {ins}")
                    for lesson in data["lessons"]:
                        lines.append(f"  ⚡ Lesson: {lesson}")
                lines.append("")
    except Exception:
        pass  # brain surface is best-effort, never block session start

    # Surface pending [Auto] tickets from Application Agent
    try:
        auto_tickets = _fetch_auto_tickets()
        if auto_tickets:
            lines.append("## 🔧 Pending Self-Improvement Tickets (from research)")
            lines.append("*(These were auto-created by Varys's Application Agent — derived from NLM research)*")
            for t in auto_tickets:
                lines.append(f"- [{t['phase']}] {t['title']}")
            lines.append("")
    except Exception:
        pass

    # Tell Claude what to fetch via MCP
    lines += [
        "## 🔌 Notion MCP — Fetch These Now",
        "Use `mcp__claude_ai_Notion__notion-fetch` to load live context:",
        f"- My PRs DB: `{DB_PAGE_MY_PRS}` — filter Status = Open/Needs Review/CI Failing",
        f"- Work Log DB: `{DB_PAGE_WORK_LOG}` — last 1 entry",
        f"- Harness DB: `{DB_PAGE_HARNESS}` — filter Phase != Done",
        f"- Slack Inbox DB: `{DB_PAGE_SLACK_INBOX}` — filter Status = Unread/Needs Action",
        "",
        "After fetching, greet Shoaib with: open PRs + last session summary + any inbox items needing action.",
        "If there are unsynced Slack items above, write them to Notion Slack Inbox DB via MCP.",
    ]

    return "\n".join(lines)


def main():
    msg = {"systemMessage": build_system_message()}
    print(json.dumps(msg))
    return 0


if __name__ == "__main__":
    _t0 = _time.time()
    try:
        rc = main()
        if _k: _k.klog_cron("session-start", status="ok", duration_ms=(_time.time()-_t0)*1000)
        sys.exit(rc)
    except Exception as _e:
        if _k: _k.klog_error("session-start-main", _e, component="session-start", severity="ERROR")
        raise
