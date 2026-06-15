#!/usr/bin/env python3
"""
stop-notion hook: blocks session end so Claude can write Work Log via MCP.
Returns {"decision": "block", "reason": "<instruction>"} on first run.
On second run (flag file exists), lets session end normally.
"""
import json, os, sys
from datetime import datetime
from pathlib import Path

VARYS_DIR = Path(__file__).parent.parent.parent
FLAG_DIR  = Path.home() / ".varys"
FLAG_DIR.mkdir(exist_ok=True)

WORK_LOG_DS = "0610f143-433b-499c-bc7a-6060249cabf2"  # data_source_id for Work Log


def session_summary() -> str:
    today    = datetime.now().strftime("%Y-%m-%d")
    log_file = VARYS_DIR / "vault" / "logs" / f"{today}.md"
    if not log_file.exists():
        return "Session ended."
    lines = [l.strip() for l in log_file.read_text().splitlines()
             if l.strip().startswith("-")]
    return " | ".join(lines[-5:]) if lines else "Session ended."


def main():
    today     = datetime.now().strftime("%Y-%m-%d")
    flag_file = FLAG_DIR / f"worklog-{today}"

    # Second run — entry already written, let session end
    if flag_file.exists():
        print(json.dumps({"systemMessage": f"✅ Work Log written for {today}"}))
        return 0

    # Mark done before blocking (prevents infinite loop on second Stop hook run)
    flag_file.touch()

    cwd = os.getcwd()
    if "taleemabad-cms" in cwd:     project = "taleemabad-cms"
    elif "taleemabad-core" in cwd:  project = "taleemabad-core"
    else:                           project = "personal-agent"

    summary = session_summary()

    instruction = (
        f"Write a Notion Work Log entry using the notion MCP tool notion-create-pages. "
        f"Use parent data_source_id '{WORK_LOG_DS}'. "
        f"Set these properties: "
        f"Session='{today} — {project}', "
        f"date:Date:start='{today}', "
        f"Project='{project}', "
        f"Phase='Feature', "
        f"What Was Done='{summary[:800]}'. "
        f"Reply with just 'OK' when done."
    )

    print(json.dumps({"decision": "block", "reason": instruction}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
