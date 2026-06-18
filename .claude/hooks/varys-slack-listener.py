#!/usr/bin/env python3
"""
varys-slack-listener.py — Varys's Slack brain. Socket Mode daemon.

Handles two event types:
  1. DM to Varys bot         → any message in a DM channel
  2. @Varys mention          → app_mention in any channel

Intent routing:
  pr_review  → fetches GitHub diff, posts structured code review
  task       → creates Notion Harness entry, starts taleemabad-core harness
  research   → searches web + Notion + GitHub, answers with context
  chat       → direct answer with Varys personality

Idle 35min → proactive: reads engineering links, writes to Notion Learning Log, DMs {USER_NAME}.

Run:
  python3 .claude/hooks/varys-slack-listener.py

Auto-start via cron:
  @reboot python3 /home/oye/.../varys-slack-listener.py >> /tmp/varys-slack-listener.log 2>&1
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
from agent_config import cfg
from varys_log import (klog, klog_error, klog_conversation, klog_claude_call,
                        klog_socket, klog_catchup, klog_humor, klog_privacy,
                        klog_system_start)
from varys_people import build_person_context, update_profile_after_conversation
from varys_eval import log_to_eval
from varys_health import log_response_quality, log_critique
from varys_eval_tracker import (eval_conversation, eval_proactive_dm,
                                 record_reaction, expire_pending)
from notebooklm_handler import handle as nlm_handle, is_notebooklm_command
try:
    from infographic_handler import handle as infographic_handle
    _infographic_available = True
except ImportError:
    _infographic_available = False

try:
    from honesty_gate import check as honesty_check
    _honesty_gate_available = True
except ImportError:
    _honesty_gate_available = False

from linkedin_poster import post_to_linkedin
try:
    from varys_harness_db import (
        get_db as _get_harness_db,
        enqueue_slack_mention,
    )
    _harness_db_available = True
except Exception:
    _harness_db_available = False

try:
    from varys_context import (
        resolve_person, record_interaction, run_sync_loop,
        PersonNotFound, PersonAmbiguous,
        create_job, mark_job_processing, mark_job_delivered, mark_job_failed,
        log_suppression, log_milestone, fetch_thread_context, extract_pr_url,
        tracked_thread,
    )
    _context_available = True
except Exception:
    _context_available = False

# ── Config ────────────────────────────────────────────────────────────────────
import glob as _glob, shutil as _shutil
def _find_claude() -> str:
    c = _shutil.which("claude")
    if c:
        return c
    # ponytail: daemon runs without nvm in PATH; fall back to glob nvm installs
    hits = sorted(_glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/claude")))
    return hits[-1] if hits else "claude"
CLAUDE_BIN = _find_claude()

SLACK_CONFIG = Path.home() / ".claude" / "hooks" / ".slack"
VARYS_DIR    = Path(__file__).parent.parent.parent
LOG_FILE     = Path("/tmp/varys-slack-listener.log")
STATE_FILE   = Path("/tmp/varys-listener-state.json")

SHOAIB_USER_ID   = cfg("USER_SLACK_ID",        "")  # set USER_SLACK_ID in ~/.agent-config.json
VARYS_BOT_USER  = cfg("BOT_SLACK_USER_ID",   "")  # set BOT_SLACK_USER_ID in ~/.agent-config.json
DB_PAGE_HARNESS = cfg("NOTION_HARNESS_DB_ID", "")  # set NOTION_HARNESS_DB_ID in ~/.agent-config.json
WORKSPACE       = cfg("SLACK_WORKSPACE",      "")  # set SLACK_WORKSPACE in ~/.agent-config.json
AGENT_NAME      = cfg("AGENT_NAME",           "Varys")
USER_NAME       = cfg("USER_NAME",            "Shoaib Ud Din")

# Channels where {{AGENT_NAME}} auto-answers engineering questions
# Replace with your own channel IDs (get from Slack URL or API)
ENGINEERING_CHANNELS: set[str] = set()  # populated on startup from Slack API

# Tracks thread_ts of posts Varys originated — auto-answer replies in these
_varys_thread_origins: set[str] = set()

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


_VISUAL_TRIGGERS = (
    "infographic", "create image", "make image", "generate image",
    "create a visual", "make a visual", "make me a visual",
    "create an image", "generate a picture", "make an infographic",
    "visual for", "image for", "create me an infographic",
    "make me an infographic", "build an infographic",
)

def is_visual_request(text: str) -> bool:
    """Return True if the message is requesting image/infographic generation."""
    t = text.lower()
    return any(trigger in t for trigger in _VISUAL_TRIGGERS)


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
    # Skip Varys's own messages
    if sender_id == VARYS_BOT_USER:
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
                f"Say `nlm research {keywords[0]}` to build one. 🤖 {AGENT_NAME}"
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
            f"🤖 {AGENT_NAME}"
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

# Limits concurrent Claude invocations to auto_answer_engineering_question only
# (handle_message goes through the sequential slack_queue drainer instead)
_MSG_EXECUTOR = ThreadPoolExecutor(max_workers=2)

# Shared web client ref — updated on reconnect so the drainer always has the live client
_web_client_ref: list = [None]

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


def _save_thread_origin(channel: str, ts: str):
    """Persist a Varys-originated thread to harness.db so it survives restarts."""
    if _listener_db is None:
        return
    with _listener_db_lock:
        try:
            _listener_db.execute(
                "INSERT OR IGNORE INTO events "
                "(id, source, type, context_key, payload, status, received_at) "
                "VALUES (?, 'varys', 'thread_origin', ?, '{}', 'done', datetime('now'))",
                (f"thread-{channel}-{ts}", ts),
            )
            _listener_db.commit()
        except Exception:
            pass


def _load_thread_origins():
    """Reload Varys thread_ts values from harness.db into the in-memory set on startup."""
    if _listener_db is None:
        return
    try:
        with _listener_db_lock:
            rows = _listener_db.execute(
                "SELECT context_key FROM events "
                "WHERE type='thread_origin' AND source='varys' "
                "AND received_at >= datetime('now', '-7 days')"
            ).fetchall()
        for (ts,) in rows:
            _varys_thread_origins.add(ts)
        log(f"[startup] loaded {len(rows)} thread origins from harness.db")
    except Exception as e:
        log(f"[startup] could not load thread origins: {e}")


_CHANNEL_SCAN_TS_FILE = Path("/tmp/varys-channel-scan-ts.txt")


def _populate_engineering_channels(web: WebClient):
    """Populate ENGINEERING_CHANNELS from all channels Varys is currently a member of."""
    try:
        resp = web.conversations_list(
            types="public_channel,private_channel",
            exclude_archived=True,
            limit=200,
        )
        new_ids   = {c["id"] for c in resp.get("channels", []) if c.get("is_member")}
        new_names = [
            f"#{c.get('name', c['id'])}"
            for c in resp.get("channels", [])
            if c.get("is_member")
        ]
        ENGINEERING_CHANNELS.clear()
        ENGINEERING_CHANNELS.update(new_ids)
        log(f"[startup] ENGINEERING_CHANNELS ({len(new_ids)}): {', '.join(new_names)}")
    except Exception as e:
        log(f"[startup] could not populate ENGINEERING_CHANNELS: {e}")


def _startup_channel_scan(web: WebClient, dm_channel: str, bot_token: str):
    """
    On startup: scan all member channels for missed messages since last run.
    • Messages @mentioning Varys  → enqueued in slack_queue for the drain
    • Other messages              → summarised by Claude, DM'd to Shoaib
    Runs in a background thread so the listener socket is ready immediately.
    """
    def _run():
        if not ENGINEERING_CHANNELS:
            log("[startup] channel scan skipped — no member channels")
            return

        last_ts = (
            _CHANNEL_SCAN_TS_FILE.read_text().strip()
            if _CHANNEL_SCAN_TS_FILE.exists()
            else str(time.time() - 6 * 3600)
        )

        mention_count = 0
        other_msgs: list[str] = []

        for ch_id in list(ENGINEERING_CHANNELS):
            try:
                resp = web.conversations_history(channel=ch_id, oldest=last_ts, limit=50)
                time.sleep(0.4)  # Slack rate-limit courtesy pause
            except Exception as e:
                log(f"[startup] history fetch failed for {ch_id}: {e}")
                continue

            for m in resp.get("messages", []):
                ts      = m.get("ts", "")
                user    = m.get("user", "")
                bot_id  = m.get("bot_id", "")
                text    = m.get("text", "").strip()
                subtype = m.get("subtype", "")

                if not text or subtype:
                    continue
                # Track and skip Varys-originated messages
                if bot_id or user == VARYS_BOT_USER:
                    _varys_thread_origins.add(ts)
                    _save_thread_origin(ch_id, ts)
                    continue
                if _is_already_processed(ch_id, ts):
                    continue

                if VARYS_BOT_USER and f"<@{VARYS_BOT_USER}>" in text:
                    thread_ts = m.get("thread_ts") or ts
                    if _harness_db_available and _listener_db is not None:
                        row_id = f"slack-{ch_id}-{ts}"
                        enqueue_slack_mention(
                            _listener_db,
                            row_id=row_id,
                            source=f"channel-scan:{ch_id}",
                            channel=ch_id,
                            thread_ts=thread_ts,
                            sender_id=user,
                            sender_name=user,
                            text=re.sub(r"<@[A-Z0-9]+>", "", text).strip(),
                            thread_history="",
                            is_dm=False,
                            is_third_party=(user != SHOAIB_USER_ID),
                            priority=1,
                        )
                        mention_count += 1
                        log(f"[startup] enqueued @mention from {ch_id}: {text[:60]}")
                else:
                    other_msgs.append(f"<#{ch_id}>: {text[:200]}")

        log(f"[startup] scan done — {mention_count} mentions enqueued, {len(other_msgs)} msgs for summary")
        _CHANNEL_SCAN_TS_FILE.write_text(str(time.time()))

        if not other_msgs or not dm_channel:
            return

        summary_input = "\n".join(other_msgs[:40])
        prompt = (
            f"You are {AGENT_NAME}, {USER_NAME}'s AI agent at Taleemabad. "
            f"You just came back online. Below are Slack messages from the past few hours "
            f"across channels you're in. Write a tight 3-5 bullet summary of what's been "
            f"happening — decisions made, things shipped, blockers, team mood. Skip small talk. "
            f"Slack formatting only (*bold*, bullets, no # headers).\n\n{summary_input}"
        )
        summary = run_claude(prompt, event_context="startup-channel-scan")
        if summary and not summary.startswith(("⚠️", "⏱️")):
            try:
                web.chat_postMessage(
                    channel=dm_channel,
                    text=f"*📡 Catch-up ({len(other_msgs)} msgs since last online):*\n{summary}\n🤖 {AGENT_NAME}",
                )
            except Exception as e:
                log(f"[startup] could not DM catch-up: {e}")

    threading.Thread(target=_run, daemon=True, name="startup-channel-scan").start()


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
    env = os.environ.copy()
    env["VARYS_PROMPT"] = prompt
    t0 = time.time()
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "--dangerously-skip-permissions", "--print", "-p", prompt],
            capture_output=True, text=True,
            cwd=cwd or str(VARYS_DIR),
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


HUMOR_LOG = Path("/tmp/varys-humor-log.jsonl")

# Privacy: what Varys must NEVER share with non-Shoaib people
PRIVACY_RULES = """
PRIVACY EVAL — before sending to a non-{USER_NAME} person, strip or rewrite anything that:
1. Reveals another person's work issues, failures, or personal situation
2. Contains {USER_NAME}'s private info (salary, personal logistics, health, finance)
3. Mentions internal system details (DB IDs, API tokens, server errors, infra)
4. Could embarrass {USER_NAME} if the recipient forwarded it to the team
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
                who = AGENT_NAME
            elif uid == SHOAIB_USER_ID:
                who = USER_NAME
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
    prompt = f"""You are {AGENT_NAME}. Save this conversation to Notion.

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
    prompt = f"""You are {AGENT_NAME}'s privacy filter.

