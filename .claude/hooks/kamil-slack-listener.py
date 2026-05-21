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


# ── Intent detection ──────────────────────────────────────────────────────────

def detect_intent(text: str) -> str:
    t = text.lower()
    if re.search(r"(review|check|look at)\b.{0,40}\b(pr|pull request|diff|code)", t):
        return "pr_review"
    if "github.com" in t and "/pull/" in t:
        return "pr_review"
    if re.search(r"\bpr\s*#?\d+\b", t):
        return "pr_review"
    if re.search(r"(create|build|make|set up|generate)\b.{0,50}\b(notion|database|db|page)", t):
        return "notion_task"
    if re.search(r"(work on|implement|build|fix|add|create)\b.{0,50}\b(feature|bug|task|ticket|issue)", t):
        return "task"
    if re.search(r"kamil.{0,30}(taleemabad|core|cms|auth)\b", t):
        return "task"
    if "?" in text or re.search(r"^(what|how|why|when|who|where|can|could|find|search|look up|show me|list)\b", t):
        return "research"
    return "chat"


def extract_pr_url(text: str) -> str | None:
    m = re.search(r"https://github\.com/[^\s>]+/pull/\d+", text)
    return m.group(0) if m else None


# ── Intent handlers ───────────────────────────────────────────────────────────

def handle_pr_review(text: str, web: WebClient, channel: str, thread_ts: str):
    pr_ref = extract_pr_url(text) or "the PR"
    web.chat_postMessage(channel=channel, text=f"🔍 Fetching and reviewing {pr_ref}...", thread_ts=thread_ts)

    answer = run_claude(f"""You are Kamil — Kamal's AI agent at Taleemabad.

Kamal asked: "{text}"

1. If there's a GitHub PR URL, use the gh CLI or web fetch to get the diff and changed files.
2. Review for: bugs, logic errors, missing edge cases, security, Django/React best practices, multi-tenancy, soft-delete.
3. Structure your reply for Slack:
   *Summary:* 1-2 sentences
   *✅ What's good:* bullet points
   *⚠️ Issues:* file:line — description
   *💡 Suggestions:* bullet points
   *🚦 Verdict:* Approve / Request Changes / Needs Discussion

Be direct. No markdown headers (use *bold* instead). Sign off: 🤖 Kamil""", timeout=300)

    web.chat_postMessage(channel=channel, text=answer, thread_ts=thread_ts)
    log(f"PR review sent: {pr_ref}")


def handle_notion_task(text: str, web: WebClient, channel: str, thread_ts: str):
    """Handle requests to create/update Notion databases or pages."""
    web.chat_postMessage(channel=channel, text="🗂️ On it — building that in Notion...", thread_ts=thread_ts)

    answer = run_claude(f"""You are Kamil — Kamal's AI agent at Taleemabad.

Kamal asked: "{text}"

You have full access to Notion via MCP (mcp__claude_ai_Notion__* tools) and GitHub via gh CLI.

Execute the request completely:
- If he wants a database of repos: use `gh repo list <org> --limit 100 --json name,description,url,language,updatedAt` to get repos, then create a Notion database with the right schema and populate it.
- If he wants pages, summaries, or any other Notion work: do it directly.

After completing: reply with what you built, the Notion URL, and a 1-line summary of what's in it.
Format for Slack. Sign off: 🤖 Kamil""", timeout=360)

    web.chat_postMessage(channel=channel, text=answer, thread_ts=thread_ts)
    log(f"Notion task done: {text[:60]}")


def handle_task(text: str, web: WebClient, channel: str, thread_ts: str):
    web.chat_postMessage(channel=channel, text="📋 Creating Harness entry and starting work...", thread_ts=thread_ts)

    answer = run_claude(f"""You are Kamil — Kamal's AI agent at Taleemabad.

Kamal assigned this task via Slack: "{text}"

1. Infer the project (taleemabad-core, taleemabad-cms, etc.) from context.
2. Create a Notion Harness entry (DB: {DB_PAGE_HARNESS}) with: Feature name, Phase=Research, Plan Summary.
3. If taleemabad-core: cd /home/oye/Documents/taleemabad-core → git checkout develop && git pull → git checkout -b kamil/<name> → run /feature <name>.
4. Reply: branch name, Harness entry created, what /feature found, next step.

Slack format (*bold*, bullets). Sign off: 🤖 Kamil""", timeout=360)

    web.chat_postMessage(channel=channel, text=answer, thread_ts=thread_ts)
    log(f"Task started: {text[:60]}")


def handle_research(text: str, web: WebClient, channel: str, thread_ts: str):
    web.chat_postMessage(channel=channel, text="🔎 Looking into that...", thread_ts=thread_ts)

    answer = run_claude(f"""You are Kamil — Kamal's AI agent at Taleemabad.

Kamal asked: "{text}"

Use whatever tools give the best answer:
- Notion MCP → for questions about Kamal's work, projects, team, PRs
- Web search → for technical questions, external knowledge
- gh CLI → for GitHub/repo questions
- File reads → for codebase questions

Give a direct answer with sources. Concise for Slack.
Sign off: 🤖 Kamil""", timeout=180)

    web.chat_postMessage(channel=channel, text=answer, thread_ts=thread_ts)
    log(f"Research: {text[:60]}")


def handle_chat(text: str, web: WebClient, channel: str, thread_ts: str):
    answer = run_claude(f"""You are Kamil — Kamal's AI agent at Taleemabad.

Kamal said: "{text}"

Reply directly. You know his work, his team, his stack. Be helpful, concise, Kamil personality.
Slack format. Sign off: 🤖 Kamil""", timeout=120)

    web.chat_postMessage(channel=channel, text=answer, thread_ts=thread_ts)


def dispatch(text: str, web: WebClient, channel: str, thread_ts: str, source: str):
    """Route a message to the right handler."""
    global last_activity_time
    last_activity_time = time.time()

    # Strip @mentions and whitespace
    clean = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    if not clean:
        return

    intent = detect_intent(clean)
    log(f"[{source}] intent={intent} | {clean[:60]}")

    if intent == "pr_review":
        threading.Thread(target=handle_pr_review, args=(clean, web, channel, thread_ts), daemon=True).start()
    elif intent == "notion_task":
        threading.Thread(target=handle_notion_task, args=(clean, web, channel, thread_ts), daemon=True).start()
    elif intent == "task":
        threading.Thread(target=handle_task, args=(clean, web, channel, thread_ts), daemon=True).start()
    elif intent == "research":
        threading.Thread(target=handle_research, args=(clean, web, channel, thread_ts), daemon=True).start()
    else:
        threading.Thread(target=handle_chat, args=(clean, web, channel, thread_ts), daemon=True).start()


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
