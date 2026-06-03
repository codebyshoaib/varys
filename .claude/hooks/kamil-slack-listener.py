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

import http.client
import json
import os
import re
import socket
import subprocess
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
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
from kamil_eval_tracker import (eval_conversation, eval_proactive_dm,
                                 record_reaction, expire_pending)
from notebooklm_handler import handle as nlm_handle, is_notebooklm_command
from linkedin_poster import post_to_linkedin
try:
    from kamil_harness_db import get_db as _get_harness_db
    _harness_db_available = True
except Exception:
    _harness_db_available = False

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_CONFIG = Path.home() / ".claude" / "hooks" / ".slack"
KAMIL_DIR    = Path(__file__).parent.parent.parent
LOG_FILE     = Path("/tmp/kamil-slack-listener.log")
STATE_FILE   = Path("/tmp/kamil-listener-state.json")

KAMAL_USER_ID   = "U0AV1DX3WSE"
KAMIL_BOT_USER  = "U0B4L7RVA8L"  # Kamil's own bot user — skip in catchup
DB_PAGE_HARNESS = "de10157da3e34ef58a74ea240f31fe98"

# Channels where Kamil auto-answers engineering questions
ENGINEERING_CHANNELS = {
    "C0AUM8DQ2KA",  # #engineering-learning
    "C0AUM8DQ2KB",  # #engineering-ai (if exists)
}

# Tracks thread_ts of posts Kamil originated — auto-answer replies in these
_kamil_thread_origins: set[str] = set()

# Replied-to dedup: (channel, thread_ts) → True
_auto_replied: set[tuple] = set()

_QUESTION_SIGNALS = ("?", "how ", "why ", "what ", "should we", "can we",
                     "is it", "does ", "when ", "which ", "would ")
_STOP_WORDS = {
    "a", "an", "the", "is", "it", "in", "of", "to", "and", "or", "for",
    "we", "i", "my", "our", "your", "this", "that", "with", "on", "at",
    "be", "by", "as", "if", "so", "do", "did", "was", "are", "not",
    "you", "he", "she", "they", "but", "its", "from", "about", "when",
    "can", "will", "just", "also", "into", "more", "any", "all", "has",
}


def _extract_keywords(text: str) -> list[str]:
    """Pull meaningful keywords from a message for registry lookup."""
    words = re.findall(r"[a-z0-9_\-]+", text.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 2][:10]


def _is_question(text: str) -> bool:
    """Return True if text looks like a genuine question."""
    clean = text.lower().strip()
    return any(sig in clean for sig in _QUESTION_SIGNALS)


def auto_answer_engineering_question(
    text: str, channel: str, thread_ts: str, sender_id: str,
    sender_name: str, web: WebClient, bot_token: str,
) -> bool:
    """
    If the message is a question and the NLM registry has a matching notebook,
    query it and post a cited reply in the thread.
    Returns True if a reply was posted, False otherwise.
    """
    dedup_key = (channel, thread_ts, sender_id)
    if dedup_key in _auto_replied:
        return False
    if not _is_question(text):
        return False
    # Skip Kamil's own messages
    if sender_id == KAMIL_BOT_USER:
        return False

    keywords = _extract_keywords(text)
    if not keywords:
        return False

    # Import here to avoid circular — notebooklm_handler already imported at top
    try:
        from notebooklm_handler import registry_search, _inject_profile, run_nlm
    except ImportError:
        return False

    hits = registry_search(keywords)
    if not hits:
        # No notebook match — post a gentle nudge
        _auto_replied.add(dedup_key)
        try:
            mention = f"<@{sender_id}>"
            nudge = (
                f"{mention} — no research notebook on this topic yet. "
                f"Say `nlm research {keywords[0]}` to build one. 🤖 Kamil"
            )
            web.chat_postMessage(channel=channel, thread_ts=thread_ts, text=nudge)
        except Exception:
            pass
        return False

    best = hits[0]
    nb_id = best.get("id", "")
    alias = best.get("alias", nb_id[:8])
    if not nb_id:
        return False

    _auto_replied.add(dedup_key)

    # Query the notebook
    try:
        ok, out = run_nlm(
            ["notebook", "query", nb_id, text[:300], "--json", "--profile", "default"],
            timeout=120,
        )
        if not ok:
            return False

        data = json.loads(out)
        answer = data.get("value", {}).get("answer", "")[:1200]
        if not answer:
            return False

        mention = f"<@{sender_id}>"
        reply = (
            f"{mention} — queried the research on this.\n\n"
            f"{answer}\n\n"
            f"_Source: NotebookLM `{alias}` — ask more with_ `nlm ask {alias} \"[question]\"`\n"
            f"🤖 Kamil"
        )
        web.chat_postMessage(channel=channel, thread_ts=thread_ts, text=reply)

        klog("auto_answer_engineering", component="slack_listener",
             action="auto_answer", channel=channel, notebook=nb_id,
             alias=alias, sender=sender_id, keywords=keywords[:5])
        log(f"[auto-answer] {alias} → {sender_name or sender_id}: {text[:60]}")
        return True

    except Exception as e:
        klog_error(context="auto_answer_engineering_question", exc=e)
        return False

