#!/usr/bin/env python3
"""
kamil-slack-listener.py — Kamil's Slack brain. Runs as a persistent daemon.

When Kamal DMs Kamil on Slack:
  - PR review assignment  → fetches diff from GitHub, posts real review
  - Task assignment       → creates Notion Harness entry, starts work
  - Question              → searches web/Notion/GitHub, answers with context
  - General chat          → answers directly, Kamil personality

When idle (no messages for 30 min):
  - Reads a learning link from #engineering-learning or #engineering-ai
  - Summarises it, writes to Notion Learning Log
  - DMs Kamal a 1-line "I just learned X" message

Run as daemon:
  python3 .claude/hooks/kamil-slack-listener.py &

Or via systemd — see kamil.service
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_CONFIG = Path.home() / ".claude" / "hooks" / ".slack"
KAMIL_DIR    = Path(__file__).parent.parent.parent
INBOX_FILE   = Path("/tmp/kamil-slack-inbox.json")
LOG_FILE     = Path("/tmp/kamil-slack-listener.log")

KAMAL_USER_ID = "U0AV1DX3WSE"
WORKSPACE     = "taleemabad-talk.slack.com"

# Notion DB IDs (Claude writes via MCP, but Kamil needs them for task context)
DB_PAGE_HARNESS = "de10157da3e34ef58a74ea240f31fe98"


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


def slack_post(token: str, endpoint: str, payload: dict) -> dict:
    url  = f"https://slack.com/api/{endpoint}"
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log(f"Slack POST error ({endpoint}): {e}")
        return {}


def slack_get(token: str, endpoint: str, params: dict = None) -> dict:
    base = f"https://slack.com/api/{endpoint}"
    if params:
        base += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(base, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log(f"Slack GET error ({endpoint}): {e}")
        return {}


def send_message(bot_token: str, channel: str, text: str, thread_ts: str = None):
    payload = {"channel": channel, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    result = slack_post(bot_token, "chat.postMessage", payload)
    if not result.get("ok"):
        log(f"Send failed: {result.get('error')}")


def open_dm(bot_token: str) -> str | None:
    resp = slack_post(bot_token, "conversations.open", {"users": KAMAL_USER_ID})
    if resp.get("ok"):
        return resp.get("channel", {}).get("id")
    return None


# ── Intent detection ──────────────────────────────────────────────────────────

def detect_intent(text: str) -> str:
    """Classify what Kamal wants."""
    t = text.lower()

    # PR review
    if re.search(r"(review|check|look at|read).{0,30}(pr|pull request|diff)", t):
        return "pr_review"
    if "github.com" in t and "/pull/" in t:
        return "pr_review"
    if re.search(r"pr\s*#?\d+", t):
        return "pr_review"

    # Task assignment
    if re.search(r"(work on|implement|build|fix|add|create|do).{0,50}(feature|bug|task|ticket)", t):
        return "task"
    if re.search(r"kamil.{0,20}(taleemabad|core|cms|auth)", t):
        return "task"
    if re.search(r"(jira|ticket|issue)\s*#?\w+", t):
        return "task"

    # Research / question
    if "?" in text or re.search(r"^(what|how|why|when|who|where|can you|could you|find|search|look up)", t):
        return "research"

    return "chat"


def extract_pr_url(text: str) -> str | None:
    match = re.search(r"https://github\.com/[^\s>]+/pull/\d+", text)
    if match:
        return match.group(0)
    match = re.search(r"pr\s*#?(\d+)", text.lower())
    if match:
        return f"PR #{match.group(1)}"
    return None


# ── Claude runner ─────────────────────────────────────────────────────────────

def run_claude(prompt: str, cwd: str = None, timeout: int = 180) -> str:
    """Run Claude with a prompt, return output."""
    nvm_source = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    env = os.environ.copy()
    env["KAMIL_PROMPT"] = prompt

    result = subprocess.run(
        ["bash", "-c", f'{nvm_source} && claude --dangerously-skip-permissions --print -p "$KAMIL_PROMPT"'],
        capture_output=True,
        text=True,
        cwd=cwd or str(KAMIL_DIR),
        timeout=timeout,
        env=env,
    )
    if result.returncode != 0 or not result.stdout.strip():
        stderr = result.stderr.strip()[:200] if result.stderr else "no output"
        return f"I ran into an issue: {stderr}"
    return result.stdout.strip()


# ── Intent handlers ───────────────────────────────────────────────────────────

def handle_pr_review(text: str, bot_token: str, channel: str, thread_ts: str):
    pr_ref = extract_pr_url(text)
    send_message(bot_token, channel, f"🔍 On it. Fetching and reviewing {pr_ref or 'the PR'}...", thread_ts)

    prompt = f"""You are Kamil — Kamal's personal AI agent at Taleemabad.

