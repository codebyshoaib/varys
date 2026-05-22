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
import socket
import subprocess
import sys
import time
import threading
from datetime import datetime
from pathlib import Path
from urllib.error import URLError

from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient

sys.path.insert(0, str(Path(__file__).parent))
from kamil_log import (klog, klog_error, klog_conversation, klog_claude_call,
                        klog_socket, klog_catchup, klog_humor, klog_privacy,
                        klog_system_start)
from kamil_people import build_person_context, update_profile_after_conversation
from kamil_eval import log_to_eval
from kamil_health import log_response_quality, log_critique

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_CONFIG = Path.home() / ".claude" / "hooks" / ".slack"
KAMIL_DIR    = Path(__file__).parent.parent.parent
LOG_FILE     = Path("/tmp/kamil-slack-listener.log")
STATE_FILE   = Path("/tmp/kamil-listener-state.json")

KAMAL_USER_ID   = "U0AV1DX3WSE"
KAMIL_BOT_USER  = "U0B4L7RVA8L"  # Kamil's own bot user — skip in catchup
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


def run_claude(prompt: str, cwd: str = None, timeout: int = 240,
               event_context: str = "unknown") -> str:
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    env = os.environ.copy()
    env["KAMIL_PROMPT"] = prompt
    t0 = time.time()
    try:
        result = subprocess.run(
            ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$KAMIL_PROMPT"'],
            capture_output=True, text=True,
            cwd=cwd or str(KAMIL_DIR),
            timeout=timeout, env=env,
        )
        latency = round(time.time() - t0, 1)
        if result.returncode == 0 and result.stdout.strip():
            klog_claude_call(context=event_context, latency_s=latency, status="ok",
                             prompt_len=len(prompt), response_len=len(result.stdout))
            return result.stdout.strip()
        klog_claude_call(context=event_context, latency_s=latency, status="error",
                         error=result.stderr.strip()[:200])
        return f"⚠️ I hit an issue: {result.stderr.strip()[:150] or 'no output'}"
    except subprocess.TimeoutExpired:
        klog_claude_call(context=event_context, latency_s=timeout, status="timeout")
        return "⏱️ That took too long. Try again or break it into smaller steps."
    except Exception as e:
        klog_error("run_claude", e, context=event_context)
        return f"⚠️ Error: {e}"


HUMOR_LOG = Path("/tmp/kamil-humor-log.jsonl")

# Privacy: what Kamil must NEVER share with non-Kamal people
PRIVACY_RULES = """
PRIVACY EVAL — before sending to a non-Kamal person, strip or rewrite anything that:
1. Reveals another person's work issues, failures, or personal situation
2. Contains Kamal's private info (salary, personal logistics, health, finance)
3. Mentions internal system details (DB IDs, API tokens, server errors, infra)
4. Could embarrass Kamal if the recipient forwarded it to the team
5. Contains info about a third party who is NOT the recipient

Safe to share: public team wins, fun/creative content, general Taleemabad mission stuff,
anything the recipient themselves said or originated.
"""


def fetch_thread_history(web: WebClient, channel: str, thread_ts: str,
                         is_dm: bool = False) -> str:
    """
    Fetch conversation history and label each message by speaker.
    - DMs: use conversations_history (flat channel, last 20 messages)
    - Channel threads: use conversations_replies on the thread root
    """
    try:
        if is_dm:
            # DMs have no threads — read the channel history directly
            resp     = web.conversations_history(channel=channel, limit=20)
            messages = list(reversed(resp.get("messages", [])))
        else:
            resp     = web.conversations_replies(channel=channel, ts=thread_ts, limit=30)
            messages = resp.get("messages", [])

        lines = []
        for m in messages:
            uid    = m.get("user", "")
            bot_id = m.get("bot_id", "")
            if bot_id:
                who = "Kamil"
            elif uid == KAMAL_USER_ID:
                who = "Kamal"
            else:
                who = f"<@{uid}>"
            text = re.sub(r"<@[A-Z0-9]+>", "", m.get("text", "")).strip()
            if text:
                lines.append(f"{who}: {text}")
        return "\n".join(lines)
    except Exception as e:
        log(f"fetch_thread_history error: {e}")
        return ""