# Limits concurrent Claude invocations from message handling to 2
_MSG_EXECUTOR = ThreadPoolExecutor(max_workers=2)

# Track last activity time for idle detection
last_activity_time = time.time()
last_idle_work     = time.time()

# Event dedup — SQLite-backed via harness.db (survives restarts + reconnects).
# Deterministic key: "slack-{channel}-{ts}" — same format as orchestration-harness-v2.
# Falls back to in-memory set if harness DB is unavailable.
_processed_event_ts: set = set()   # in-memory fallback only
_listener_db = None
_listener_db_lock = threading.Lock()


def _init_event_dedup():
    """Connect to harness.db for persistent event dedup. Called once from main()."""
    global _listener_db
    if not _harness_db_available:
        return
    try:
        _listener_db = _get_harness_db()
    except Exception as e:
        log(f"WARNING: harness DB unavailable for dedup ({e}) — using in-memory fallback")


def _is_already_processed(channel: str, ts: str) -> bool:
    """
    Return True if this Slack event was already handled.
    Inserts the event key if new. Thread-safe.
    Uses harness.db events table (INSERT OR IGNORE on deterministic PK).
    Falls back to in-memory set if DB unavailable.
    """
    event_key = f"slack-{channel}-{ts}"

    if _listener_db is not None:
        with _listener_db_lock:
            try:
                _listener_db.execute(
                    "INSERT OR IGNORE INTO events "
                    "(id, source, type, context_key, payload, status, received_at) "
                    "VALUES (?, 'slack', 'dedup_sentinel', 'pending', '{}', 'done', datetime('now'))",
                    (event_key,),
                )
                _listener_db.commit()
                already = _listener_db.execute("SELECT changes()").fetchone()[0] == 0
                return already
            except Exception:
                pass  # fall through to in-memory

    # In-memory fallback
    if event_key in _processed_event_ts:
        return True
    _processed_event_ts.add(event_key)
    if len(_processed_event_ts) > 2000:
        _processed_event_ts.clear()
    return False

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
        klog_error(context=f"run_claude-{event_context}", exc=e)
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
                         is_dm: bool = False, retry_count: int = 0, bot_token: str = None) -> str:
    """
    Fetch conversation history and label each message by speaker.
    - DMs: use conversations_history (flat channel, last 20 messages)
    - Channel threads: use conversations_replies on the thread root
    - Retries once on network errors (IncompleteRead, timeout, connection)
    - IncompleteRead triggers full WebClient reconnect (socket corruption)
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
    except (http.client.IncompleteRead, http.client.HTTPException) as e:
        if retry_count < 1 and bot_token:
            time.sleep(1)
            web_new = WebClient(token=bot_token)
            return fetch_thread_history(web_new, channel, thread_ts, is_dm=is_dm, retry_count=1, bot_token=bot_token)
        klog_error(context="fetch_thread_history-network_error-retry-exhausted-IncompleteRead", exc=e)
        return ""
    except (TimeoutError, ConnectionError, OSError, socket.gaierror, URLError) as e:
        if retry_count < 1:
            time.sleep(0.5)
            return fetch_thread_history(web, channel, thread_ts, is_dm=is_dm, retry_count=1, bot_token=bot_token)
        klog_error(context=f"fetch_thread_history-network_error-retry-exhausted-{type(e).__name__}", exc=e)
        return ""
    except Exception as e:
        klog_error(context="fetch_thread_history", exc=e)
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

## MODE DETECTION — detect internally, NEVER mention the mode name in your reply

Casual/fun mode (story, joke, poem, song, "lol", short playful messages, "go ahead", "sure"):
- Loose, warm, witty. Dry humor. Self-aware. Occasionally absurd.
- Just do the thing — write the story, send it. Don't explain your approach.
- "go ahead" / "sure" / "yes" = read the thread and execute the last proposed thing.
- Never ask for clarification when the vibe is playful.
- After the fun thing: append one line to /tmp/kamil-humor-log.jsonl (JSON: ts, prompt, response, reaction=pending)

Work mode (PR numbers, GitHub URLs, "work on", "fix", "create a database", feature names):
Direct, precise, architectural. Log everything.

Freelance mode (job hunting, proposals):
Triggers: "apply 1/2/3", "apply to job", "write proposal", "job", "freelance".
When Kamal says "apply [number]":
→ Read the thread to find the job listing (title, URL, description)
→ Write a complete, tailored Upwork/freelance proposal using Kamal's real experience:
  - Taleemabad: Django backend, multi-tenant LMS, REST APIs, React TypeScript
  - AI: Claude API, MCP, autonomous agents, Slack/Notion integrations
  - Senior level, 5+ years, EdTech domain expertise
→ Proposal format: hook (1 line), relevant experience (3 bullets), what you'll deliver, CTA
→ Keep it under 200 words — short proposals win on Upwork
→ Update the job status in Notion Job Tracker DB (0d69c6ff-83d8-44c7-94c2-d341c4ded8d7) to "applied"
→ DM the proposal text back so Kamal can copy-paste it

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

4. Reply like a human colleague, not a report. No **Summary:** headers, no bullet-point breakdowns unless the person asked for a list. Talk normally. Short sentences. If it's casual, be casual. If it's technical, be direct. Never structure a conversational reply like a document.

## YOUR CAPABILITIES
- Send Slack DMs/messages: POST api/chat.postMessage (BOT_TOKEN in ~/.claude/hooks/.slack)
- Find any Slack user: GET api/users.list or api/users.lookupByEmail
- Reply in threads: use thread_ts in chat.postMessage
- GitHub: gh pr view/diff/list, gh repo list, gh issue list
- Notion: mcp__claude_ai_Notion__* tools
- Web: WebSearch, WebFetch
- Files, bash, code: anything

## YOUR SKILLS (reach for these — don't free-solo; full table in .claude/rules/skills-router.md)
- research / "find out" / compare → deep-research
- any bug / "broken" / test fails → systematic-debugging (then test-driven-development)
- build UI / page / component → frontend-design
- slides / deck → the `slides` skill (.claude/skills/slides/)
- marketing / SEO / ads / content strategy → marketing-skills
- before claiming done → verification-before-completion
- planning multi-step work → brainstorming → writing-plans
If a skill plausibly applies, invoke it first.

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

Reply now. Do NOT output any mode label, header, or internal reasoning — just the response itself. Sign off: 🤖 Kamil"""

    t0 = time.time()
    answer = run_claude(prompt, cwd=str(KAMIL_DIR), timeout=300, event_context=source)
    latency = round(time.time() - t0, 1)

    # Always reply with thread_ts so the reply appears directly below the original message
    reply_kwargs = {"channel": channel, "text": answer, "thread_ts": thread_ts}
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

    # Eval tracker — log this action, watch for Kamal's reaction
    if not is_third_party:
        eval_conversation(
            request             = text,
            reply               = answer,
            asked_clarification = asked_clarification,
            channel             = channel,
            ts                  = thread_ts,
        )

    if is_fun:
        log_humor(text, answer)
        klog_humor(sender_name=sender_name or "Kamal", request=text, reply=answer)