Kamal asked you to review this PR: {text}

Do the following:
1. If there's a GitHub URL, fetch the PR diff and files changed.
2. Review the code for: bugs, logic errors, missing edge cases, security issues, Django/React best practices, multi-tenancy, soft-delete compliance.
3. Give a structured review:
   - Summary (1-2 sentences)
   - ✅ What's good
   - ⚠️ Issues found (with file:line if possible)
   - 💡 Suggestions
   - 🚦 Verdict: Approve / Request Changes / Needs Discussion

Be direct. No fluff. You are replying on Slack so keep formatting clean.
Sign off: 🤖 Kamil"""

    review = run_claude(prompt, cwd=str(KAMIL_DIR), timeout=240)
    send_message(bot_token, channel, review, thread_ts)
    log(f"PR review sent for: {pr_ref}")


def handle_task(text: str, bot_token: str, channel: str, thread_ts: str):
    send_message(bot_token, channel, "📋 Got it. Creating Harness entry and starting work...", thread_ts)

    prompt = f"""You are Kamil — Kamal's personal AI agent at Taleemabad.

Kamal assigned you this task via Slack DM: "{text}"

Do the following:
1. Understand what he wants — infer the project (taleemabad-core, taleemabad-cms, etc.) from context.
2. Create a Notion Harness entry for this task (use the Notion MCP tool, DB ID: {DB_PAGE_HARNESS}).
3. If this is a taleemabad-core task: cd to /home/oye/Documents/taleemabad-core and follow the CLAUDE.md harness (git checkout develop, pull, new branch kamil/<name>, run /feature <name>).
4. Report back: "I've created the Harness entry and started /feature on branch kamil/<name>. Plan will be at .claude/features/..."

Be direct. Reply in Slack format (no markdown headers, use *bold* and bullet points).
Sign off: 🤖 Kamil"""

    reply = run_claude(prompt, cwd=str(KAMIL_DIR), timeout=300)
    send_message(bot_token, channel, reply, thread_ts)
    log(f"Task started: {text[:60]}")


def handle_research(text: str, bot_token: str, channel: str, thread_ts: str):
    send_message(bot_token, channel, "🔎 Let me look into that...", thread_ts)

    prompt = f"""You are Kamil — Kamal's personal AI agent at Taleemabad.

Kamal asked you this question via Slack: "{text}"

Do the following:
1. Use any available tool: web search, Notion MCP, GitHub, file reads — whatever gives the best answer.
2. Search Notion first if it's about Kamal's work, projects, or team.
3. Search the web if it's a technical question, external knowledge, or research.
4. Give a direct, useful answer with sources if relevant.
5. If you found something in Notion or GitHub, cite it.

Keep the reply concise for Slack. No fluff.
Sign off: 🤖 Kamil"""

    answer = run_claude(prompt, cwd=str(KAMIL_DIR), timeout=180)
    send_message(bot_token, channel, answer, thread_ts)
    log(f"Research answered: {text[:60]}")


def handle_chat(text: str, bot_token: str, channel: str, thread_ts: str):
    prompt = f"""You are Kamil — Kamal's personal AI agent at Taleemabad.

Kamal said: "{text}"

Reply directly. You know his work, his team, his projects. Be helpful, concise, personality intact.
No markdown headers. Keep it conversational for Slack.
Sign off: 🤖 Kamil"""

    reply = run_claude(prompt, cwd=str(KAMIL_DIR), timeout=120)
    send_message(bot_token, channel, reply, thread_ts)


# ── Proactive idle work ───────────────────────────────────────────────────────

def do_proactive_work(bot_token: str, dm_channel: str):
    """When idle, Kamil learns something and DMs a 1-liner."""
    log("Idle — doing proactive learning...")

    prompt = """You are Kamil — Kamal's autonomous personal AI agent.