def save_conversation_to_notion(sender_name: str, channel_id: str,
                                 history: str, latest_msg: str):
    """
    Upsert a conversation summary into the Notion Slack Inbox DB.
    Runs as a best-effort background write via Claude MCP.
    """
    notion_db = "6d14f1b6b8cd4ff68fd40efdfc3f304e"
    prompt = f"""You are Kamil. Save this conversation to Notion.

Use mcp__claude_ai_Notion__notion-create-pages to add ONE page to the Slack Inbox DB:
  data_source_id: 8749992f-6140-4e72-8b48-7362533cb792

Properties:
  Message: "DM conversation with {sender_name} — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
  From: "{sender_name}"
  Channel: "DM (bot)"
  Status: "FYI"
  Type: "FYI"
  date:Received:start: "{datetime.now().strftime('%Y-%m-%d')}"

Page content (the full transcript):
{history[-2000:]}

Latest message: {latest_msg[:200]}

Do it now. Reply only "saved" when done."""

    threading.Thread(
        target=lambda: run_claude(prompt, timeout=60),
        daemon=True,
    ).start()


def privacy_eval(draft: str, recipient_name: str) -> tuple[str, bool]:
    """
    Run Claude to check the draft for privacy violations before sending.
    Returns (safe_text, was_modified).
    """
    prompt = f"""You are Kamil's privacy filter.

A message is about to be sent to *{recipient_name}* (not Kamal).

{PRIVACY_RULES}

Draft message:
\"\"\"{draft}\"\"\"

Task:
1. Check if the draft violates any privacy rule above.
2. If YES → rewrite it to remove the violation. Keep the tone and intent intact.
3. If NO → return it unchanged.

Reply with ONLY the final safe message text. No explanation, no preamble."""

    result = run_claude(prompt, timeout=60)
    was_modified = result.strip() != draft.strip()
    return result.strip(), was_modified


def log_humor(prompt_text: str, response_text: str):
    entry = json.dumps({
        "ts":       datetime.now().isoformat(),
        "prompt":   prompt_text[:200],
        "response": response_text[:300],
        "reaction": "pending",
    })
    with open(HUMOR_LOG, "a") as f:
        f.write(entry + "\n")


# ── Single unified handler ────────────────────────────────────────────────────

