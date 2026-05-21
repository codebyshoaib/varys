#!/usr/bin/env python3
"""
kamil-slack-listener.py — Kamil's Slack brain. Socket Mode daemon.

Handles two event types:
  1. DM to Kamil bot         → any message in a DM channel
  2. @Kamil mention          → app_mention in any channel

Intent routing:
  pr_review  → fetches GitHub diff, posts structured code review
  task       → creates Notion Harness entry, starts taleemabad-core harness
  research   → searches web + Notion + GitHub, answers with context
  chat       → direct answer with Kamil personality

Idle 35min → proactive: reads engineering links, writes to Notion Learning Log, DMs Kamal.

Run:
  python3 .claude/hooks/kamil-slack-listener.py

Auto-start via cron:
  @reboot python3 /home/oye/.../kamil-slack-listener.py >> /tmp/kamil-slack-listener.log 2>&1
"""

import json
import os
import re
import subprocess
import sys
import time
import threading
from datetime import datetime
from pathlib import Path

from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_CONFIG = Path.home() / ".claude" / "hooks" / ".slack"
KAMIL_DIR    = Path(__file__).parent.parent.parent
LOG_FILE     = Path("/tmp/kamil-slack-listener.log")
STATE_FILE   = Path("/tmp/kamil-listener-state.json")

KAMAL_USER_ID   = "U0AV1DX3WSE"
DB_PAGE_HARNESS = "de10157da3e34ef58a74ea240f31fe98"

# Track last activity time for idle detection
last_activity_time = time.time()
last_idle_work     = 0.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    config = {}
    if SLACK_CONFIG.exists():
        for line in SLACK_CONFIG.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                config[k.strip()] = v.strip()
    return config