A message is about to be sent to *{recipient_name}* (not {USER_NAME}).

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
                   is_dm: bool = False, job_id: str = ""):
    """
    One Claude call with full context.
    is_third_party=True when Fatima (or anyone not {USER_NAME}) is the sender — {AGENT_NAME}
    can reply to them but must pass the privacy eval first.
    """
    is_fun = any(w in text.lower() for w in [
        "song", "poem", "joke", "fun", "imagine", "creative", "lyrics",
        "laugh", "funny", "roast", "go ahead", "sure", "lol", "haha",
    ])
    mode = "human" if is_fun else ("third_party" if is_third_party else "work")

    # For PR review requests from {USER_NAME}: extract URL from trigger or thread.
    # If no URL is found, ask instead of silently passing an empty context to Claude.
    _is_pr_review = (
        not is_third_party
        and any(w in text.lower() for w in ["review this pr", "review the pr", "review pr", "code review"])
    )
    if _is_pr_review and _context_available:
        pr_url = extract_pr_url(trigger_text=text, thread_context=thread_history or "")
        if pr_url is None:
            log_suppression(
                event_id=f"{channel}_{thread_ts}",
                reason_code="no_url_in_context",
                raw_text=text[:200],
                channel=channel,
                sender_id=sender_id or "",
                job_id=job_id,
                details="PR review requested but no GitHub URL found in trigger or thread",
            )
            reply_kwargs = {
                "channel": channel,
                "text": "I couldn't find a PR URL in this thread — can you share the link? 🤖 {AGENT_NAME}",
                "thread_ts": thread_ts,
            }
            web.chat_postMessage(**reply_kwargs)
            if job_id:
                mark_job_failed(job_id, "no_url_in_context")
            return
        else:
            # Route to the purpose-built reviewer skill by repo instead of a
            # generic free-solo review. These user-level skills (~/.claude/skills)
            # run the full six-axis review + exact-position inline GitHub comments
            # + auto-approve. Falls through to generic handling for unknown repos.
            # (wired 2026-06-15)
            _u = pr_url.lower()
            if "compliancetracker" in _u:
                _skill_cmd = f"/compliancetracker-pr-reviewer {pr_url}"
            elif "taleemabad-core" in _u:
                _skill_cmd = f"/taleemabad-pr-review-lite {pr_url}"
            else:
                _skill_cmd = None  # unknown repo → generic handling below
            if _skill_cmd:
                web.chat_postMessage(
                    channel=channel, thread_ts=thread_ts,
                    text=f"On it — reviewing {pr_url} with `{_skill_cmd.split()[0]}` 🔍",
                )
                _review = run_claude(_skill_cmd, cwd=str(VARYS_DIR),
                                     timeout=900, event_context="pr_review")
                web.chat_postMessage(
                    channel=channel, thread_ts=thread_ts,
                    text=(_review[:3500] if _review
                          else "Review finished — see the PR for inline comments."),
                )
                if _context_available and job_id:
                    mark_job_delivered(job_id)
                log(f"[pr-review {_skill_cmd.split()[0]}] {pr_url}")
                return

    if is_third_party:
        person_context = build_person_context(sender_name or "Unknown", sender_id or "")

        prompt = f"""You are {AGENT_NAME} — {USER_NAME}'s AI agent at Taleemabad, replying on behalf of the conversation.

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
- Do NOT sign off as "{AGENT_NAME}" — reply naturally
- Do NOT reveal private info about {USER_NAME}, the team, or internal systems"""

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
        if _context_available and job_id:
            mark_job_delivered(job_id)
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

    # ── Normal {USER_NAME} → {AGENT_NAME} flow ─────────────────────────────────────────────
    _caps_path  = VARYS_DIR / ".claude" / "rules" / "CAPABILITIES.md"
    _caps_block = _caps_path.read_text() if _caps_path.exists() else ""

    prompt = f"""You are {AGENT_NAME} — a senior team member at Taleemabad who commands a fleet of specialist agents.

## ROUTING DECISION — make this before anything else

Casual/instant (banter, joke, poem, quick question answerable in < 60s, no code, no commits):
→ Handle it yourself. Loose, warm, witty. Just do the thing. No explanation.
→ "go ahead" / "sure" / "yes" = read the thread and execute the last proposed thing.
→ Append to /tmp/varys-humor-log.jsonl if humor was used: (JSON: ts, prompt, response, reaction=pending)

Work with scope (code, bug, feature, content, research, jobs, memory, analysis):
→ Pick the right agent. Post a 1-line plan. Dispatch. You coordinate — you don't implement.
→ Agent fleet: bug-agent, content-agent, research-agent, brain-agent,
  slack-agent, notion-agent, people-agent, character-agent, job-agent,
  evolution-agent, escalation-broker.
→ Routing table: .claude/rules/skills-router.md

THE ONE GOVERNING RULE:
{{AGENT_NAME}} never writes production code, never posts content to the world, never commits.
Those always go through a named agent with an approval gate.

### Bug/feature requests — HARD RULES (never break)

When {{USER_NAME}} says anything like "fix X", "users can't see Y", "white screen on Z", "bug in W":

1. NEVER offer execution options ("Subagent-Driven vs Inline"). Just start.
2. NEVER ask about staging vs production. Fixes always go to develop via PR.
3. NEVER ask "should I redesign or just fix?" — if the design exists, fix it.
4. NEVER narrate what you are "about to do". Do it, then report.
5. NEVER ask clarifying questions that the code can answer. Read the code first.
   - "which component?" → grep for it
   - "where is it rendered?" → trace the import
   - "what does the API return?" → read the view/serializer
   Only allowed questions: "I found X and Y approaches, which do you prefer?" (with a recommendation) or "Plan ready — approve to start /develop?"
6. ALWAYS run `/feature <name>` in the relevant project FIRST to create the Notion Harness entry and produce research.md + plan.md before saying anything.
7. ALWAYS post the plan to the thread and wait for "@{{AGENT_NAME}} go" before implementing.
8. NEVER write a single line of production code without plan approval.

Freelance mode (job hunting, proposals):
Triggers: "apply 1/2/3", "apply to job", "write proposal", "job", "freelance".
When {{USER_NAME}} says "apply [number]":
→ Read the thread to find the job listing (title, URL, description)
→ Write a complete, tailored Upwork/freelance proposal using {{USER_NAME}}'s real experience from vault/memory/user_profile.md
→ Proposal format: hook (1 line), relevant experience (3 bullets), what you'll deliver, CTA
→ Keep it under 200 words — short proposals win on Upwork
→ Update the job status in Notion Job Tracker DB to "applied"
→ DM the proposal text back so {{USER_NAME}} can copy-paste it

## CORE RULES (both modes)

1. Never ask what tools can answer.
   - Slack user ID → GET api/users.list filtered by name
   - Send DM → POST api/chat.postMessage with BOT_TOKEN from ~/.claude/hooks/.slack
   - PR diff → `gh pr diff <number>`
   - Notion → mcp__claude_ai_Notion__notion-fetch
   - Web → WebSearch / WebFetch
   - GitHub repo exists? → `gh repo list <org> --limit 50` FIRST. The org is set in ~/.agent-config.json.
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

## WHAT VARYS CANNOT DO
{_caps_block}

## PEOPLE INTELLIGENCE
People Intelligence DB: c976d58ea4e34b0585f245529cdc4528
When {USER_NAME} asks about a person ("how is Fatima?", "what does Haroon need?"):
→ Search People Intelligence DB for their profile
→ Read their Current Mood, Active Needs, Recurring Topics, What Works, {AGENT_NAME} Notes
→ Answer from the profile + check Notion Slack Inbox for recent messages from them

## SHOAIB'S CONTEXT
- Taleemabad, Pakistan — EdTech, Django + React, multi-tenant LMS
- Slack workspace: {WORKSPACE} | User Slack ID: {SHOAIB_USER_ID}
- Harness DB: {DB_PAGE_HARNESS}

## THREAD HISTORY
{thread_history or "(no prior messages)"}

## CURRENT MESSAGE
Source: {source}
{USER_NAME} says: "{text}"

Reply now. Do NOT output any mode label, header, or internal reasoning — just the response itself. Sign off: 🤖 {AGENT_NAME}"""

    t0 = time.time()
    answer = run_claude(prompt, cwd=str(VARYS_DIR), timeout=300, event_context=source)
    # Honesty gate: catches false delivery claims before sending
    if _honesty_gate_available:
        answer = honesty_check(answer, uploaded=False, request=text)
    latency = round(time.time() - t0, 1)

    # Always reply with thread_ts so the reply appears directly below the original message
    reply_kwargs = {"channel": channel, "text": answer, "thread_ts": thread_ts}
    web.chat_postMessage(**reply_kwargs)

    # Mark job delivered AFTER successful send — never before
    if _context_available and job_id:
        mark_job_delivered(job_id)

    # Write-back: log this interaction to per-person memory
    if _context_available and sender_name:
        try:
            person = resolve_person(sender_name)
            _summary_prompt = (
                f"Summarize in 1-2 sentences: what was asked, what was decided, any open items. "
                f"Request: '{text[:200]}' Reply: '{answer[:200]}'"
            )
            summary = run_claude(_summary_prompt, timeout=30)
            record_interaction(
                person_id=person.entity_id,
                source='slack',
                external_id=f"{channel}_{thread_ts}",
                raw=thread_history or text,
                summary=summary,
                open_items="[]",
            )
        except (PersonNotFound, PersonAmbiguous):
            pass
        except Exception as _e:
            log(f"[record_interaction] failed: {_e}")

    log(f"[{source}] replied: {answer[:80]}")

    conv_id = f"{channel}-{thread_ts}"

    # mode was already determined at line ~248
    klog_conversation(
        conv_id        = conv_id,
        sender_name    = sender_name or USER_NAME,
        sender_id      = sender_id or SHOAIB_USER_ID,
        is_third_party = is_third_party,
        channel        = channel,
        source         = source,
        mode           = mode,
        request        = text,
        reply          = answer,
        latency_s      = latency,
        thread_preview = thread_history,
    )

    # Write to Eval Log for Shoaib to review and rate
    log_to_eval(
        conv_id     = conv_id,
        sender_name = sender_name or USER_NAME,
        request     = text,
        reply       = answer,
        mode        = mode,
        source      = source,
        latency_s   = latency,
    )

    # Self-critique: did Varys ask a clarifying question it could have answered itself?
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
            reason  = f"{AGENT_NAME} asked a clarifying question — should have used tools to find the answer",
            request = text,
        )

    # Eval tracker — log this action, watch for Shoaib's reaction
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
        klog_humor(sender_name=sender_name or USER_NAME, request=text, reply=answer)


