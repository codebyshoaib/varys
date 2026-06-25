#!/usr/bin/env python3
"""
varys_dm.py — Shared Shoaib DM utility for evolution loops.

Single-source for the token-lookup + DM pattern shared by varys-proactive-evolve.py
and varys-skill-evolve.py. Call dm_shoaib(text) — it resolves the token and user_id
from agent_config / env / .slack file automatically. Fails silently (never raises).
"""

import json
import os
import urllib.request
from pathlib import Path

from agent_config import cfg


def dm_shoaib(text: str) -> None:
    user_id = cfg("USER_SLACK_ID", "")
    token   = cfg("SLACK_BOT_TOKEN", "") or os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        slack = Path.home() / ".claude" / "hooks" / ".slack"
        if slack.exists():
            for line in slack.read_text().splitlines():
                if line.startswith(("BOT_TOKEN=", "SLACK_BOT_TOKEN=")):
                    token = line.split("=", 1)[1].strip()
    if not user_id or not token:
        return
    try:
        opened = urllib.request.urlopen(urllib.request.Request(
            "https://slack.com/api/conversations.open",
            data=json.dumps({"users": user_id}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}),
            timeout=10)
        ch = json.loads(opened.read()).get("channel", {}).get("id")
        if not ch:
            return
        urllib.request.urlopen(urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=json.dumps({"channel": ch, "text": text}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}),
            timeout=10)
    except Exception:
        pass


if __name__ == "__main__":
    # Self-check: module imports and function is callable
    assert callable(dm_shoaib)
    print("varys_dm: OK")