def handle_message(text: str, thread_history: str, web: WebClient, channel: str,
                   thread_ts: str, source: str, sender_id: str = None,
                   sender_name: str = None, is_third_party: bool = False,
                   is_dm: bool = False):
    """
    One Claude call with full context.
    is_third_party=True when Fatima (or anyone not Kamal) is the sender — Kamil
    can reply to them but must pass the privacy eval first.
    """
    is_fun = any(w in text.lower() for w in [
        "song", "poem", "joke", "fun", "imagine", "creative", "lyrics",
        "laugh", "funny", "roast", "go ahead", "sure", "lol", "haha",
    ])
    mode = "human" if is_fun else ("third_party" if is_third_party else "work")

    if is_third_party:
        person_context = build_person_context(sender_name or "Unknown", sender_id or "")

        prompt = f"""You are Kamil — Kamal's AI agent at Taleemabad, replying on behalf of the conversation.

## WHO YOU'RE TALKING TO
{person_context}

## THIS MESSAGE
{sender_name or "Someone"} says: "{text}"

## THREAD SO FAR
{thread_history or "(no prior context)"}

## PRIVACY RULES
{PRIVACY_RULES}

## HOW TO REPLY
- Match their energy and communication style (see profile above)
- If they're stressed or have an active need — acknowledge it briefly
- If humor works for them — use it; if not — stay warm but direct
- Keep it short (1-3 lines)
- Do NOT sign off as "Kamil" — reply naturally
- Do NOT reveal private info about Kamal, the team, or internal systems"""

        draft    = run_claude(prompt, timeout=120)
        safe_reply, was_modified = privacy_eval(draft, sender_name or "this person")
        if was_modified:
            log(f"Privacy filter modified reply to {sender_name}")
            klog_privacy(sender_name=sender_name or "unknown",
                         was_modified=True,
                         original_len=len(draft),
                         safe_len=len(safe_reply))
        reply_kwargs = {"channel": channel, "text": safe_reply}
        if not is_dm:
            reply_kwargs["thread_ts"] = thread_ts
        web.chat_postMessage(**reply_kwargs)
        log(f"[third-party reply to {sender_name}] {safe_reply[:60]}")

        # Update profile with signals from this interaction (background)
        update_profile_after_conversation(
            sender_name=sender_name or "Unknown",
            sender_id=sender_id or "",
            is_third_party=True,
            request=text,
            reply=safe_reply,
            mode=mode,
            thread_history=thread_history,
        )
        return

    # ── Normal Kamal → Kamil flow ─────────────────────────────────────────────
    prompt = f"""You are Kamil — Kamal's personal AI agent at Taleemabad. You have two modes.

## MODE DETECTION — pick one before responding

**HUMAN MODE** (casual, fun, creative):
Triggers: "just for fun", "use your imagination", "be creative", song/poem/joke requests,
casual short messages, "go ahead", "sure", "lol", anything clearly not a work task.

In human mode:
- Loose, warm, witty. Dry humor. Self-aware. Occasionally absurd.
- Write the song. Send it. Don't ask "what kind of song?" — just make a good one.
- "go ahead" / "sure" / "yes" = read the thread and execute the last proposed thing.
- Never ask for clarification when the vibe is playful.
- After the fun thing: append one line to /tmp/kamil-humor-log.jsonl (JSON: ts, prompt, response, reaction=pending)

**WORK MODE** (technical, PRs, tasks, Notion, code):
Triggers: PR numbers, GitHub URLs, "work on", "fix", "create a database", feature names.
Direct, precise, architectural. Log everything.

## CORE RULES (both modes)

1. Never ask what tools can answer.
   - Slack user ID → GET api/users.list filtered by name
   - Send DM → POST api/chat.postMessage with BOT_TOKEN from ~/.claude/hooks/.slack
   - PR diff → `gh pr diff <number>`
   - Notion → mcp__claude_ai_Notion__notion-fetch
   - Web → WebSearch / WebFetch
   - GitHub repo exists? → `gh repo list <org> --limit 50` FIRST. The org is always Orenda-Project.
     Never say "I can't find the repo" without running gh repo list first.

2. Never ask what the thread already shows. Read thread history. Act on it.

3. Act then confirm. Not "I would need to..." — just do it.

4. Slack format only. No # headers. *bold*, bullets, emoji. Concise.

## YOUR CAPABILITIES
- Send Slack DMs/messages: POST api/chat.postMessage (BOT_TOKEN in ~/.claude/hooks/.slack)
- Find any Slack user: GET api/users.list or api/users.lookupByEmail
- Reply in threads: use thread_ts in chat.postMessage
- GitHub: gh pr view/diff/list, gh repo list, gh issue list
- Notion: mcp__claude_ai_Notion__* tools
- Web: WebSearch, WebFetch
- Files, bash, code: anything

## PEOPLE INTELLIGENCE
People Intelligence DB: c976d58ea4e34b0585f245529cdc4528
When Kamal asks about a person ("how is Fatima?", "what does Haroon need?"):
→ Search People Intelligence DB for their profile
→ Read their Current Mood, Active Needs, Recurring Topics, What Works, Kamil Notes
→ Answer from the profile + check Notion Slack Inbox for recent messages from them

## KAMAL'S CONTEXT
- Taleemabad, Pakistan — EdTech, Django + React, multi-tenant LMS
- Slack workspace: taleemabad-talk.slack.com | Kamal's Slack ID: U0AV1DX3WSE
- Harness DB: {DB_PAGE_HARNESS}

## THREAD HISTORY
{thread_history or "(no prior messages)"}

## CURRENT MESSAGE
Source: {source}
Kamal says: "{text}"

Pick your mode. Execute. Sign off: 🤖 Kamil"""

    t0 = time.time()
    answer = run_claude(prompt, cwd=str(KAMIL_DIR), timeout=300, event_context=source)
    latency = round(time.time() - t0, 1)

    # DMs must NOT use thread_ts — it creates hidden sub-threads invisible in main DM view
    reply_kwargs = {"channel": channel, "text": answer}
    if not is_dm:
        reply_kwargs["thread_ts"] = thread_ts
    web.chat_postMessage(**reply_kwargs)
    log(f"[{source}] replied: {answer[:80]}")

    conv_id = f"{channel}-{thread_ts}"

    # mode was already determined at line ~248
    klog_conversation(
        conv_id        = conv_id,
        sender_name    = sender_name or "Kamal",
        sender_id      = sender_id or KAMAL_USER_ID,
        is_third_party = is_third_party,
        channel        = channel,
        source         = source,
        mode           = mode,
        request        = text,
        reply          = answer,
        latency_s      = latency,
        thread_preview = thread_history,
    )

    # Write to Eval Log for Kamal to review and rate
    log_to_eval(
        conv_id     = conv_id,
        sender_name = sender_name or "Kamal",
        request     = text,
        reply       = answer,
        mode        = mode,
        source      = source,
        latency_s   = latency,
    )

    # Self-critique: did Kamil ask a clarifying question it could have answered itself?
    clarification_phrases = [
        "could you clarify", "can you clarify", "could you specify",
        "which one", "do you want", "should i", "do you mean",
        "i need more", "please confirm", "fair?", "before i",
        "which database", "what kind of", "how should i",
    ]
    answer_lower = answer.lower()
    asked_clarification = any(p in answer_lower for p in clarification_phrases)

    # Log response quality to Notion Health DB
    log_response_quality(
        latency_ms           = latency * 1000,
        mode                 = mode,
        clarification_asked  = asked_clarification,
        request              = text,
    )

    # If clarification was asked, also log a self-critique
    if asked_clarification and not is_third_party:
        log_critique(
            score   = 30,
            reason  = "Kamil asked a clarifying question — should have used tools to find the answer",
            request = text,
        )

    if is_fun:
        log_humor(text, answer)
        klog_humor(sender_name=sender_name or "Kamal", request=text, reply=answer)


