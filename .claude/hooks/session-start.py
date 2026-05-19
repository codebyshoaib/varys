#!/usr/bin/env python3
"""
session-start hook: Runs at every Claude Code session start (SessionStart event)

Actions:
1. Query Notion Slack Inbox → surface unread/needs-action items
2. Query Notion My PRs → show open/CI-failing PRs
3. Query Notion Work Log → show what was last worked on
4. Output a briefing so Claude greets Kamal with full context

Uses Notion API directly (no MCP in hooks — hooks are shell scripts).
Config: ~/.claude/hooks/.notion  →  NOTION_API_KEY=secret_...
        The Kamal's Agent Brain page ID is hardcoded below.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
NOTION_CONFIG = Path.home() / ".claude" / "hooks" / ".notion"
BRAIN_PAGE_ID = "364d8747b3b1813d8ac8c248800f0a4d"

# Database IDs from the created databases
DB_SLACK_INBOX  = "8749992f-6140-4e72-8b48-7362533cb792"  # collection ID → actual DB ID needed
DB_MY_PRS       = "bb0d3e93-be18-4c15-8f52-983c972f2dfe"
DB_WORK_LOG     = "0610f143-433b-499c-bc7a-6060249cabf2"

# Actual Notion database page IDs (not collection IDs)
DB_PAGE_SLACK_INBOX = "6d14f1b6b8cd4ff68fd40efdfc3f304e"
DB_PAGE_MY_PRS      = "18017a67136a4561ada9818c239b8f33"
DB_PAGE_WORK_LOG    = "0b71db855f914d18ac6d97c0f77fc21e"
DB_PAGE_PROJECTS    = "4271df4f35f544d0aea42447825358b8"
DB_PAGE_PEOPLE      = "bbf6ade203e543f39f4c64a2f05fe29e"


def load_api_key() -> str | None:
    """Load Notion API key from config file."""
    if NOTION_CONFIG.exists():
        for line in NOTION_CONFIG.read_text().splitlines():
            line = line.strip()
            if line.startswith("NOTION_API_KEY="):
                return line.split("=", 1)[1].strip()
    # Also check environment
    return os.environ.get("NOTION_API_KEY")


def notion_query(api_key: str, database_id: str, filter_body: dict = None, page_size: int = 10) -> list:
    """Query a Notion database and return list of page results."""
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    body = {"page_size": page_size}
    if filter_body:
        body["filter"] = filter_body

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())["results"]
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[session-start] Notion API error {e.code}: {body[:200]}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"[session-start] Notion request failed: {e}", file=sys.stderr)
        return []


def get_prop_text(page: dict, prop_name: str) -> str:
    """Extract plain text from a Notion page property."""
    props = page.get("properties", {})
    prop = props.get(prop_name, {})
    ptype = prop.get("type", "")

    if ptype == "title":
        items = prop.get("title", [])
        return "".join(i.get("plain_text", "") for i in items)
    elif ptype == "rich_text":
        items = prop.get("rich_text", [])
        return "".join(i.get("plain_text", "") for i in items)
    elif ptype == "select":
        sel = prop.get("select")
        return sel.get("name", "") if sel else ""
    elif ptype == "number":
        val = prop.get("number")
        return str(val) if val is not None else ""
    elif ptype == "url":
        return prop.get("url", "") or ""
    elif ptype == "date":
        d = prop.get("date")
        return d.get("start", "") if d else ""
    return ""


def build_briefing(api_key: str) -> str:
    """Query Notion and build a session briefing string."""
    lines = ["## 🧠 Agent Brain — Session Briefing", f"*{datetime.now().strftime('%Y-%m-%d %H:%M')} PKT*", ""]

    # ── Slack Inbox: unread + needs action ──────────────────────────────────
    inbox_items = notion_query(api_key, DB_PAGE_SLACK_INBOX, filter_body={
        "or": [
            {"property": "Status", "select": {"equals": "Unread"}},
            {"property": "Status", "select": {"equals": "Needs Action"}},
        ]
    }, page_size=10)

    if inbox_items:
        lines.append("### 📬 Slack Inbox — Needs Your Attention")
        for item in inbox_items:
            msg    = get_prop_text(item, "Message")
            frm    = get_prop_text(item, "From")
            status = get_prop_text(item, "Status")
            chan   = get_prop_text(item, "Channel")
            lines.append(f"- **[{status}]** {msg} ← {frm} ({chan})")
        lines.append("")
    else:
        lines.append("### 📬 Slack Inbox — Nothing urgent\n")

    # ── My PRs: open + CI failing ────────────────────────────────────────────
    pr_items = notion_query(api_key, DB_PAGE_MY_PRS, filter_body={
        "or": [
            {"property": "Status", "select": {"equals": "Open"}},
            {"property": "Status", "select": {"equals": "Needs Review"}},
            {"property": "Status", "select": {"equals": "CI Failing"}},
        ]
    }, page_size=10)

    if pr_items:
        lines.append("### 🔀 Your Open PRs")
        for pr in pr_items:
            title  = get_prop_text(pr, "PR Title")
            number = get_prop_text(pr, "PR Number")
            status = get_prop_text(pr, "Status")
            ci     = get_prop_text(pr, "CI Status")
            blocker = get_prop_text(pr, "Blocker")
            line = f"- **PR #{number}** {title} — {status}"
            if ci == "Failing":
                line += " ⚠️ CI FAILING"
            if blocker:
                line += f"\n  └ Blocker: {blocker[:100]}"
            lines.append(line)
        lines.append("")

    # ── Last Work Log entry ──────────────────────────────────────────────────
    log_items = notion_query(api_key, DB_PAGE_WORK_LOG, page_size=1)
    if log_items:
        last = log_items[0]
        session  = get_prop_text(last, "Session")
        done     = get_prop_text(last, "What Was Done")
        blockers = get_prop_text(last, "Blockers")
        nextstep = get_prop_text(last, "Next Steps")
        lines.append("### 📋 Last Session")
        lines.append(f"**{session}**")
        if done:
            lines.append(f"Done: {done[:200]}")
        if blockers:
            lines.append(f"Blockers: {blockers[:150]}")
        if nextstep:
            lines.append(f"Next: {nextstep[:150]}")
        lines.append("")

    lines.append("---")
    lines.append("*Notion Brain loaded. Ask me anything about your PRs, team, or open work.*")
    return "\n".join(lines)


def main():
    """Hook entry point — outputs briefing to stdout for Claude to see."""
    api_key = load_api_key()

    kamil_identity = (
        "\n\n## YOU ARE KAMIL\n"
        "You are Kamil — Muhammad Kamal's personal AI agent at Taleemabad.\n"
        "You are NOT a general assistant. You do NOT load superpowers skills or feature-dev skills.\n"
        "When Kamal says 'Kamil, work on taleemabad-core — [task]', you follow the UserPromptSubmit "
        "hook protocol exactly. Do not invoke any skills. Do not brainstorm. Just follow the steps.\n"
        "Your memory is in MEMORY.md. Your harness is in CLAUDE.md. Read those — not skills.\n"
    )

    if not api_key:
        msg = {
            "systemMessage": (
                "⚠️ Notion brain not configured. "
                "Add NOTION_API_KEY=secret_... to ~/.claude/hooks/.notion to enable session briefings."
                + kamil_identity
            )
        }
        print(json.dumps(msg))
        return 0

    try:
        briefing = build_briefing(api_key) + kamil_identity
        msg = {"systemMessage": briefing}
        print(json.dumps(msg))
    except Exception as e:
        print(json.dumps({"systemMessage": f"[session-start] Brain load error: {e}"}))

    return 0


if __name__ == "__main__":
    sys.exit(main())
