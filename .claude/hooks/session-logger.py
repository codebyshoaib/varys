#!/usr/bin/env python3
"""
session-logger.py — UserPromptSubmit + PostToolUse hook.

Appends to vault/logs/YYYY-MM-DD.md so brain-watcher has content at session end.

UserPromptSubmit: logs each user turn (short human messages only).
PostToolUse:      logs Write/Edit calls to .claude/hooks/ (decisions made via code).
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

VARYS_DIR = Path(__file__).parent.parent.parent
LOG_DIR   = VARYS_DIR / "vault" / "logs"


def _append(entry: str):
    now = datetime.now()
    log_file = LOG_DIR / f"{now.strftime('%Y-%m-%d')}.md"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"- {now.strftime('%H:%M')} — {entry}\n")


def handle_prompt(data: dict):
    prompt = (data.get("prompt") or "").strip()
    if not prompt or len(prompt) < 10:
        return

    prompt = re.sub(r"<system-reminder>.*?</system-reminder>", "", prompt, flags=re.DOTALL)
    prompt = re.sub(r"<[^>]+>.*?</[^>]+>", "", prompt, flags=re.DOTALL)
    prompt = prompt.strip()
    if not prompt:
        return

    # Skip LLM-style prompts from subprocess --print calls
    skip_prefixes = ("you are ", "return only", "from this ", "output only")
    if any(prompt.lower().startswith(p) for p in skip_prefixes):
        return
    if len(prompt) > 800:
        return

    _append(f"[user] {prompt[:300]}")


def handle_tool(data: dict):
    tool = data.get("tool_name", "")
    if tool not in ("Write", "Edit"):
        return

    file_path = (data.get("tool_input") or {}).get("file_path", "")
    if not file_path:
        return

    # Only log changes to hooks/agents/skills — these represent decisions
    rel = file_path.replace(str(VARYS_DIR) + "/", "")
    interesting = any(rel.startswith(p) for p in
                      (".claude/hooks/", ".claude/agents/", ".claude/skills/", ".claude/rules/"))
    if not interesting:
        return

    action = "created" if tool == "Write" else "edited"
    _append(f"[code] {action} {rel}")


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except Exception:
        sys.exit(0)

    if "prompt" in data:
        handle_prompt(data)
    elif "tool_name" in data:
        handle_tool(data)

    sys.exit(0)


if __name__ == "__main__":
    main()