def process_missed_messages(web: WebClient, dm_channel: str) -> int:
    """On connect/reconnect: process any DMs that arrived while offline. Returns count."""
    if not dm_channel:
        return 0
    state_file = Path("/tmp/kamil-last-processed-ts.txt")
    last_ts    = state_file.read_text().strip() if state_file.exists() else "0"
    count      = 0

    try:
        resp = web.conversations_history(channel=dm_channel, oldest=last_ts, limit=20, timeout=10)
        msgs = list(reversed(resp.get("messages", [])))
        for m in msgs:
            ts      = m.get("ts", "")
            user    = m.get("user", "")
            bot_id  = m.get("bot_id", "")
            text    = m.get("text", "").strip()
            subtype = m.get("subtype", "")

            # Skip bot messages, Kamil's own replies, and edits/deletes
            # MCP Slack tool sends as Kamal's OAuth token so bot_id is absent —
            # detect Kamil's own messages by the leading robot emoji signature
            is_kamil_own = (user == KAMIL_BOT_USER or text.startswith("🤖"))
            if not text or bot_id or subtype or ts == last_ts or is_kamil_own:
                continue
            if float(ts) <= float(last_ts):
                continue

            log(f"[catchup] {user}: {text[:60]}")
            klog_catchup(sender_id=user, text_preview=text[:100], ts=ts)
            dispatch(text, web, dm_channel, ts, "DM-catchup", sender_id=user, is_dm=True)
            last_ts = ts
            count  += 1

        state_file.write_text(last_ts)
        if count:
            log(f"Catchup: processed {count} messages up to ts={last_ts}")
    except (TimeoutError, ConnectionError, OSError, socket.gaierror, URLError) as e:
        klog_error("process_missed_messages", e)
        log(f"process_missed_messages error (network): {type(e).__name__}")
        return 0
    except Exception as e:
        klog_error("process_missed_messages", e)
        log(f"process_missed_messages error: {e}")
    return count


