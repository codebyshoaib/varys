#!/usr/bin/env python3
"""
varys_eval_tracker.py — Eval system for every Varys action.

Every action Varys takes gets logged with:
  - action_id:    unique ID so the reaction watcher can find it later
  - action_type:  conversation | proactive-dm | self-question | pr-review |
                  notion-write | self-heal | book-coach | poller-summary
  - initial_score: Varys's self-score before seeing Shoaib's reaction
  - shoaib_reacted: pending → yes/no (updated by reaction watcher)
  - evidence:     what Varys actually did (request, answer, action)

Previously wrote to Notion Health Log DB via Claude MCP subprocess.
Now local-only: all events go to the local telemetry log via klog.
Pending-reaction tracking continues via the local JSONL file.

Scoring rubric (0-100):
  conversation:
    100 — answered with tools, no clarification asked, Shoaib acted on it
    70  — good answer, Shoaib read it
    30  — asked a clarifying question a tool could have answered
    0   — Shoaib had to repeat himself or correct Varys

  proactive-dm / poller-summary:
    100 — Shoaib replied, reacted, or acted on it
    50  — Shoaib read it (no reply but no complaint)
    0   — Shoaib ignored or said "already knew"

  self-question:
    100 — answer sourced from real tool (Notion/GitHub/Slack), spawned useful follow-up
    60  — answer sourced from real tool, no follow-up
    20  — answer was a guess / no tool used
    0   — answer was wrong (corrected by Shoaib later)

  self-heal:
    100 — fix applied, service stable after 24h
    50  — fix applied, needed follow-up
    0   — fix was wrong, broke again

  pr-review:
    100 — Shoaib agreed with all points, no issues missed
    60  — Shoaib agreed with most points
    20  — Shoaib found issues Varys missed
    0   — Varys's review was wrong

  book-coach:
    100 — Shoaib replied, referenced the challenge, or asked follow-up
    50  — DM delivered, no engagement
    0   — Shoaib said not useful

  notion-write:
    100 — entry complete, all fields filled, still accurate after 7 days
    60  — entry created, some fields missing
    0   — entry wrong or stale within 24h

Reaction watcher (passive):
  - After every Varys proactive DM, listener watches the next message Shoaib sends
  - If Shoaib replies within 5 min → reacted=yes, score boosted to 100
  - If Shoaib reacts with emoji → reacted=yes
  - If no reply within 30 min → reacted=no, score stays as-is
  - Updates the local pending file (no Notion write)
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from varys_log import klog

VARYS_DIR    = Path(__file__).parent.parent.parent
PENDING_FILE = Path("/tmp/varys-eval-pending.jsonl")  # actions waiting for reaction

_SESSION_ID = datetime.utcnow().strftime("%Y%m%d-%H%M%S")


# ── Scoring rubrics ───────────────────────────────────────────────────────────

INITIAL_SCORES = {
    # (action_type, signal) → score
    ("conversation",    "no_clarification"):  80,
    ("conversation",    "clarification_asked"): 30,
    ("conversation",    "tool_used"):          90,
    ("proactive-dm",    "sent"):               50,  # bumped to 100 if Shoaib reacts
    ("poller-summary",  "sent"):               50,
    ("self-question",   "tool_sourced"):       70,
    ("self-question",   "guessed"):            20,
    ("self-heal",       "applied"):            70,  # bumped if stable after 24h
    ("self-heal",       "needs_manual"):       10,
    ("pr-review",       "sent"):               60,
    ("book-coach",      "sent"):               50,
    ("notion-write",    "complete"):           70,
    ("notion-write",    "partial"):            40,
}


def _make_id() -> str:
    return str(uuid.uuid4())[:8]


def _save_pending(action_id: str, action_type: str, score: int,
                  channel: str, ts: str):
    """Save to local file so reaction watcher can pick it up."""
    entry = json.dumps({
        "action_id":   action_id,
        "action_type": action_type,
        "score":       score,
        "channel":     channel,
        "ts":          ts,
        "logged_at":   datetime.utcnow().isoformat(),
    })
    with open(PENDING_FILE, "a") as f:
        f.write(entry + "\n")


# ── Public API ────────────────────────────────────────────────────────────────

def log_action(action_type: str, event: str, evidence: str,
               signal: str = "sent", service: str = "claude-session",
               channel: str = "", ts: str = "",
               session_id: str = None) -> str:
    """
    Log a Varys action to the eval system. Returns action_id.
    Call this immediately when Varys does something.
    """
    action_id  = _make_id()
    score      = INITIAL_SCORES.get((action_type, signal),
                 INITIAL_SCORES.get((action_type, "sent"), 50))
    sid        = session_id or _SESSION_ID

    # Log telemetry synchronously — fast, always works
    klog("eval_action", component=service, action_type=action_type,
         action_id=action_id, score=score, signal=signal,
         summary=event[:100], evidence=evidence[:150],
         session_id=sid)

    # Save to pending file if this action expects a Shoaib reaction
    if action_type in ("conversation", "proactive-dm", "poller-summary",
                       "book-coach", "pr-review") and channel and ts:
        _save_pending(action_id, action_type, score, channel, ts)

    return action_id


def record_reaction(action_id: str, reacted: bool, boost: int = 30):
    """
    Call when Shoaib replies to or reacts to a Varys message.
    Boosts the eval score and logs the reaction locally.
    """
    # Load pending to find current score
    current_score = 50
    if PENDING_FILE.exists():
        for line in PENDING_FILE.read_text().splitlines():
            try:
                entry = json.loads(line)
                if entry.get("action_id") == action_id:
                    current_score = entry.get("score", 50)
                    break
            except Exception:
                pass

    final_score = min(100, current_score + boost) if reacted else current_score
    reacted_str = "yes" if reacted else "no"

    klog("eval_reaction", component="eval-tracker",
         action_id=action_id, reacted=reacted_str,
         score_before=current_score, score_after=final_score)

    # Remove from pending
    _remove_pending(action_id)


def expire_pending(max_age_minutes: int = 35):
    """
    Called by the reaction watcher loop. Any pending action older than
    max_age_minutes with no reaction gets marked reacted=no and logged.
    """
    if not PENDING_FILE.exists():
        return

    now     = datetime.utcnow()
    kept    = []
    expired = []

    for line in PENDING_FILE.read_text().splitlines():
        try:
            entry = json.loads(line)
            logged = datetime.fromisoformat(entry["logged_at"])
            age_min = (now - logged).total_seconds() / 60
            if age_min > max_age_minutes:
                expired.append(entry)
            else:
                kept.append(line)
        except Exception:
            pass

    PENDING_FILE.write_text("\n".join(kept) + ("\n" if kept else ""))

    for entry in expired:
        klog("eval_reaction", component="eval-tracker",
             action_id=entry["action_id"], reacted="no",
             score_before=entry.get("score", 50), score_after=entry.get("score", 50))


def _remove_pending(action_id: str):
    if not PENDING_FILE.exists():
        return
    lines = [l for l in PENDING_FILE.read_text().splitlines()
             if action_id not in l]
    PENDING_FILE.write_text("\n".join(lines) + ("\n" if lines else ""))


# ── Convenience wrappers ──────────────────────────────────────────────────────

def eval_conversation(request: str, reply: str, asked_clarification: bool,
                      channel: str = "", ts: str = "",
                      session_id: str = None) -> str:
    signal = "clarification_asked" if asked_clarification else "no_clarification"
    return log_action(
        action_type = "conversation",
        event       = f"Conversation: {request[:60]}",
        evidence    = f"Request: {request[:200]}\nReply: {reply[:200]}",
        signal      = signal,
        service     = "claude-session",
        channel     = channel,
        ts          = ts,
        session_id  = session_id,
    )


def eval_proactive_dm(content: str, channel: str = "", ts: str = "",
                      session_id: str = None) -> str:
    return log_action(
        action_type = "proactive-dm",
        event       = f"Proactive DM: {content[:60]}",
        evidence    = content[:400],
        signal      = "sent",
        service     = "varys-slack-listener",
        channel     = channel,
        ts          = ts,
        session_id  = session_id,
    )


def eval_poller_summary(summary: str, new_items: int,
                        channel: str = "", ts: str = "",
                        session_id: str = None) -> str:
    return log_action(
        action_type = "poller-summary",
        event       = f"Poller summary: {new_items} new items",
        evidence    = summary[:400],
        signal      = "sent",
        service     = "slack-poller",
        channel     = channel,
        ts          = ts,
        session_id  = session_id,
    )


def eval_self_question(question: str, answer: str, tool_used: bool,
                       spawned_followup: bool, session_id: str = None) -> str:
    signal = "tool_sourced" if tool_used else "guessed"
    action_id = log_action(
        action_type = "self-question",
        event       = f"Self-question: {question[:60]}",
        evidence    = f"Q: {question[:200]}\nA: {answer[:200]}\nTool used: {tool_used} | Followup: {spawned_followup}",
        signal      = signal,
        service     = "slack-poller",
        session_id  = session_id,
    )
    return action_id


def eval_self_heal(service: str, root_cause: str, fix: str,
                   applied: bool, session_id: str = None) -> str:
    signal = "applied" if applied else "needs_manual"
    return log_action(
        action_type = "self-heal",
        event       = f"Self-heal: {service}",
        evidence    = f"Root cause: {root_cause}\nFix: {fix}",
        signal      = signal,
        service     = "self-healer",
        session_id  = session_id,
    )


def eval_notion_write(db_name: str, fields_complete: bool,
                      session_id: str = None) -> str:
    signal = "complete" if fields_complete else "partial"
    return log_action(
        action_type = "notion-write",
        event       = f"Notion write: {db_name}",
        evidence    = f"DB: {db_name} | Complete: {fields_complete}",
        signal      = signal,
        service     = "claude-session",
        session_id  = session_id,
    )


def eval_book_coach(book: str, chapter: str,
                    channel: str = "", ts: str = "",
                    session_id: str = None) -> str:
    return log_action(
        action_type = "book-coach",
        event       = f"Book coach: {book} — {chapter}",
        evidence    = f"Book: {book}\nChapter: {chapter}",
        signal      = "sent",
        service     = "claude-session",
        channel     = channel,
        ts          = ts,
        session_id  = session_id,
    )