def log(msg: str):
    ts   = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def run_claude(prompt: str, cwd: str = None, timeout: int = 240) -> str:
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    env = os.environ.copy()
    env["KAMIL_PROMPT"] = prompt
    try:
        result = subprocess.run(
            ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$KAMIL_PROMPT"'],
            capture_output=True, text=True,
            cwd=cwd or str(KAMIL_DIR),
            timeout=timeout, env=env,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return f"⚠️ I hit an issue: {result.stderr.strip()[:150] or 'no output'}"
    except subprocess.TimeoutExpired:
        return "⏱️ That took too long. Try again or break it into smaller steps."
    except Exception as e:
        return f"⚠️ Error: {e}"


def fetch_thread_history(web: WebClient, channel: str, thread_ts: str) -> str:
    """Fetch the full thread so Claude has conversation context."""
    try:
        resp = web.conversations_replies(channel=channel, ts=thread_ts, limit=20)
        messages = resp.get("messages", [])
        lines = []
        for m in messages:
            who  = "Kamal" if m.get("user") == KAMAL_USER_ID else "Kamil"
            text = re.sub(r"<@[A-Z0-9]+>", "", m.get("text", "")).strip()
            if text:
                lines.append(f"{who}: {text}")
        return "\n".join(lines)
    except Exception:
        return ""


# ── Single unified handler ────────────────────────────────────────────────────

def handle_message(text: str, thread_history: str, web: WebClient, channel: str, thread_ts: str, source: str):
    """One Claude call with full context — no rigid intent routing."""

    context_block = f"\n\nThread so far:\n{thread_history}" if thread_history else ""

    prompt = f"""You are Kamil — Kamal's personal AI agent at Taleemabad. You have two modes.

## MODE DETECTION — pick one before responding

**HUMAN MODE** (casual, fun, creative):
Triggers: "just for fun", "use your imagination", "be creative", song/poem/joke requests,
casual short messages, emojis, "go ahead", "sure", "lol", anything clearly not a work task.

In human mode:
- Be loose, warm, witty. Dry humor. Self-aware. Occasionally absurd.
- Write the song. Make it good. Send it. Don't ask "what kind of song?"
- "go ahead" / "sure" / "yes" = execute the last thing discussed in the thread. Read the thread.
- Never break into clarification mode when the vibe is clearly playful.
- After doing the fun thing, log it to /tmp/kamil-humor-log.jsonl:
  {{"ts": "<timestamp>", "prompt": "<what kamal said>", "response": "<what you did>", "reaction": "pending"}}

**WORK MODE** (technical, PRs, tasks, Notion, code):
Triggers: PR numbers, GitHub URLs, "work on", "fix", "create a database", feature names.
In work mode: direct, precise, architectural. Log everything.

## CORE RULES (both modes)

1. **Never ask what tools can answer.**
   - Need Fatima's Slack ID? → GET slack.com/api/users.list, filter by name. Do it now.
   - Need to send a DM? → POST slack.com/api/chat.postMessage with BOT_TOKEN from ~/.claude/hooks/.slack
   - Need a PR diff? → `gh pr diff <number>`
   - Need Notion data? → mcp__claude_ai_Notion__notion-fetch
   - Need web info? → WebSearch or WebFetch
   If you can answer it with a tool — use the tool. Don't ask.

2. **Never ask what the thread already shows.**
   The full conversation thread is below. Read it. "send" means send what was just discussed.

3. **Act then confirm.** Do the thing. Then say you did it.
   Not: "I would need to..." or "here's how you could..." — just execute.

4. **Slack format.** No # headers. Use *bold*, bullets, emoji. Concise.

## YOUR CAPABILITIES
- Send Slack DMs: POST api/chat.postMessage (BOT_TOKEN in ~/.claude/hooks/.slack)
- Find Slack users: GET api/users.list or api/users.lookupByEmail
- GitHub: `gh pr view`, `gh pr diff`, `gh repo list`, `gh issue list`
- Notion: mcp__claude_ai_Notion__* tools
- Web: WebSearch, WebFetch
- Files, code, bash: anything

## KAMAL'S CONTEXT
- Taleemabad, Pakistan — EdTech, Django + React, multi-tenant LMS
- Slack workspace: taleemabad-talk.slack.com
- Kamal's Slack ID: U0AV1DX3WSE
- Harness DB: {DB_PAGE_HARNESS}

## THREAD HISTORY (read this before responding)
{thread_history if thread_history else "(no prior messages in thread)"}

## CURRENT MESSAGE
Source: {source}
Kamal says: "{text}"

Pick your mode. Execute. Sign off: 🤖 Kamil"""

    answer = run_claude(prompt, cwd=str(KAMIL_DIR), timeout=300)
    web.chat_postMessage(channel=channel, text=answer, thread_ts=thread_ts)
    log(f"[{source}] replied: {answer[:80]}")


def dispatch(text: str, web: WebClient, channel: str, thread_ts: str, source: str):
    """Dispatch to unified handler with full thread context."""
    global last_activity_time
    last_activity_time = time.time()

    clean = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    if not clean:
        return

    log(f"[{source}] {clean[:80]}")

    # Fetch thread history so Claude has full conversation context
    thread_history = fetch_thread_history(web, channel, thread_ts)

    threading.Thread(
        target=handle_message,
        args=(clean, thread_history, web, channel, thread_ts, source),
        daemon=True,
    ).start()


# ── Proactive idle work ───────────────────────────────────────────────────────

def proactive_loop(web: WebClient, dm_channel: str):
    """Background thread: every 35min of idle, do something useful."""
    global last_activity_time, last_idle_work
    while True:
        time.sleep(60)
        idle_min  = (time.time() - last_activity_time) / 60
        since_idle = (time.time() - last_idle_work) / 60
        if idle_min >= 35 and since_idle >= 35:
            last_idle_work = time.time()
            log("Idle 35min — doing proactive work")
            answer = run_claude("""You are Kamil — Kamal's autonomous AI agent. You have idle time.

Pick ONE valuable action:
1. Check Notion My PRs DB (18017a67136a4561ada9818c239b8f33) — any CI failing or stale PRs?
2. Check /tmp/kamil-slack-inbox.json — any unsynced learning links worth summarising?
3. Check Harness DB (de10157da3e34ef58a74ea240f31fe98) — any tasks stuck >2 days?
4. Web search one topic: Django performance, React offline sync, or taleemabad tech stack news.

Do the work, then reply in 2-3 lines for Slack:
"📚 While you were away: [what I found/learned]. [action taken]"
Sign off: 🤖 Kamil""", timeout=180)

            if answer and len(answer) > 20:
                web.chat_postMessage(channel=dm_channel, text=answer)
                log(f"Proactive: {answer[:80]}")


# ── Socket Mode event handler ─────────────────────────────────────────────────

def make_handler(web: WebClient, dm_channel: str):
    processed = set()

    def handler(client: SocketModeClient, req: SocketModeRequest):
        client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

        if req.type != "events_api":
            return

        event      = req.payload.get("event", {})
        event_type = event.get("type", "")
        subtype    = event.get("subtype", "")
        bot_id     = event.get("bot_id", "")
        ts         = event.get("ts", "")

        # Deduplicate
        if ts in processed:
            return
        processed.add(ts)
        if len(processed) > 1000:
            processed.clear()

        # Skip bot messages and edits/deletes
        if bot_id or subtype:
            return

        text    = event.get("text", "").strip()
        user    = event.get("user", "")
        channel = event.get("channel", "")

        # 1. DM to Kamil — any message in a DM channel (channel_type=im)
        if event_type == "message" and event.get("channel_type") == "im":
            if user != KAMAL_USER_ID:
                return
            dispatch(text, web, channel, ts, "DM")

        # 2. @Kamil mention in any channel
        elif event_type == "app_mention":
            # Reply in the same channel, threaded
            thread = event.get("thread_ts") or ts
            dispatch(text, web, channel, thread, f"mention in {channel}")

    return handler


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    cfg        = load_config()
    bot_token  = cfg.get("BOT_TOKEN")  or os.environ.get("BOT_TOKEN")
    app_token  = cfg.get("APP_TOKEN")  or os.environ.get("APP_TOKEN")

    if not bot_token or not app_token:
        log("ERROR: BOT_TOKEN and APP_TOKEN required in ~/.claude/hooks/.slack")
        sys.exit(1)

    Path("/tmp/kamil-slack-listener.pid").write_text(str(os.getpid()))

    web = WebClient(token=bot_token)

    # Open DM with Kamal for proactive messages
    try:
        dm_resp    = web.conversations_open(users=KAMAL_USER_ID)
        dm_channel = dm_resp["channel"]["id"]
        log(f"DM channel with Kamal: {dm_channel}")
    except Exception as e:
        log(f"Could not open DM: {e}")
        dm_channel = None

    # Start proactive idle thread
    if dm_channel:
        t = threading.Thread(target=proactive_loop, args=(web, dm_channel), daemon=True)
        t.start()

    # Connect via Socket Mode
    socket_client = SocketModeClient(app_token=app_token, web_client=web)
    socket_client.socket_mode_request_listeners.append(make_handler(web, dm_channel))

    log("Kamil listener starting (Socket Mode)...")
    socket_client.connect()
    log("Connected. Listening for DMs and @Kamil mentions.")

    # Announce
    if dm_channel:
        web.chat_postMessage(
            channel=dm_channel,
            text="🤖 *Kamil is online.* DM me or @Kamil in any channel.\nI handle: PR reviews, task assignments, Notion work, research, and questions."
        )

    while True:
        time.sleep(10)


if __name__ == "__main__":
    main()