def process_missed_messages(web: WebClient, dm_channel: str, retry_count: int = 0, bot_token: str = None) -> int:
    """On connect/reconnect: process any DMs that arrived while offline. Returns count."""
    if not dm_channel:
        return 0
    state_file = Path("/tmp/varys-last-processed-ts.txt")
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

            # Skip bot messages, Varys's own replies, and edits/deletes
            # MCP Slack tool sends as Shoaib's OAuth token so bot_id is absent —
            # detect Varys's own messages by the leading robot emoji signature
            is_varys_own = (user == VARYS_BOT_USER or text.startswith("🤖"))
            if not text or bot_id or subtype or ts == last_ts or is_varys_own:
                continue
            if float(ts) <= float(last_ts):
                continue

            log(f"[catchup] {user}: {text[:60]}")
            klog_catchup(sender_id=user, text_preview=text[:100], ts=ts)
            dispatch(text, web, dm_channel, ts, "DM-catchup", sender_id=user, is_dm=True, bot_token=bot_token, msg_ts=ts)
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
             sender_id: str = None, is_dm: bool = False, bot_token: str = None,
             msg_ts: str = None):
    """Dispatch to unified handler with full conversation context."""
    global last_activity_time
    last_activity_time = time.time()

    clean = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    if not clean:
        if _context_available:
            log_suppression(
                event_id=thread_ts or "",
                reason_code="empty_after_strip",
                raw_text=text[:200],
                channel=channel,
                sender_id=sender_id or "",
            )
        return

    # Create job row for this inbound event
    job_id = ""
    if _context_available:
        job_id = create_job(
            event_id=f"{channel}_{thread_ts}",
            source=source,
            raw_text=clean,
            channel=channel,
            thread_ts=thread_ts,
            sender_id=sender_id or "",
        )

    log(f"[{source}] {clean[:80]}")

    # For DMs: read flat channel history. For channel threads: read thread replies.
    if _context_available and not is_dm:
        thread_history = fetch_thread_context(
            channel=channel,
            thread_ts=thread_ts,
            web=web,
            event_id=f"{channel}_{thread_ts}",
            sender_id=sender_id or "",
        )
    else:
        thread_history = fetch_thread_history(web, channel, thread_ts, is_dm=is_dm, bot_token=bot_token)

    # Resolve sender identity
    is_third_party = sender_id is not None and sender_id != SHOAIB_USER_ID
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

    # Reaction watcher: if Shoaib is replying, check if this is a reaction to a pending Varys action
    if sender_id == SHOAIB_USER_ID and not is_third_party:
        _check_pending_reactions(channel, thread_ts)

    # Expire old pending evals (no reaction within 35 min = reacted:no)
    expire_pending(max_age_minutes=35)

    # ── First message of the day — run content pipeline if not done yet ──────
    # DISABLED 2026-06-15: this auto-posted hardcoded TECH_CAPTIONS to LinkedIn
    # (previous owner Shoaib's content) with no human approval, triggered by the
    # first Slack message each day. LinkedIn posting is manual-only for this user
    # to avoid spam/ban risk. Re-enable only with an explicit opt-in + per-post
    # approval. See memory: content-linkedin-pipeline-setup / user-linkedin-identity.
    # if sender_id == SHOAIB_USER_ID and not is_third_party:
    #     _maybe_run_daily_content()

    # ── NotebookLM fast-path — bypass Claude for nlm commands ────────────────
    if sender_id == SHOAIB_USER_ID and is_notebooklm_command(clean):
        cfg       = load_config()
        bot_token_cfg = cfg.get("BOT_TOKEN")
        if _context_available and job_id:
            mark_job_processing(job_id)
            tracked_thread(job_id, nlm_handle, clean, bot_token_cfg)
        else:
            threading.Thread(
                target=nlm_handle,
                args=(clean, bot_token_cfg),
                daemon=True,
            ).start()
        return

    # Visual/infographic fast-path REMOVED 2026-06-17: loose substring matching on
    # "infographic" misfired on natural-language messages (e.g. sarcasm mentioning
    # the word). All non-nlm messages now flow through the queue → slack-worker.py,
    # where the LLM judges intent properly instead of dumb keyword matching.

    if _harness_db_available and _listener_db is not None:
        # ponytail: deterministic ID on msg_ts (or thread_ts for DMs) — UUID suffix was
        # breaking INSERT OR IGNORE dedup, causing the same message to be processed twice.
        row_id = f"slack-{channel}-{msg_ts or thread_ts}"
        enqueued = enqueue_slack_mention(
            _listener_db, row_id, source, channel, thread_ts,
            sender_id or "", sender_name or "", clean,
            thread_history or "", is_dm, is_third_party, job_id or "",
        )
        if enqueued:
            log(f"[queue] enqueued {row_id}")
        else:
            log(f"[queue] dedup hit for {channel}/{thread_ts}, skipped")
    else:
        # Fallback: process immediately if DB unavailable
        if _context_available and job_id:
            mark_job_processing(job_id)
        _MSG_EXECUTOR.submit(
            handle_message,
            clean, thread_history, web, channel, thread_ts, source,
            sender_id, sender_name, is_third_party, is_dm, job_id,
        )


