"""
varys_log.py — Structured local telemetry logging for all Varys hooks.

Design principles:
- Every event has base fields: _time, component, event, session_id
- Events are typed — no null pollution from unrelated fields
- Conversation events have conv_id for grouping threads
- Queryable as a harness: "show me slow calls", "show me failed intents",
  "show me all messages Shoaib had to repeat"

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
    from varys_log import klog, klog_error, klog_conversation
    klog("socket_stale", stale_minutes=8.2)
    klog_conversation(sender_name="Shoaib", request="send a joke", reply="Sent!", ...)
    klog_error("handle_message", exc)
"""

import datetime
import json
import os
import traceback
from pathlib import Path
import socket
import uuid

_HOST = socket.gethostname()
_PID = os.getpid()
_SCHEMA_VERSION = "1.0"
_TRACE_ID = None  # set per-operation via start_trace()

# The single telemetry sink: one JSON event per line. Persistent so reboots don't
# wipe it (/tmp clears on boot). Read it with jq, or via varys-observer /
# varys-self-healer, which scan it for recent ERROR/FATAL events.
# ponytail: append-only, grows unbounded; add size-based rotation if it gets large.
_FALLBACK_LOG   = Path.home() / ".varys-harness" / "telemetry.jsonl"
try:
    _FALLBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
except Exception:
    _FALLBACK_LOG = Path("/tmp/varys-telemetry.jsonl")  # last-resort path
_SESSION_ID     = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")


def _now_iso() -> str:
    """ISO timestamp for local fallback log only."""
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _send(events: list):
    """Append events to the local telemetry log, one JSON object per line. Never raises."""
    try:
        with open(_FALLBACK_LOG, "a") as f:
            for e in events:
                f.write(json.dumps({**e, "_local_time": _now_iso()}) + "\n")
    except Exception:
        pass


def _base(component: str, event: str, severity: str = "INFO") -> dict:
    """Base fields present on every event (OTel-aligned envelope)."""
    return {
        "schema_version": _SCHEMA_VERSION,
        "severity":       severity,
        "component":      component,
        "event":          event,
        "session_id":     _SESSION_ID,
        "trace_id":       _TRACE_ID or _SESSION_ID,
        "host":           _HOST,
        "pid":            _PID,
    }


def start_trace(trace_id: str = None) -> str:
    """Begin a correlated operation. Returns the trace_id."""
    global _TRACE_ID
    _TRACE_ID = trace_id or uuid.uuid4().hex[:16]
    return _TRACE_ID

def new_span() -> str:
    return uuid.uuid4().hex[:8]


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
    """The main conversation log — who asked what, what Varys replied."""
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


def klog_error(context: str, exc: Exception = None, component: str = "listener",
               severity: str = "ERROR", **extra):
    e = _base(component, "error", severity=severity)
    e.update({
        "context":    context,
        "error_type": type(exc).__name__ if exc else "unknown",
        "error_msg":  str(exc) if exc else "unknown",
        "error":      str(exc) if exc else "unknown",  # backward compat
        "traceback":  traceback.format_exc() if exc else "",
        **extra,
    })
    _send([e])


def klog_system_start(component: str, version: str = "v2.2"):
    e = _base(component, "system_start")
    e.update({"version": version})
    _send([e])


def klog_cron(component: str, *, status: str, duration_ms: float,
              items: int = 0, rc: int = 0, error: str = "", **extra):
    """One row per cron run. status: ok|error|partial."""
    sev = "INFO" if status == "ok" else ("ERROR" if status == "error" else "WARN")
    e = _base(component, "cron_run", severity=sev)
    e.update({"status": status, "duration_ms": duration_ms, "items": items,
              "rc": rc, "error": error, **extra})
    _send([e])

def klog_external(component: str, *, target: str, status: str,
                  latency_ms: float = 0, retry_count: int = 0, http_status: int = 0, **extra):
    """External API call. target: slack|notion|github|kie|openoutreach|linkedin|nlm."""
    sev = "INFO" if status == "ok" else "WARN"
    e = _base(component, "external_call", severity=sev)
    e.update({"target": target, "status": status, "latency_ms": latency_ms,
              "retry_count": retry_count, "http_status": http_status, **extra})
    _send([e])

def klog_policy_block(component: str, *, rule: str, reason: str, command: str = "", path: str = ""):
    """A PreToolUse hook blocked something."""
    e = _base(component, "policy_block", severity="WARN")
    e.update({"rule": rule, "reason": reason,
              "command": command[:200], "path": path})
    _send([e])

def klog_bead(*, action: str, bead_id: str, title: str = "", status: str = ""):
    """action: opened|closed."""
    e = _base("beads", f"bead_{action}")
    e.update({"bead_id": bead_id, "title": title, "status": status})
    _send([e])

def klog_eval(*, passed: int, failed: int, metrics: dict = None):
    e = _base("evals", "eval_run", severity="INFO" if failed == 0 else "WARN")
    e.update({"passed": passed, "failed": failed, **(metrics or {})})
    _send([e])

def klog_session_end(component: str, *, duration_s: float = 0, context_loaded: str = ""):
    e = _base(component, "session_end")
    e.update({"duration_s": duration_s, "context_loaded": context_loaded})
    _send([e])


def klog_suppression(
    event_id: str,
    reason_code: str,
    raw_text: str = "",
    channel: str = "",
    sender_id: str = "",
    job_id: str = "",
    details: str = "",
) -> None:
    """Log a suppressed/dropped inbound message event."""
    klog(
        "suppression",
        component="listener",
        event_id=event_id,
        reason_code=reason_code,
        raw_text=raw_text[:200],
        channel=channel,
        sender_id=sender_id,
        job_id=job_id,
        details=details[:500],
        severity="WARNING",
    )

def klog_milestone(
    job_id: str,
    step_name: str,
    step_index: int,
    total_steps: int,
    status: str,
    details: str = "",
) -> None:
    """Log a step milestone for a multi-step job."""
    klog(
        "milestone",
        component="listener",
        job_id=job_id,
        step_name=step_name,
        step_index=step_index,
        total_steps=total_steps,
        status=status,
        details=details[:500],
        severity="INFO",
    )


# ── Legacy shim — so existing klog() calls don't break during transition ─────

def klog(event: str, **fields):
    """
    Generic fallback. Prefer typed functions above.
    Used by code not yet migrated to typed calls.
    """
    e = _base(fields.pop("component", "unknown"), event)
    e.update(fields)
    _send([e])