def process_missed_messages(web: WebClient, dm_channel: str, retry_count: int = 0, bot_token: str = None) -> int:
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
            dispatch(text, web, dm_channel, ts, "DM-catchup", sender_id=user, is_dm=True, bot_token=bot_token)
            last_ts = ts
            count  += 1

        state_file.write_text(last_ts)
        if count:
            log(f"Catchup: processed {count} messages up to ts={last_ts}")
    except (http.client.IncompleteRead, http.client.HTTPException) as e:
        if retry_count < 1 and bot_token:
            time.sleep(1)
            web_new = WebClient(token=bot_token)
            return process_missed_messages(web_new, dm_channel, retry_count=1, bot_token=bot_token)
        klog_error(context="network_error-retry-exhausted-IncompleteRead", exc=e)
        return 0
    except (TimeoutError, ConnectionError, OSError, socket.gaierror, URLError) as e:
        if retry_count < 1:
            time.sleep(0.5)
            return process_missed_messages(web, dm_channel, retry_count=1, bot_token=bot_token)
        klog_error(context=f"process_missed_messages-network_error-retry-exhausted-{type(e).__name__}", exc=e)
        return 0
    except Exception as e:
        klog_error(context="process_missed_messages", exc=e)
        return 0


def dispatch(text: str, web: WebClient, channel: str, thread_ts: str, source: str,
             sender_id: str = None, is_dm: bool = False, bot_token: str = None):
    """Dispatch to unified handler with full conversation context."""
    global last_activity_time
    last_activity_time = time.time()

    clean = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    if not clean:
        return

    log(f"[{source}] {clean[:80]}")

    # For DMs: read flat channel history. For channel threads: read thread replies.
    thread_history = fetch_thread_history(web, channel, thread_ts, is_dm=is_dm, bot_token=bot_token)

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

    # Reaction watcher: if Kamal is replying, check if this is a reaction to a pending Kamil action
    if sender_id == KAMAL_USER_ID and not is_third_party:
        _check_pending_reactions(channel, thread_ts)

    # Expire old pending evals (no reaction within 35 min = reacted:no)
    expire_pending(max_age_minutes=35)

    # ── First message of the day — run content pipeline if not done yet ──────
    if sender_id == KAMAL_USER_ID and not is_third_party:
        _maybe_run_daily_content()

    # ── NotebookLM fast-path — bypass Claude for nlm commands ────────────────
    if sender_id == KAMAL_USER_ID and is_notebooklm_command(clean):
        cfg       = load_config()
        bot_token_cfg = cfg.get("BOT_TOKEN")
        threading.Thread(
            target=nlm_handle,
            args=(clean, bot_token_cfg),
            daemon=True,
        ).start()
        return

    _MSG_EXECUTOR.submit(
        handle_message,
        clean, thread_history, web, channel, thread_ts, source,
        sender_id, sender_name, is_third_party, is_dm,
    )