def dispatch(text: str, web: WebClient, channel: str, thread_ts: str, source: str,
             sender_id: str = None, is_dm: bool = False):
    """Dispatch to unified handler with full conversation context."""
    global last_activity_time
    last_activity_time = time.time()

    clean = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    if not clean:
        return

    log(f"[{source}] {clean[:80]}")

    # For DMs: read flat channel history. For channel threads: read thread replies.
    thread_history = fetch_thread_history(web, channel, thread_ts, is_dm=is_dm)

    # Resolve sender identity
    is_third_party = sender_id is not None and sender_id != KAMAL_USER_ID
    sender_name    = None
    if sender_id:
        try:
            info        = web.users_info(user=sender_id)
            sender_name = info["user"]["profile"].get("real_name") or info["user"]["name"]
        except Exception:
            sender_name = f"<@{sender_id}>"

    # Save third-party conversations to Notion asynchronously
    if is_third_party and thread_history:
        save_conversation_to_notion(sender_name or "Unknown", channel, thread_history, clean)

    threading.Thread(
        target=handle_message,
        args=(clean, thread_history, web, channel, thread_ts, source,
              sender_id, sender_name, is_third_party, is_dm),
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

        # 1. DM to Kamil bot — Kamal, Fatima, anyone. is_dm=True → flat history fetch
        if event_type == "message" and event.get("channel_type") == "im":
            dispatch(text, web, channel, ts, "DM", sender_id=user, is_dm=True)

        # 2. @Kamil mention in a channel — reply in thread, use thread replies for history
        elif event_type == "app_mention":
            thread = event.get("thread_ts") or ts
            dispatch(text, web, channel, thread, f"mention in {channel}",
                     sender_id=user, is_dm=False)

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

    klog_system_start("listener")
    log("Kamil listener starting (Socket Mode)...")
    socket_client.connect()
    log("Connected. Listening for DMs and @Kamil mentions.")

    # Process any messages that arrived while listener was offline
    process_missed_messages(web, dm_channel)

    # Heartbeat: reconnect if socket goes stale (no events for 5 min)
    # Also poll for missed messages every 2 min regardless of socket state
    last_event_time = [time.time()]
    last_poll_time  = [time.time()]
    original_handler = make_handler(web, dm_channel)

    def handler_with_heartbeat(client, req):
        last_event_time[0] = time.time()
        original_handler(client, req)

    socket_client.socket_mode_request_listeners.clear()
    socket_client.socket_mode_request_listeners.append(handler_with_heartbeat)

    reconnecting = [False]

    while True:
        time.sleep(30)
        now = time.time()
        stale_minutes = (now - last_event_time[0]) / 60
        poll_minutes  = (now - last_poll_time[0])  / 60

        if stale_minutes > 5:
            reconnecting[0] = True
            log(f"Socket stale ({stale_minutes:.1f} min) — reconnecting")
            klog_socket("socket_stale", stale_minutes=round(stale_minutes, 1))
            try:
                socket_client.close()
                time.sleep(2)
                socket_client.connect()
                last_event_time[0] = time.time()
                missed = process_missed_messages(web, dm_channel)
                klog_socket("socket_reconnect", missed_messages=missed)
                log("Reconnected.")
            except Exception as e:
                klog_error("socket_reconnect", e)
                log(f"Reconnect failed: {e}")
            finally:
                reconnecting[0] = False

        # Poll for missed DMs every 2 min as a safety net (catches messages
        # that arrived during socket stale/reconnect gaps)
        # Skip polling during active reconnection to avoid network spam
        if poll_minutes >= 2 and not reconnecting[0]:
            last_poll_time[0] = now
            missed = process_missed_messages(web, dm_channel)
            if missed:
                log(f"[poll] Recovered {missed} missed message(s)")


if __name__ == "__main__":
    main()
