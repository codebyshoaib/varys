#!/usr/bin/env python3
"""
stop-notion hook: writes a Work Log entry to Notion via direct REST at session end.
Requires NOTION_API_KEY and NOTION_WORK_LOG_DB_ID in ~/.agent-config.json.
"""
import json, os, sys, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path
import time as _time

sys.path.insert(0, str(Path(__file__).parent))
try:
    import varys_log as _k
except Exception:
    _k = None
from agent_config import cfg

VARYS_DIR = Path(__file__).parent.parent.parent
NOTION_VERSION = "2022-06-28"


def notion_post(endpoint: str, body: dict) -> dict:
    key = cfg("NOTION_API_KEY")
    req = urllib.request.Request(
        f"https://api.notion.com/v1/{endpoint}",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def session_summary() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = VARYS_DIR / "vault" / "logs" / f"{today}.md"
    if not log_file.exists():
        return "Session ended — no log file."
    lines = [l.strip() for l in log_file.read_text().splitlines() if l.strip().startswith("-")]
    return "\n".join(lines[-10:]) if lines else "Session ended."


def main():
    t0 = _time.time()
    key = cfg("NOTION_API_KEY")
    db_id = cfg("NOTION_WORK_LOG_DB_ID")

    if not key or not db_id:
        msg = "⚠️ stop-notion: NOTION_API_KEY or NOTION_WORK_LOG_DB_ID not configured"
        print(msg, file=sys.stderr)
        print(json.dumps({"systemMessage": msg}))
        return 0

    today = datetime.now().strftime("%Y-%m-%d")
    summary = session_summary()

    # Detect project from cwd
    cwd = os.getcwd()
    if "taleemabad-cms" in cwd:
        project = "taleemabad-cms"
    elif "taleemabad-core" in cwd:
        project = "taleemabad-core"
    else:
        project = "personal-agent"

    try:
        notion_post("pages", {
            "parent": {"database_id": db_id},
            "properties": {
                "Session": {"title": [{"text": {"content": f"{today} — {project}"}}]},
                "Date": {"date": {"start": today}},
                "Project": {"select": {"name": project}},
                "Phase": {"select": {"name": "Feature"}},
                "What Was Done": {"rich_text": [{"text": {"content": summary[:2000]}}]},
            },
        })
        msg = f"✅ Work Log written: {today} — {project}"
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        msg = f"⚠️ stop-notion HTTP {e.code}: {body[:200]}"
    except Exception as e:
        msg = f"⚠️ stop-notion failed: {e}"

    print(msg, file=sys.stderr)
    print(json.dumps({"systemMessage": msg}))
    if _k:
        status = "ok" if "✅" in msg else "error"
        _k.klog_cron("stop-notion", status=status, duration_ms=(_time.time()-t0)*1000)
    return 0


if __name__ == "__main__":
    sys.exit(main())