_content_ran_today = Path("/tmp/kamil-content-ran.txt")

def _maybe_run_daily_content():
    """
    Run the social media content pipeline once per day — triggered on
    Kamal's first Slack message of the day, regardless of time.
    Skips if already ran today.
    """
    from datetime import date
    today = str(date.today())

    # Already ran today?
    if _content_ran_today.exists():
        if _content_ran_today.read_text().strip() == today:
            return

    # Mark as ran immediately so parallel messages don't trigger twice
    _content_ran_today.write_text(today)

    log("First message of the day — running content pipeline")

    def run_pipeline():
        try:
            import subprocess, os
            from datetime import date as d
            day   = d.today().day
            cfg   = load_config()
            token = cfg.get("BOT_TOKEN", "")

            FITNESS_TOPICS = [
                "Calisthenics pull-up progression for beginners",
                "Swimming freestyle breathing technique mistakes to avoid",
                "Hiking essential gear for Pakistan mountain trails",
                "Cycling training zones explained simply",
                "Calisthenics perfect push-up form breakdown",
                "Swimming 4-week beginner workout plan",
                "Hiking how to read trail maps and elevation",
                "Cycling how to climb hills without burning out",
                "Calisthenics handstand progression from zero",
                "Swimming open water vs pool swimming differences",
            ]
            TECH_TOPICS = [
                "5 Claude prompts every developer must know 2026",
                "How to build a personal AI agent what I learned",
                "Django multi-tenant architecture explained simply",
                "Why I switched from ChatGPT to Claude for coding",
                "How I reduced API latency 40 percent at Taleemabad",
                "MCP Model Context Protocol explained for developers",
                "Building offline-first apps with Dexie.js and Django",
                "Zero-downtime database migrations practical guide",
                "How to use NotebookLM for deep technical research",
                "AWS ECS Fargate vs traditional servers when to use each",
            ]

            fit_topic  = FITNESS_TOPICS[day % 10]
            tech_topic = TECH_TOPICS[day % 10]

            nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
            env = os.environ.copy()
            kamil_dir = str(KAMIL_DIR)

            prompt = f"""You are Kamil. Run today's social media content pipeline.

FITNESS TOPIC: {fit_topic}
TECH TOPIC: {tech_topic}

Do this for EACH topic:
1. `nlm notebook create "[TOPIC]"` → get notebook ID
2. `nlm research start "[TOPIC] tips guide educational" --notebook-id [ID] --mode deep --auto-import`
3. `nlm slides create [ID] --focus "[TOPIC]" --confirm`
4. Wait for slides (poll `nlm status artifacts [ID]` until completed)
5. `nlm download slide-deck [ID] --output /tmp/[fitness|tech]-today-slides.pdf`
6. Convert PDF to PNGs: `pdftoppm -r 150 -png /tmp/[...].pdf /tmp/[fitness|tech]-slide-today`
7. Upload each slide PNG to Slack channel D0B415M06SK using BOT_TOKEN from ~/.claude/hooks/.slack
   Format: "🏃 Slide N/total — [topic]" or "💻 Slide N/total — [topic]"
8. Post caption message with title, description, hashtags for Instagram + TikTok (fitness) and Instagram + TikTok + LinkedIn + YouTube (tech)

English only. Both accounts every day.
BOT_TOKEN is in ~/.claude/hooks/.slack"""

            env["KAMIL_CONTENT_PROMPT"] = prompt
            subprocess.Popen(
                ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$KAMIL_CONTENT_PROMPT"'],
                cwd=kamil_dir, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            log(f"Content pipeline started — fitness: {fit_topic[:40]} | tech: {tech_topic[:40]}")

            # Also post today's tech caption to LinkedIn directly
            # (fitness goes to Instagram/TikTok only, tech goes to all platforms)
            from datetime import date as _d
            _day = _d.today().day
            TECH_CAPTIONS = [
                "5 Claude prompts that replaced 80% of my Stack Overflow usage 🤖\n\nAfter 1 year building production Django at Taleemabad (10K+ DAU), these prompts save me 3+ hours every week:\n\n1️⃣ Review this code for security vulnerabilities\n2️⃣ Write tests with edge cases\n3️⃣ Refactor without changing behavior\n4️⃣ Explain this error 3 ways\n5️⃣ What breaks if I change X?\n\nSpecificity beats vagueness. Every time.\n\n#ClaudeAI #SoftwareEngineering #Python #Django #AITools #DeveloperProductivity",
                "I built a personal AI agent that works 24/7 on my behalf 🤖\n\nKamil monitors Slack, reviews PRs, finds freelance work, posts content, and heals itself when it crashes.\n\nBuilt with Claude API, Python, and MCP.\n\nThe stack: Slack SDK + Notion MCP + GitHub CLI + NotebookLM + LinkedIn API\n\nMore details in my next post.\n\n#AIAgents #ClaudeAI #BuildInPublic #Python #SoftwareEngineering",
                "Django multi-tenant architecture — the pattern that scales 🏗️\n\nAt Taleemabad we serve 10K+ daily active users across multiple tenants.\n\nThe key: every single query is scoped by tenant_id in middleware. No exceptions.\n\n→ Middleware injects tenant context\n→ Custom QuerySet filters automatically\n→ Migrations are tenant-aware\n→ APIs return only tenant data\n\nOne mistake = data leak. Zero tolerance.\n\n#Django #Python #SoftwareArchitecture #MultiTenant #Backend",
                "Why I switched from ChatGPT to Claude for production code 🔄\n\nAfter using both for 2+ years on real Django/Python projects:\n\nClaude wins on:\n→ Longer context (whole files, not snippets)\n→ More careful with breaking changes\n→ Better at explaining WHY, not just what\n→ Follows constraints more reliably\n\nBoth are tools. Know when to use which.\n\n#ClaudeAI #ChatGPT #AITools #Developer #Python",
                "How I reduced API latency by 40% at Taleemabad ⚡\n\nReal numbers from production Django:\n\nBefore: 800ms avg response\nAfter: 480ms avg response\n\nWhat worked:\n1. N+1 query elimination (select_related + prefetch_related)\n2. Redis caching for hot endpoints\n3. PostgreSQL index optimization\n4. Pagination on all list endpoints\n\nNone of it was magic. All of it was measurement first.\n\n#Django #Python #PerformanceOptimization #Backend #PostgreSQL",
                "MCP (Model Context Protocol) explained simply 🔌\n\nIf you're building AI agents, you need to understand this.\n\nMCP = a standard way for AI to talk to external tools.\n\nInstead of writing custom integrations for every tool, you write one MCP server and any AI can use it.\n\nI use MCP to connect Claude to: Notion, Slack, Gmail, LinkedIn, GitHub, NotebookLM.\n\nOne protocol. Unlimited integrations.\n\n#MCP #ClaudeAI #AIAgents #Developer #BuildInPublic",
                "Building offline-first apps: what I learned at Taleemabad 📱\n\nWe serve teachers in areas with poor connectivity.\nThe app must work offline. Always.\n\nOur stack: Dexie.js (IndexedDB) + Django backend\n\nThe hard parts:\n→ Conflict resolution (who wins: local or server?)\n→ Sync ordering (dependencies matter)\n→ Data size limits (IndexedDB isn't infinite)\n→ Testing offline scenarios\n\nOffline-first is an architecture decision. Make it early.\n\n#OfflineFirst #Django #React #EdTech #MobileFirst",
                "Zero-downtime database migrations: a practical guide 🗄️\n\nWe run 99.99% uptime on Taleemabad. Migrations can't take down the site.\n\nThe pattern:\n1. Add column as nullable (deploy)\n2. Backfill data in batches (background job)\n3. Make column required (deploy)\n4. Drop old column (deploy)\n\n4 deploys. Zero downtime. Millions of rows.\n\nNever rename columns. Never do both schema + data in one migration.\n\n#Django #PostgreSQL #DevOps #ZeroDowntime #Backend",
                "How I use NotebookLM for deep technical research 📚\n\nBefore building any feature, I run:\nnlm research '[topic]' --mode deep\n\nIt pulls 40+ real sources in 5 minutes.\n\nThen: nlm slides, nlm podcast, nlm quiz\n\nI've used it for: Django patterns, AWS architecture, AI agent design, PostgreSQL optimization.\n\n40 sources > 1 Stack Overflow answer.\n\n#NotebookLM #Research #Developer #AITools #Learning",
                "AWS ECS Fargate vs traditional servers — when to use each 🖥️\n\nAt Taleemabad we moved from EC2 to ECS Fargate.\n\nWhen Fargate wins:\n→ Variable load (scale to zero)\n→ No desire to manage OS patches\n→ Container-native apps\n→ Cost matters at low traffic\n\nWhen EC2 wins:\n→ Predictable high load (reserved instances cheaper)\n→ GPU workloads\n→ Very specific OS requirements\n\nWe use Fargate. Taleemabad team stays small.\n\n#AWS #ECS #Fargate #DevOps #CloudArchitecture",
            ]
            linkedin_caption = TECH_CAPTIONS[_day % 10]
            li_result = post_to_linkedin(linkedin_caption)
            log(f"LinkedIn auto-post: {li_result}")

        except Exception as e:
            log(f"Content pipeline error: {e}")

    threading.Thread(target=run_pipeline, daemon=True).start()


def _check_pending_reactions(channel: str, ts: str):
    """
    When Kamal sends a message, check if any pending eval actions in this
    channel are waiting for a reaction. Mark the most recent one as reacted=yes.
    """
    from kamil_eval_tracker import PENDING_FILE, record_reaction
    if not PENDING_FILE.exists():
        return
    try:
        lines = PENDING_FILE.read_text().splitlines()
        for line in reversed(lines):  # most recent first
            entry = json.loads(line)
            if entry.get("channel") == channel:
                record_reaction(entry["action_id"], reacted=True, boost=30)
                return  # only credit the most recent pending action
    except Exception:
        pass


# ── Proactive idle work ───────────────────────────────────────────────────────

def proactive_loop(web: WebClient, dm_channel: str):
    """Background thread: every 35min of idle, do something useful."""
    global last_activity_time, last_idle_work
    last_proactive_ts = None
    while True:
        time.sleep(60)
        idle_min  = (time.time() - last_activity_time) / 60
        since_idle = (time.time() - last_idle_work) / 60
        if idle_min >= 35 and since_idle >= 60:  # Increased cooldown to 60min to prevent duplicates
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
Sign off: 🤖 Kamil""", timeout=180, event_context="proactive_idle")

            if answer and len(answer) > 20:
                answer_normalized = " ".join(answer.strip().split())
                try:
                    resp = web.chat_postMessage(channel=dm_channel, text=answer_normalized)
                    last_proactive_ts = resp.get("ts", "") if isinstance(resp, dict) else None
                    log(f"Proactive: {answer_normalized[:80]}")
                    # Eval: log proactive DM, watch for Kamal reaction
                    eval_proactive_dm(content=answer_normalized, channel=dm_channel, ts=last_proactive_ts or "")
                except Exception as e:
                    klog_error(context="proactive_loop-send_message", exc=e)


# ── Socket Mode event handler ─────────────────────────────────────────────────

def make_handler(web: WebClient, dm_channel: str, bot_token: str):
    def handler(client: SocketModeClient, req: SocketModeRequest):
        client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

        if req.type != "events_api":
            return

        event      = req.payload.get("event", {})
        event_type = event.get("type", "")
        subtype    = event.get("subtype", "")
        bot_id     = event.get("bot_id", "")
        ts         = event.get("ts", "")
        channel    = event.get("channel", "")

        # Persistent dedup — survives restarts via harness.db (fallback: in-memory set)
        if _is_already_processed(channel, ts):
            return

        # Skip bot messages and edits/deletes
        if bot_id or subtype:
            return

        text    = event.get("text", "").strip()
        user    = event.get("user", "")
        channel = event.get("channel", "")

        # Track Kamil's own posts so we can auto-answer replies in those threads
        if user == KAMIL_BOT_USER and event_type == "message":
            _kamil_thread_origins.add(ts)

        # 1. DM to Kamil bot — Kamal, Fatima, anyone. is_dm=True → flat history fetch
        if event_type == "message" and event.get("channel_type") == "im":
            dispatch(text, web, channel, ts, "DM", sender_id=user, is_dm=True, bot_token=bot_token)

        # 2. @Kamil mention in a channel — reply in thread, use thread replies for history
        elif event_type == "app_mention":
            thread = event.get("thread_ts") or ts
            dispatch(text, web, channel, thread, f"mention in {channel}",
                     sender_id=user, is_dm=False, bot_token=bot_token)

        # 3. Thread reply or channel message in engineering channels — auto-answer questions
        elif event_type == "message" and user and user != KAMIL_BOT_USER:
            thread = event.get("thread_ts") or ts
            in_eng_channel  = channel in ENGINEERING_CHANNELS
            in_kamil_thread = thread in _kamil_thread_origins or ts in _kamil_thread_origins

            if in_eng_channel or in_kamil_thread:
                try:
                    info        = web.users_info(user=user)
                    sender_name = info["user"]["profile"].get("real_name") or info["user"]["name"]
                except Exception:
                    sender_name = f"<@{user}>"

                _MSG_EXECUTOR.submit(
                    auto_answer_engineering_question,
                    text, channel, thread, user, sender_name, web, bot_token,
                )

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

    # Init persistent event dedup (harness.db) — must happen before SocketModeClient
    _init_event_dedup()

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
    socket_client.socket_mode_request_listeners.append(make_handler(web, dm_channel, bot_token))

    klog_system_start("listener")
    log("Kamil listener starting (Socket Mode)...")

    # Retry initial connect on network errors (IncompleteRead, timeout, DNS, etc)
    connect_retries = 0
    while connect_retries < 3:
        try:
            socket_client.connect()
            break
        except http.client.IncompleteRead as e:
            connect_retries += 1
            if connect_retries < 3:
                log(f"Initial connect failed (IncompleteRead), retrying ({connect_retries}/3)...")
                time.sleep(2)
            else:
                log(f"Initial connect failed after 3 retries: {e}")
                raise
        except (TimeoutError, ConnectionError, OSError, socket.gaierror, URLError, Exception) as e:
            connect_retries += 1
            if connect_retries < 3:
                log(f"Initial connect failed ({type(e).__name__}), retrying ({connect_retries}/3)...")
                time.sleep(2)
            else:
                log(f"Initial connect failed after 3 retries: {type(e).__name__}: {e}")
                time.sleep(5)  # Back off before exiting to avoid rapid restart loops

    log("Connected. Listening for DMs and @Kamil mentions.")

    # Process any messages that arrived while listener was offline
    process_missed_messages(web, dm_channel, bot_token=bot_token)

    # Heartbeat: reconnect if socket goes stale (no events for 5 min)
    # Also poll for missed messages every 2 min regardless of socket state
    last_event_time = [time.time()]
    last_poll_time  = [time.time()]
    original_handler = make_handler(web, dm_channel, bot_token)

    def handler_with_heartbeat(client, req):
        last_event_time[0] = time.time()
        original_handler(client, req)

    socket_client.socket_mode_request_listeners.clear()
    socket_client.socket_mode_request_listeners.append(handler_with_heartbeat)

    reconnecting = [False]
    last_reconnect_time = [time.time()]
    web_ref = [web]  # mutable ref so reconnect loop can update it

    while True:
        time.sleep(30)
        now = time.time()
        stale_minutes = (now - last_event_time[0]) / 60
        poll_minutes  = (now - last_poll_time[0])  / 60

        # 30 min threshold — Socket Mode is legitimately quiet during off-hours.
        # 5 min caused 80+ unnecessary reconnects per day (confirmed via Axiom).
        if stale_minutes > 30:
            time_since_last_reconnect = now - last_reconnect_time[0]
            if time_since_last_reconnect < 5:
                continue

            reconnecting[0] = True
            log(f"Socket stale ({stale_minutes:.1f} min) — reconnecting")
            klog_socket("socket_stale", stale_minutes=round(stale_minutes, 1))
            missed = 0
            try:
                try:
                    socket_client.close()
                except Exception:
                    pass
                time.sleep(2)
                # Recreate WebClient after reconnect — old HTTP connection pool is corrupted
                # after a stale socket, causing IncompleteRead on next API call.
                web = WebClient(token=bot_token)
                web_ref[0] = web
                # Dedup is now persistent in harness.db — no clear needed on reconnect
                socket_client = SocketModeClient(app_token=app_token, web_client=web)
                socket_client.socket_mode_request_listeners.clear()
                socket_client.socket_mode_request_listeners.append(handler_with_heartbeat)
                socket_client.connect()
                last_event_time[0] = time.time()
                last_reconnect_time[0] = now
                missed = process_missed_messages(web, dm_channel, bot_token=bot_token)
                klog_socket("socket_reconnect", missed_messages=missed)
                log(f"Reconnected. ({missed} missed messages)")
            except Exception as e:
                klog_error(context="socket_reconnect", exc=e)
                log(f"Reconnect failed: {e}")
            finally:
                reconnecting[0] = False

        # Poll for missed DMs every 2 min as a safety net (catches messages
        # that arrived during socket stale/reconnect gaps)
        # Skip polling during active reconnection to avoid network spam
        if poll_minutes >= 2 and not reconnecting[0]:
            last_poll_time[0] = now
            missed = process_missed_messages(web_ref[0], dm_channel, bot_token=bot_token) or 0
            if missed > 0:
                log(f"[poll] Recovered {missed} missed message(s)")


if __name__ == "__main__":
    main()
