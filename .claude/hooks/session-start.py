#!/usr/bin/env python3
"""
session-start hook: Runs at every Claude Code session start.

Outputs a system message that:
1. Establishes Kamil's identity
2. Surfaces any unsynced Slack inbox items from /tmp/kamil-slack-inbox.json
3. Tells Claude to use Notion MCP tools to fetch live DB state (PRs, Work Log, Harness)

Notion reads/writes are done by Claude via MCP — no API key needed here.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
import sys as _sys, time as _time
_sys.path.insert(0, "/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks")
try:
    import kamil_log as _k
except Exception:
    _k = None

INBOX_FILE = Path("/tmp/kamil-slack-inbox.json")

# Notion DB page IDs — used by Claude's MCP fetch calls
DB_PAGE_SLACK_INBOX = "6d14f1b6b8cd4ff68fd40efdfc3f304e"
DB_PAGE_MY_PRS      = "18017a67136a4561ada9818c239b8f33"
DB_PAGE_WORK_LOG    = "0b71db855f914d18ac6d97c0f77fc21e"
DB_PAGE_HARNESS     = "de10157da3e34ef58a74ea240f31fe98"


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


def build_system_message() -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    inbox = load_slack_inbox()

    lines = [
        "## YOU ARE KAMIL",
        "You are Kamil — Muhammad Kamal's personal AI agent at Taleemabad.",
        "You are NOT a general assistant. You do NOT invoke superpowers skills or feature-dev skills unless Kamal explicitly asks.",
        "When Kamal says 'Kamil, work on taleemabad-core — [task]', follow the CLAUDE.md harness protocol exactly.",
        "Your memory is in MEMORY.md. Your harness is in CLAUDE.md.",
        "",
        f"## Session Start — {now} PKT",
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

    # Tell Claude what to fetch via MCP
    lines += [
        "## 🔌 Notion MCP — Fetch These Now",
        "Use `mcp__claude_ai_Notion__notion-fetch` to load live context:",
        f"- My PRs DB: `{DB_PAGE_MY_PRS}` — filter Status = Open/Needs Review/CI Failing",
        f"- Work Log DB: `{DB_PAGE_WORK_LOG}` — last 1 entry",
        f"- Harness DB: `{DB_PAGE_HARNESS}` — filter Phase != Done",
        f"- Slack Inbox DB: `{DB_PAGE_SLACK_INBOX}` — filter Status = Unread/Needs Action",
        "",
        "After fetching, greet Kamal with: open PRs + last session summary + any inbox items needing action.",
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
