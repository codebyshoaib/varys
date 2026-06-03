#!/usr/bin/env python3
"""
stop-notion hook: Runs at session end (Stop event)

Replaces the old stop.py vault+MemPalace approach.
Writes a Work Log entry to Notion with session summary.

Claude is expected to output a JSON summary before session ends —
this hook reads it from stdin (hook input), or builds a minimal entry.

Config: ~/.claude/hooks/.notion  →  NOTION_API_KEY=secret_...
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
import sys as _sys, time as _time
_sys.path.insert(0, "/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks")
try:
    import kamil_log as _k
except Exception:
    _k = None
try:
    from kamil_notion import notion_request as _notion_request
except Exception:
    _notion_request = None

NOTION_CONFIG   = Path.home() / ".claude" / "hooks" / ".notion"
DB_PAGE_WORK_LOG = "0b71db855f914d18ac6d97c0f77fc21e"


def load_api_key() -> str | None:
    if NOTION_CONFIG.exists():
        for line in NOTION_CONFIG.read_text().splitlines():
            line = line.strip()
            if line.startswith("NOTION_API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("NOTION_API_KEY")


def notion_create_page(api_key: str, db_id: str, properties: dict, content: str = "") -> bool:
    url = "https://api.notion.com/v1/pages"
    body = {
        "parent": {"database_id": db_id},
        "properties": properties,
    }
    if content:
        body["children"] = [{
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": content[:2000]}}]
            }
        }]
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    # COMMIT-POINT RULE (harness-v2):
    # For UPDATE flows: always write Status LAST — a successful Status write = work complete.
    # This file only does CREATE (all-or-nothing) — rule applies when extending to updates.
    try:
        if _notion_request:
            _, body = _notion_request(req)
            result = json.loads(body)
        else:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
        return "id" in result
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"[stop-notion] Notion create error {e.code}: {err[:200]}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[stop-notion] Notion create error: {e}", file=sys.stderr)
        return False


def make_notion_title(value: str) -> dict:
    return {"title": [{"type": "text", "text": {"content": value[:2000]}}]}


def make_notion_text(value: str) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": value[:2000]}}]}


def make_notion_select(value: str) -> dict:
    return {"select": {"name": value}}


def make_notion_date(iso: str) -> dict:
    return {"date": {"start": iso}}


def main():
    api_key = load_api_key()
    if not api_key:
        print("[stop-notion] No NOTION_API_KEY — skipping Work Log write", file=sys.stderr)
        return 0

    today = datetime.now().strftime("%Y-%m-%d")
    now   = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Read hook input from stdin (Claude Code passes JSON)
    hook_input = {}
    try:
        raw = sys.stdin.read()
        if raw.strip():
            hook_input = json.loads(raw)
    except Exception:
        pass

    # Extract any session summary Claude may have printed
    # (Claude is instructed to output a JSON summary block)
    session_summary = hook_input.get("session_summary", {})
    what_done  = session_summary.get("what_done", "Session ended — no summary provided.")
    prs_worked = session_summary.get("prs_worked", "")
    blockers   = session_summary.get("blockers", "")
    next_steps = session_summary.get("next_steps", "")
    project    = session_summary.get("project", "taleemabad-core")
    phase      = session_summary.get("phase", "Feature")

    # Detect project from cwd if not in summary
    cwd = os.getcwd()
    if "taleemabad-core" in cwd:
        project = "taleemabad-core"
    elif "taleemabad-cms" in cwd:
        project = "taleemabad-cms"
    elif "personal-agent" in cwd:
        project = "personal-agent"

    session_title = f"{today} — {project} session"

    properties = {
        "Session":       make_notion_title(session_title),
        "date:Date:start": today,  # plain string, Notion API accepts ISO date
        "Project":       make_notion_select(project),
        "Phase":         make_notion_select(phase),
        "What Was Done": make_notion_text(what_done),
    }

    # Add optional fields only if non-empty
    if prs_worked:
        properties["PRs Worked On"] = make_notion_text(prs_worked)
    if blockers:
        properties["Blockers"] = make_notion_text(blockers)
    if next_steps:
        properties["Next Steps"] = make_notion_text(next_steps)

    # Fix date property format (Notion API needs nested object)
    properties["date:Date:start"] = None  # remove invalid key
    del properties["date:Date:start"]
    properties["Date"] = make_notion_date(today)

    success = notion_create_page(api_key, DB_PAGE_WORK_LOG, properties)

    if success:
        print(f"[stop-notion] Work Log entry written: {session_title}", file=sys.stderr)
        output = {"systemMessage": f"✅ Work Log saved to Notion: {session_title}"}
        print(json.dumps(output))
    else:
        print("[stop-notion] Failed to write Work Log entry", file=sys.stderr)

    return 0


if __name__ == "__main__":
    _t0 = _time.time()
    try:
        rc = main()
        if _k: _k.klog_cron("stop-notion", status="ok", duration_ms=(_time.time()-_t0)*1000)
        sys.exit(rc)
    except Exception as _e:
        if _k: _k.klog_error("stop-notion-main", _e, component="stop-notion", severity="ERROR")
        raise