_content_ran_today = Path("/tmp/varys-content-ran.txt")

def _maybe_run_daily_content():
    """
    Run the social media content pipeline once per day — triggered on
    {USER_NAME}'s first Slack message of the day, regardless of time.
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

    pipeline_job_id = ""
    if _context_available:
        import datetime as _dt
        pipeline_job_id = create_job(
            event_id=f"daily_content_{_dt.datetime.now().strftime('%Y-%m-%d')}",
            source='cron',
            intent='content_pipeline',
            steps_total=8,
        )
        mark_job_processing(pipeline_job_id)
        log_milestone(pipeline_job_id, 'pipeline_started', 1, 8, 'completed')

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

            env = os.environ.copy()
            varys_dir = str(VARYS_DIR)

            prompt = f"""You are {AGENT_NAME}. Run today's social media content pipeline.

FITNESS TOPIC: {fit_topic}
TECH TOPIC: {tech_topic}

Do this for EACH topic:
1. `nlm notebook create "[TOPIC]"` → get notebook ID
2. `nlm research start "[TOPIC] tips guide educational" --notebook-id [ID] --mode deep --auto-import`
3. `nlm slides create [ID] --focus "[TOPIC]" --confirm`
4. Wait for slides (poll `nlm status artifacts [ID]` until completed)
5. `nlm download slide-deck [ID] --output /tmp/[fitness|tech]-today-slides.pdf`
6. Convert PDF to PNGs: `pdftoppm -r 150 -png /tmp/[...].pdf /tmp/[fitness|tech]-slide-today`
7. Upload each slide PNG to Slack channel {{USER_SLACK_DM}} using BOT_TOKEN from ~/.claude/hooks/.slack
   Format: "🏃 Slide N/total — [topic]" or "💻 Slide N/total — [topic]"
