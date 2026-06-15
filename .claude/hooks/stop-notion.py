#!/usr/bin/env python3
"""
stop-notion hook: writes Work Log to Notion via direct REST (ntn_ token).
Fast — no subprocess, no MCP, no blocking.
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


def session_summary() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = VARYS_DIR / "vault" / "logs" / f"{today}.md"
    if not log_file.exists():
        return "Session ended."
    lines = [l.strip() for l in log_file.read_text().splitlines()
             if l.strip().startswith("-")]
    return " | ".join(lines[-5:]) if lines else "Session ended."


def main():
    t0 = _time.time()
    key = cfg("NOTION_API_KEY")
    db_id = cfg("NOTION_WORK_LOG_DB_ID", "37f902248f3d817890d2c70c1635bad9")

    if not key:
        print(json.dumps({"systemMessage": "⚠️ stop-notion: NOTION_API_KEY not set"}))
        return 0

    today = datetime.now().strftime("%Y-%m-%d")
    cwd = os.getcwd()
    if "taleemabad-cms" in cwd:    project = "taleemabad-cms"
    elif "taleemabad-core" in cwd: project = "taleemabad-core"
    else:                          project = "personal-agent"

    summary = session_summary()

    body = json.dumps({
        "parent": {"database_id": db_id},
        "properties": {
            "Date":      {"title": [{"text": {"content": f"{today} — {project}"}}]},
            "Session ID":{"rich_text": [{"text": {"content": project}}]},
            "Summary":   {"rich_text": [{"text": {"content": summary[:2000]}}]},
        },
    }).encode()

    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            msg = f"✅ Work Log written: {today} — {project}"
    except urllib.error.HTTPError as e:
        msg = f"⚠️ stop-notion HTTP {e.code}: {e.read().decode()[:150]}"
    except Exception as e:
        msg = f"⚠️ stop-notion failed: {e}"

    print(msg, file=sys.stderr)
    print(json.dumps({"systemMessage": msg}))
    if _k:
        _k.klog_cron("stop-notion", status="ok" if "✅" in msg else "error",
                     duration_ms=(_time.time()-t0)*1000)
    return 0


if __name__ == "__main__":
    sys.exit(main())
