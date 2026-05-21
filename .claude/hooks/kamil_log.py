"""
kamil_log.py — Structured Axiom logging for all Kamil hooks.

Design principles:
- Every event has base fields: _time, component, event, session_id
- Events are typed — no null pollution from unrelated fields
- Conversation events have conv_id for grouping threads
- Queryable as a harness: "show me slow calls", "show me failed intents",
  "show me all messages Kamal had to repeat"

Event types:
  conversation     — full request/reply log (the main one you read)
  claude_call      — latency + status per Claude subprocess
  socket_stale     — connection went deaf + how long
  socket_reconnect — reconnected + missed message count
  message_catchup  — message processed after reconnect
  poller_run       — 30min cron result
  privacy_filtered — outbound message was modified by privacy eval
  humor_interaction — fun mode interaction (for humor profile eval)
  error            — any exception with context + traceback
  system_start     — listener/poller startup

Usage:
    from kamil_log import klog, klog_error, klog_conversation
    klog("socket_stale", stale_minutes=8.2)
    klog_conversation(sender_name="Kamal", request="send a joke", reply="Sent!", ...)
    klog_error("handle_message", exc)
"""

import datetime
import json
import os
import traceback
import urllib.request
from pathlib import Path

_AXIOM_CONFIG   = Path.home() / ".claude" / "hooks" / ".axiom"
_FALLBACK_LOG   = Path("/tmp/kamil-axiom-fallback.jsonl")
_SESSION_ID     = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")


def _load_token() -> str:
    if _AXIOM_CONFIG.exists():
        for line in _AXIOM_CONFIG.read_text().splitlines():
            if line.startswith("AXIOM_TOKEN="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("AXIOM_TOKEN", "")


def _now_iso() -> str:
    """ISO timestamp for local fallback log only."""
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _send(events: list):
    """Send events to Axiom. Never raises."""
    token = _load_token()

    # Always write to local fallback with timestamp
    try:
        with open(_FALLBACK_LOG, "a") as f:
            for e in events:
                f.write(json.dumps({**e, "_local_time": _now_iso()}) + "\n")
    except Exception:
        pass

    if not token:
        return

    try:
        # Do NOT send _time — let Axiom use ingest time as the index timestamp.
        # Sending _time as a string field causes it to be stored but not indexed.
        axiom_events = [{k: v for k, v in e.items() if k != "_time"} for e in events]
        payload = json.dumps(axiom_events).encode()
        req = urllib.request.Request(
            "https://api.axiom.co/v1/datasets/kamil-logs/ingest",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            pass  # fire and forget
    except Exception:
        pass  # fallback file already has it


def _base(component: str, event: str) -> dict:
    """Base fields present on every event."""
    return {
        "component":  component,   # listener | poller | session-start | learn
        "event":      event,
        "session_id": _SESSION_ID,
    }


# ── Typed log functions ───────────────────────────────────────────────────────

def klog_conversation(
    component: str = "listener",
    *,
    conv_id: str,
    sender_name: str,
    sender_id: str,
    is_third_party: bool,
    channel: str,
    source: str,
    mode: str,
    request: str,
    reply: str,
    latency_s: float,
    privacy_filtered: bool = False,
    thread_preview: str = "",
):
    """The main conversation log — who asked what, what Kamil replied."""
    e = _base(component, "conversation")
    e.update({
        "conv_id":          conv_id,
        "sender_name":      sender_name,
        "sender_id":        sender_id,
        "is_third_party":   is_third_party,
        "channel":          channel,
        "source":           source,
        "mode":             mode,
        "request":          request,
        "reply":            reply,
        "latency_s":        latency_s,
        "privacy_filtered": privacy_filtered,
        "thread_preview":   thread_preview[-300:] if thread_preview else "",
        "request_len":      len(request),
        "reply_len":        len(reply),
    })
    _send([e])


def klog_claude_call(
    component: str = "listener",
    *,
    context: str,
    latency_s: float,
    status: str,        # ok | error | timeout
    prompt_len: int = 0,
    response_len: int = 0,
    error: str = "",
):
    e = _base(component, "claude_call")
    e.update({
        "context":      context,
        "latency_s":    latency_s,
        "status":       status,
        "prompt_len":   prompt_len,
        "response_len": response_len,
        "error":        error,
    })
    _send([e])


def klog_socket(event: str, *, stale_minutes: float = 0, missed_messages: int = 0):
    e = _base("listener", event)
    e.update({
        "stale_minutes":   stale_minutes,
        "missed_messages": missed_messages,
    })
    _send([e])


def klog_poller(*, new_items: int, total_inbox: int, channels_read: int, by_type: dict):
    e = _base("poller", "poller_run")
    e.update({
        "new_items":     new_items,
        "total_inbox":   total_inbox,
        "channels_read": channels_read,
        # Flatten by_type into individual fields for easy APL filtering
        "count_mention":    by_type.get("Mention", 0),
        "count_pr":         by_type.get("PR Review Request", 0),
        "count_bug":        by_type.get("Bug Report", 0),
        "count_fyi":        by_type.get("FYI", 0),
        "count_question":   by_type.get("Question", 0),
    })
    _send([e])


def klog_privacy(*, sender_name: str, was_modified: bool, original_len: int, safe_len: int):
    e = _base("listener", "privacy_filtered")
    e.update({
        "sender_name":   sender_name,
        "was_modified":  was_modified,
        "original_len":  original_len,
        "safe_len":      safe_len,
    })
    _send([e])


def klog_humor(*, sender_name: str, request: str, reply: str):
    e = _base("listener", "humor_interaction")
    e.update({
        "sender_name": sender_name,
        "request":     request[:200],
        "reply":       reply[:300],
    })
    _send([e])


def klog_catchup(*, sender_id: str, text_preview: str, ts: str):
    e = _base("listener", "message_catchup")
    e.update({
        "sender_id":    sender_id,
        "text_preview": text_preview,
        "original_ts":  ts,
    })
    _send([e])


def klog_error(context: str, exc: Exception = None, component: str = "listener", **extra):
    e = _base(component, "error")
    e.update({
        "context":   context,
        "error":     str(exc) if exc else "unknown",
        "traceback": traceback.format_exc() if exc else "",
        **extra,
    })
    _send([e])


def klog_system_start(component: str, version: str = "v2.2"):
    e = _base(component, "system_start")
    e.update({"version": version})
    _send([e])


# ── Legacy shim — so existing klog() calls don't break during transition ─────

def klog(event: str, **fields):
    """
    Generic fallback. Prefer typed functions above.
    Used by code not yet migrated to typed calls.
    """
    e = _base(fields.pop("component", "unknown"), event)
    e.update(fields)
    _send([e])