8. Post caption message with title, description, hashtags for Instagram + TikTok (fitness) and Instagram + TikTok + LinkedIn + YouTube (tech)

English only. Both accounts every day.
BOT_TOKEN is in ~/.claude/hooks/.slack"""

            env["VARYS_CONTENT_PROMPT"] = prompt
            if _context_available and pipeline_job_id:
                log_milestone(pipeline_job_id, 'content_generation_spawn', 2, 8, 'completed')
            subprocess.Popen(
                [CLAUDE_BIN, "--dangerously-skip-permissions", "--print", "-p", prompt],
                cwd=varys_dir, env=env,
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
                "I built a personal AI agent that works 24/7 on my behalf 🤖\n\nVarys monitors Slack, reviews PRs, finds freelance work, posts content, and heals itself when it crashes.\n\nBuilt with Claude API, Python, and MCP.\n\nThe stack: Slack SDK + Notion MCP + GitHub CLI + NotebookLM + LinkedIn API\n\nMore details in my next post.\n\n#AIAgents #ClaudeAI #BuildInPublic #Python #SoftwareEngineering",
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
            if _context_available and pipeline_job_id:
                log_milestone(pipeline_job_id, 'linkedin_posted', 8, 8, 'completed')
                mark_job_delivered(pipeline_job_id)

        except Exception as e:
            log(f"Content pipeline error: {e}")
            if _context_available and pipeline_job_id:
                mark_job_failed(pipeline_job_id, str(e))

    threading.Thread(target=run_pipeline, daemon=True).start()


def _check_pending_reactions(channel: str, ts: str):
    """
    When {USER_NAME} sends a message, check if any pending eval actions in this
    channel are waiting for a reaction. Mark the most recent one as reacted=yes.
    """
    from varys_eval_tracker import PENDING_FILE, record_reaction
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
        user       = event.get("user", "")

        # Persistent dedup — survives restarts via harness.db (fallback: in-memory set)
        if _is_already_processed(channel, ts):
            return

        # Track Varys-originated threads BEFORE the bot-skip — bot messages carry bot_id
        # ponytail: was dead code after the early-return; moved here to actually fire
        if bot_id and user == VARYS_BOT_USER and event_type == "message":
            _varys_thread_origins.add(ts)
            _save_thread_origin(channel, ts)

        # Skip bot messages and edits/deletes
        if bot_id or subtype:
            return

        text = event.get("text", "").strip()

        # 1. DM to Varys bot — Shoaib, Fatima, anyone. is_dm=True → flat history fetch
        if event_type == "message" and event.get("channel_type") == "im":
            dispatch(text, web, channel, ts, "DM", sender_id=user, is_dm=True, bot_token=bot_token, msg_ts=ts)

        # 2. @Varys mention in a channel — reply in thread, use thread replies for history
        elif event_type == "app_mention":
            thread = event.get("thread_ts") or ts
            # "@Varys go" on a plan thread = approval (Shoaib-gated) → fire orchestrator, not a reply
            if _maybe_fire_go_signal(channel, thread, ts, user, text, web, bot_token):
                return
            dispatch(text, web, channel, thread, f"mention in {channel}",
                     sender_id=user, is_dm=False, bot_token=bot_token, msg_ts=ts)

        # 3. Thread reply or channel message in member channels
        elif event_type == "message" and user and user != VARYS_BOT_USER:
            thread = event.get("thread_ts") or ts
            in_eng_channel  = channel in ENGINEERING_CHANNELS
            in_varys_thread = thread in _varys_thread_origins or ts in _varys_thread_origins

            if in_varys_thread:
                # Approval gate first: a Shoaib "go" on a plan thread fires the orchestrator
                # worker (implement → PR), not a conversational reply. Non-Shoaib "go" is refused.
                if _maybe_fire_go_signal(channel, thread, ts, user, text, web, bot_token):
                    return
                # Otherwise: reply in a Varys-originated thread → full dispatch
                dispatch(text, web, channel, thread, f"thread-reply in {channel}",
                         sender_id=user, is_dm=False, bot_token=bot_token, msg_ts=ts)
            elif in_eng_channel:
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


_APPROVAL_RE = re.compile(r"^(go|go ahead|approved?|proceed|ship it)\b", re.I)


def _maybe_fire_go_signal(channel: str, thread: str, ts: str, user: str,
                          text: str, web: "WebClient", bot_token: str) -> bool:
    """
    If `text` is an approval reply in a thread linked to an awaiting_approval orchestrator
    session, gate it: ONLY Shoaib can approve. On his 'go', insert a message.go_signal event
    (the orchestrator fires Phase 2 → implement → PR, reported back in this thread).
    Returns True if this reply was an approval attempt (handled — caller should not dispatch).
    """
    clean = re.sub(r"<@[A-Z0-9]+>", "", text or "").strip()
    if not _APPROVAL_RE.match(clean):
        return False
    try:
        db = _get_harness_db()
        row = db.execute(
            """SELECT s.id, s.context_key FROM sessions s
               JOIN entities e_bead ON e_bead.id = s.context_key
               JOIN links l ON (l.entity_a = s.context_key OR l.entity_b = s.context_key)
               JOIN entities e_slack ON e_slack.id =
                    CASE WHEN l.entity_a = s.context_key THEN l.entity_b ELSE l.entity_a END
               WHERE s.status='awaiting_approval'
                 AND e_slack.source='slack' AND e_slack.external_id=?
               ORDER BY s.updated_at DESC LIMIT 1""",
            (f"{channel}/{thread}",),
        ).fetchone()
    except Exception as e:
        log(f"[go-gate] lookup failed: {e}")
        return False
    if not row:
        return False  # approval-shaped, but no awaiting session here → let normal dispatch handle it
    session_id, context_key = row
    if user != SHOAIB_USER_ID:
        try:
            web.chat_postMessage(channel=channel, thread_ts=thread,
                text=f"Only <@{SHOAIB_USER_ID}> can approve this work. 🤖 {AGENT_NAME}")
        except Exception:
            pass
        log(f"[go-gate] non-Shoaib approval blocked from {user}")
        return True
    try:
        db.execute(
            "INSERT OR IGNORE INTO events "
            "(id, source, type, context_key, payload, status, received_at) "
            "VALUES (?, 'slack', 'message.go_signal', ?, ?, 'pending', datetime('now'))",
            (f"slack-go-{channel}-{ts}", context_key,
             json.dumps({"session_id": session_id, "channel": channel, "thread": thread})),
        )
        db.commit()
        web.chat_postMessage(channel=channel, thread_ts=thread,
            text=f"Approved — implementing now, I'll post the PR here. 🤖 {AGENT_NAME}")
        log(f"[go-gate] go_signal queued for session {session_id[:16]} ctx={context_key[:16]}")
    except Exception as e:
        log(f"[go-gate] failed to queue go_signal: {e}")
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    cfg        = load_config()
    bot_token  = cfg.get("BOT_TOKEN")  or os.environ.get("BOT_TOKEN")
    app_token  = cfg.get("APP_TOKEN")  or os.environ.get("APP_TOKEN")

    if not bot_token or not app_token:
        log("ERROR: BOT_TOKEN and APP_TOKEN required in ~/.claude/hooks/.slack")
        sys.exit(1)

    Path("/tmp/varys-slack-listener.pid").write_text(str(os.getpid()))

    # Init persistent event dedup (harness.db) — must happen before SocketModeClient
    _init_event_dedup()
    _load_thread_origins()

    web = WebClient(token=bot_token)
    _web_client_ref[0] = web

    # Open DM with Shoaib for proactive messages
    try:
        dm_resp    = web.conversations_open(users=SHOAIB_USER_ID)
        dm_channel = dm_resp["channel"]["id"]
        log(f"DM channel with {USER_NAME}: {dm_channel}")
    except Exception as e:
        log(f"Could not open DM: {e}")
        dm_channel = None

    # Connect via Socket Mode
    socket_client = SocketModeClient(app_token=app_token, web_client=web)
    socket_client.socket_mode_request_listeners.append(make_handler(web, dm_channel, bot_token))

    if _context_available:
        import threading as _threading
        _threading.Thread(target=run_sync_loop, args=(60,), daemon=True).start()
        log("[varys_context] sync loop started")

    # Queue draining moved to varys-tick.py (slack-queue-drain.py step)

    klog_system_start("listener")
    log(f"{AGENT_NAME} listener starting (Socket Mode)...")

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

    log("Connected. Listening for DMs and @Varys mentions.")

    # Populate member channels, catch up DMs, then scan all channels in background
    _populate_engineering_channels(web)
    process_missed_messages(web, dm_channel, bot_token=bot_token)
    _startup_channel_scan(web, dm_channel, bot_token)

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
                _web_client_ref[0] = web
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
    if _context_available:
        import threading as _t2
        from varys_context import run_stale_job_checker
        _t2.Thread(target=run_stale_job_checker, args=(300,), daemon=True).start()
        log("[varys_context] stale job checker started")
    main()