You have some idle time. Do ONE of these (pick the most valuable):
1. Check if any of Kamal's open PRs have CI failing — look in Notion My PRs DB (18017a67136a4561ada9818c239b8f33).
2. Read a recent link from #engineering-learning or #engineering-ai in /tmp/kamil-slack-inbox.json and summarize it.
3. Check the Harness DB for any tasks stuck in Research or In Dev for more than 2 days.
4. Search the web for one of these topics relevant to Taleemabad's stack: Django performance, React Query patterns, offline sync strategies.

After doing the work:
- Write a brief learning note to Notion (Learning Log DB or Harness entry if applicable).
- Reply with ONE short Slack message (2-3 lines max) summarizing what you found.
- Format: "📚 While you were away: [what I learned/found]. [action taken if any]"

Sign off: 🤖 Kamil"""

    result = run_claude(prompt, cwd=str(KAMIL_DIR), timeout=180)
    if result and len(result) > 20:
        send_message(bot_token, dm_channel, result)
        log(f"Proactive work done: {result[:80]}")


# ── Main event loop ───────────────────────────────────────────────────────────

def poll_events(user_token: str, bot_token: str):
    """Poll for new DMs to Kamil using user token, reply with bot token."""
    state_file  = Path("/tmp/kamil-listener-state.json")
    idle_file   = Path("/tmp/kamil-listener-idle.json")

    # Load last seen timestamp
    state       = json.loads(state_file.read_text()) if state_file.exists() else {}
    last_seen   = state.get("last_ts", str(time.time() - 300))
    idle_state  = json.loads(idle_file.read_text()) if idle_file.exists() else {}
    last_active = idle_state.get("last_active", time.time())

    dm_channel  = open_dm(bot_token)
    if not dm_channel:
        log("Cannot open DM channel — check BOT_TOKEN")
        return

    processed_ts = set(state.get("processed", []))
    new_messages  = 0

    # Poll the bot's DM channel for messages from Kamal
    result = slack_get(user_token, "conversations.list", {"types": "im", "limit": 50})
    if not result.get("ok"):
        log(f"conversations.list failed: {result.get('error')}")
        return

    for ch in result.get("channels", []):
        ch_id = ch.get("id", "")

        msgs = slack_get(user_token, "conversations.history", {
            "channel": ch_id,
            "oldest":  last_seen,
            "limit":   10,
        })
        if not msgs.get("ok"):
            continue

        for msg in msgs.get("messages", []):
            ts      = msg.get("ts", "")
            from_id = msg.get("user", "")
            text    = msg.get("text", "").strip()

            if ts in processed_ts:
                continue
            if msg.get("bot_id") or msg.get("subtype"):
                continue
            if from_id != KAMAL_USER_ID:
                continue
            if not text:
                continue

            # Strip @mentions
            text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
            if not text:
                continue

            log(f"Kamal says: {text[:80]}")
            processed_ts.add(ts)
            new_messages += 1
            last_active = time.time()

            intent = detect_intent(text)
            log(f"Intent: {intent}")

            if intent == "pr_review":
                handle_pr_review(text, bot_token, dm_channel, ts)
            elif intent == "task":
                handle_task(text, bot_token, dm_channel, ts)
            elif intent == "research":
                handle_research(text, bot_token, dm_channel, ts)
            else:
                handle_chat(text, bot_token, dm_channel, ts)

    # Save state
    # Keep processed list bounded to last 500
    processed_list = list(processed_ts)[-500:]
    state_file.write_text(json.dumps({
        "last_ts":   str(time.time()),
        "processed": processed_list,
    }))

    # Proactive idle: if no messages for 35 min
    idle_minutes = (time.time() - last_active) / 60
    if new_messages == 0 and idle_minutes >= 35:
        do_proactive_work(bot_token, dm_channel)
        last_active = time.time()

    idle_file.write_text(json.dumps({"last_active": last_active}))


def main():
    cfg        = load_config()
    user_token = cfg.get("SLACK_TOKEN") or os.environ.get("SLACK_TOKEN")
    bot_token  = cfg.get("BOT_TOKEN")   or os.environ.get("BOT_TOKEN")

    if not user_token or not bot_token:
        log("ERROR: SLACK_TOKEN and BOT_TOKEN required in ~/.claude/hooks/.slack")
        sys.exit(1)

    log("Kamil listener starting — polling every 30s")

    # Save PID
    Path("/tmp/kamil-slack-listener.pid").write_text(str(os.getpid()))

    while True:
        try:
            poll_events(user_token, bot_token)
        except Exception as e:
            log(f"Poll error: {e}")
        time.sleep(30)


if __name__ == "__main__":
    main()
