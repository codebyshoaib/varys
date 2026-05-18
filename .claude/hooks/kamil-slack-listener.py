#!/usr/bin/env python3
"""
kamil-slack-listener.py — Listens for DMs to Kamil bot via Socket Mode.

When you DM @Kamil in Slack, this script catches the message,
runs a Claude session, and replies back in the same DM thread.

Run:
  python3 .claude/hooks/kamil-slack-listener.py

Auto-start: add to ~/.config/systemd/user/ or run via kamil-start.sh
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_CONFIG = Path.home() / ".claude" / "hooks" / ".slack"
KAMIL_DIR = Path(__file__).parent.parent.parent

def load_config():
    config = {}
    if SLACK_CONFIG.exists():
        for line in SLACK_CONFIG.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                config[k.strip()] = v.strip()
    return config

cfg = load_config()
BOT_TOKEN = cfg.get("BOT_TOKEN", "")
APP_TOKEN = cfg.get("APP_TOKEN", "")
KAMAL_USER_ID = "U0AV1DX3WSE"
NOTION_BRAIN_PAGE_ID = "364d8747b3b1813d8ac8c248800f0a4d"


def ask_kamil(question: str) -> str:
    """Run a Claude session and return Kamil's answer."""
    prompt = f"""You are Kamil, Kamal's autonomous personal AI agent. You know everything about his work at Taleemabad, his projects, teammates, and ongoing tasks.

Kamal sent you this message on Slack: "{question}"

Answer directly and helpfully. Be concise. No fluff. You are replying to him on Slack.
Sign off with 🤖"""

    nvm_source = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    env = os.environ.copy()
    env["KAMIL_PROMPT"] = prompt

    result = subprocess.run(
        ["bash", "-c", f'{nvm_source} && claude --dangerously-skip-permissions --print -p "$KAMIL_PROMPT"'],
        capture_output=True,
        text=True,
        cwd=str(KAMIL_DIR),
        timeout=120,
        env=env,
    )

    if result.returncode != 0 or not result.stdout.strip():
        return "Sorry, I ran into an issue processing your message. Try again or use `kamil \"your question\"` in the terminal. 🤖"

    return result.stdout.strip()


def process(client: SocketModeClient, req: SocketModeRequest):
    """Handle incoming Slack events."""
    # Acknowledge immediately
    client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

    if req.type != "events_api":
        return

    event = req.payload.get("event", {})
    event_type = event.get("type", "")

    # Handle DMs and @mentions
    if event_type not in ("message", "app_mention"):
        return
    if event_type == "message" and event.get("channel_type") != "im":
        return
    if event.get("bot_id"):
        return  # ignore bot's own messages
    if event.get("subtype"):
        return  # ignore edits, deletions

    text = event.get("text", "").strip()
    channel = event.get("channel")
    user = event.get("user")

    if not text or not channel:
        return

    # Strip the @Kamil mention from text
    import re
    text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()

    # Only respond to Kamal — log everyone else silently
    if user != KAMAL_USER_ID:
        log(f"IGNORED (not Kamal): user={user} channel={channel} text={text[:60]!r}")
        return

    print(f"[kamil-listener] Kamal says: {text[:60]}", flush=True)

    # Show typing indicator
    web = WebClient(token=BOT_TOKEN)
    try:
        web.assistant_threads_setStatus(channel_id=channel, thread_ts=event.get("ts",""), status="is thinking...")
    except Exception:
        pass

    # Get answer from Claude
    answer = ask_kamil(text)

    # Reply in thread
    thread_ts = event.get("ts")
    web.chat_postMessage(channel=channel, text=answer, thread_ts=thread_ts)
    print(f"[kamil-listener] Replied: {answer[:60]}", flush=True)


def main():
    if not BOT_TOKEN or not APP_TOKEN:
        print("ERROR: BOT_TOKEN and APP_TOKEN required in ~/.claude/hooks/.slack", file=sys.stderr)
        sys.exit(1)

    web = WebClient(token=BOT_TOKEN)
    socket_client = SocketModeClient(app_token=APP_TOKEN, web_client=web)
    socket_client.socket_mode_request_listeners.append(process)

    print("[kamil-listener] Connecting to Slack via Socket Mode...", flush=True)
    socket_client.connect()
    print("[kamil-listener] Connected. Waiting for messages from Kamal...", flush=True)

    # Keep alive
    import time
    while True:
        time.sleep(10)


if __name__ == "__main__":
    main()
