# Agent Silent Failure Hardening — Design Spec
**Date:** 2026-06-04
**Status:** Approved
**Owner:** Kamal

---

## Problem

The Kamil harness receives tasks via Slack but silently fails to complete them in at least 30 confirmed locations across the codebase. The triggering incident: Kamal forwarded a PR review request (`@Kamil review this PR`) — Kamil logged the mention at 12:55:57 but never logged a reply, never logged an error, and never surfaced the failure in Axiom or Notion Observability. The user had no way to know the job was dropped.

This is not an isolated bug. A codebase audit identified 7 failure categories:
1. Silent exception swallowing (bare `except: pass` with no log)
2. Multi-step operations with incomplete logging (steps 2–7 invisible)
3. Intent routing with no completion record
4. Thread context not read before replying (trigger message only)
5. Partial completion — only first and last steps log
6. Fire-and-forget daemon threads with no verification
7. Dedup/state DB fallback silently degrades mid-runtime

Research confirms this is systemic across production AI agents: 78% of production AI issues are behavioral and invisible to infrastructure monitoring. Infrastructure success (HTTP 200, no exceptions, normal latency) is necessary but not sufficient evidence of task delivery.

**Goal:** Make every task Kamil receives either visibly delivered or visibly failed — no silent drops, no invisible partial completions.

---

## Architecture Overview

Four layers, each independently deployable:

1. **Job State Machine** — explicit `received → processing → delivered | failed | timed_out` lifecycle for every inbound event; `delivered` written last, only after side effect confirmed
2. **Suppression Event Registry** — every dropped/filtered/misrouted message emits a structured log event with a reason code before returning
3. **Full Thread Context Enrichment** — every handler fetches the full Slack thread via `conversations.replies` before running; trigger message is a pointer, not the spec
4. **Multi-Step Milestone Logging** — every multi-step operation logs each step with `(job_id, step_name, step_index, total_steps, status)`; fire-and-forget threads replaced with tracked threads

---

## Section 1: Job State Machine

### States

```
received → processing → delivered
                      → failed
                      → timed_out
```

**Rule:** `delivered` is written **last** — only after `chat_postMessage` (or equivalent side effect) returns success. Never write `delivered` optimistically at the start of a run.

### SQLite Schema (extends `~/.kamil-harness/harness.db`)

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,          -- sha256(source + ":" + event_id)
    event_id     TEXT NOT NULL,             -- Slack event_id or equivalent
    source       TEXT NOT NULL,             -- slack_mention | slack_dm | cron | orchestrator
    intent       TEXT,                      -- pr_review | question | task | nlm | chat | unknown
    raw_text     TEXT,                      -- triggering message text
    channel      TEXT,
    thread_ts    TEXT,
    sender_id    TEXT,
    status       TEXT NOT NULL DEFAULT 'received',  -- received | processing | delivered | failed | timed_out
    failure_reason TEXT,                    -- populated on failed/timed_out
    steps_total  INTEGER DEFAULT 1,
    steps_done   INTEGER DEFAULT 0,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL,
    delivered_at INTEGER                    -- NULL until delivered
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_event  ON jobs(event_id);
```

### Stale Job Detection

A background checker (runs every 5 minutes) marks jobs as `timed_out` if they have been `processing` for more than `STALE_THRESHOLD_SECONDS = 300`. Stale jobs are logged to Axiom + Notion Observability DB with `status=🔴 Needs Kamal`.

### Idempotency

Job IDs are derived from `sha256(source + ":" + event_id)`. Re-processing the same event is safe: `INSERT OR IGNORE` on the jobs table. The dedup DB fallback pattern is also fixed here — if the DB is unavailable, the event is still logged to the Axiom fallback file, not silently dropped.

---

## Section 2: Suppression Event Registry

### Rule

Every code path that can drop an inbound message MUST call `klog_suppression()` before returning. No silent drops.

### Reason Codes

| Code | Meaning |
|---|---|
| `self_message` | Message sent by the bot itself |
| `no_mention` | Message in a channel with no @Kamil mention |
| `channel_not_allowed` | Channel not in allowed list |
| `dm_not_authorized` | DM from unauthorized user |
| `rate_limited` | Handler is rate-limited |
| `intent_unknown` | No intent handler matched |
| `no_url_in_context` | PR review requested but no URL found in message or thread |
| `thread_fetch_failed` | Thread context fetch failed (non-fatal, logged and continues) |
| `handler_exception` | Handler threw an uncaught exception |
| `dedup_hit` | Event already processed (duplicate) |
| `budget_exhausted` | Execution timed out before delivery |

### `klog_suppression()` Signature

```python
def klog_suppression(
    event_id: str,
    reason_code: str,           # one of the codes above
    raw_text: str,
    channel: str = "",
    sender_id: str = "",
    job_id: str = "",           # if a job row was already created
    details: str = "",          # free-text additional context
) -> None
```

Writes to: Axiom `kamil-logs` (component=`listener`, event=`suppression`) + local fallback.

### Diagnostic Query

When Kamal reports "Kamil didn't respond":
```bash
python3 -c "
import sqlite3
conn = sqlite3.connect(os.path.expanduser('~/.kamil-harness/harness.db'))
rows = conn.execute('''
    SELECT event_id, reason_code, raw_text, created_at
    FROM suppression_log
    ORDER BY created_at DESC LIMIT 20
''').fetchall()
for r in rows: print(r)
"
```
Or grep Axiom: `component:listener AND event:suppression`.

### Suppression Log Table

```sql
CREATE TABLE IF NOT EXISTS suppression_log (
    id          TEXT PRIMARY KEY,
    event_id    TEXT,
    reason_code TEXT NOT NULL,
    raw_text    TEXT,
    channel     TEXT,
    sender_id   TEXT,
    job_id      TEXT,
    details     TEXT,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_suppression_event ON suppression_log(event_id);
CREATE INDEX IF NOT EXISTS idx_suppression_reason ON suppression_log(reason_code, created_at);
```

---

## Section 3: Full Thread Context Enrichment

### Rule

Every handler that processes a Slack event MUST fetch the full thread via `conversations.replies` before building the Claude prompt. The trigger message is a pointer — the thread is the spec.

### Implementation

```python
def fetch_thread_context(channel: str, thread_ts: str, web: WebClient) -> str:
    """
    Fetch full Slack thread and return as formatted string for Claude prompt.
    Never raises — on failure logs klog_suppression(reason='thread_fetch_failed')
    and returns empty string so the handler continues with what it has.
    """
    try:
        resp = web.conversations_replies(channel=channel, ts=thread_ts, limit=50)
        messages = resp.get("messages", [])
        lines = []
        for m in messages:
            user = m.get("user", "unknown")
            text = m.get("text", "")
            ts   = m.get("ts", "")
            lines.append(f"[{ts}] <{user}>: {text}")
        return "\n".join(lines)
    except Exception as e:
        klog_suppression(
            event_id=thread_ts,
            reason_code="thread_fetch_failed",
            raw_text="",
            channel=channel,
            details=str(e),
        )
        return ""
```

### PR Review Intent — URL Extraction

The root cause of the 12:55:57 failure: `@Kamil review this PR` contains no URL, but the PR URL was in Hammad's message earlier in the thread. The fix:

```python
def extract_pr_url(trigger_text: str, thread_context: str) -> str | None:
    """
    Look for a GitHub PR URL in trigger text first, then full thread.
    Returns first match or None.
    """
    import re
    pattern = r'https://github\.com/[^\s>)"]+'
    for text in [trigger_text, thread_context]:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None
```

If no URL is found after checking both trigger and thread, emit `klog_suppression(reason='no_url_in_context')` and reply to the thread: *"I couldn't find a PR URL in this thread — can you share the link?"*. Never silently drop.

### Prompt Injection

Thread context is injected into every Claude prompt under a `## THREAD HISTORY` section, replacing the existing `{thread_history or "(no prior messages)"}` placeholder that only carries context passed in by the caller (which is often empty for @mentions).

---

## Section 4: Multi-Step Milestone Logging

### Rule

Every multi-step operation logs each step. Pattern:

```python
klog_milestone(job_id, step_name, step_index, total_steps, status, details="")
```

`status` is `started | completed | failed`.

### Operations to Instrument

| Operation | File | Current state | Fix |
|---|---|---|---|
| Content pipeline | `kamil-slack-listener.py` | Step 1 + step 8 only | Log all 8 steps |
| PR review handler | `kamil-slack-listener.py` | No milestone logs | Log: fetch_thread → extract_url → fetch_diff → run_claude → post_comment |
| Orchestrator subagent | `orchestrator-dispatch.py` | Spawn logged, completion not verified | Log: spawn → session_start → plan_posted → approved → implement → pr_opened → notion_updated |
| save_conversation_to_notion | `kamil-slack-listener.py` | Thread start only | Log: thread_start → claude_call → notion_write → complete |
| proactive_loop | `kamil-slack-listener.py` | Response rejected silently | Log every rejection with reason |

### `klog_milestone()` Signature

```python
def klog_milestone(
    job_id: str,
    step_name: str,
    step_index: int,
    total_steps: int,
    status: str,           # started | completed | failed
    details: str = "",
) -> None
```

Writes to Axiom + updates `jobs.steps_done` in SQLite.

### Fire-and-Forget Thread Fix

Daemon threads that currently launch with no completion tracking are replaced with a `tracked_thread()` wrapper:

```python
def tracked_thread(job_id: str, fn, *args, **kwargs):
    """
    Run fn in a thread. On completion write delivered/failed to jobs table.
    """
    def _run():
        try:
            fn(*args, **kwargs)
            _mark_job_delivered(job_id)
        except Exception as e:
            _mark_job_failed(job_id, str(e))
            klog_error("tracked_thread", e, component="listener", severity="ERROR")
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t
```

---

## What This Fixes

| Incident | Root cause | Fix |
|---|---|---|
| "review this PR" — no response, no log | No suppression log; trigger text had no URL; thread not read | suppression registry + thread fetch + URL extraction from thread |
| Content pipeline "ran fine" but images missing | Steps 2–7 invisible | milestone logging for all 8 steps |
| Agent completed job but Notion status not updated | No job state machine; `delivered` never written | job state machine + `delivered` written last |
| Eval system orphaned pending actions | `eval_proactive_dm()` not called when Slack post fails | tracked_thread ensures failure path always fires |
| Can't diagnose "why no response" | No suppression log | suppression registry queryable in <1 second |
| Dedup DB silently degrades | No log when DB fails, in-memory fallback loses on restart | log dedup degradation; persist to fallback file |

---

## Files to Create/Modify

```
.claude/hooks/kamil_context.py          — add: jobs table, suppression_log table, klog_suppression(), klog_milestone(), fetch_thread_context(), extract_pr_url(), tracked_thread(), stale_job_checker()
.claude/hooks/kamil-slack-listener.py  — modify: wire job state machine, suppression registry, thread fetch, PR URL extraction, milestone logging, tracked_thread for daemon threads
.claude/hooks/orchestrator-dispatch.py — modify: milestone logging for subagent lifecycle
.claude/hooks/kamil_log.py             — modify: add klog_suppression(), klog_milestone() event types
```

---

## Research Sources

- [5 Silent Failure Modes in Production AI Agents — DEV.to](https://dev.to/zvone187/5-silent-failure-modes-in-production-ai-agents-and-how-we-instrument-for-them-oca)
- [Your Agent Isn't Crashing, It's Lying — Sentrial](https://www.sentrial.com/blog/ai-for-observability-your-agent-isnt-crashing-its-lying)
- [AI Agent Observability — OpenTelemetry](https://opentelemetry.io/blog/2025/ai-agent-observability/)
- [Slack Events API Acknowledgement — QuestionBase](https://www.questionbase.com/resources/blog/slack-events-api-acknowledgement-requirements-what-every-developer-needs-to-know)
- [Error Handling and Resilience — Vercel Academy](https://vercel.com/academy/slack-agents/error-handling-and-resilience)
- [Context Window Overflow — Redis Blog](https://redis.io/blog/context-window-overflow/)
- [Heartbeat Pattern for AI Agents — MindStudio](https://www.mindstudio.ai/blog/heartbeat-pattern-ai-agent-systems)
- [Understanding Agent Behavior in Production — Vellum.ai](https://www.vellum.ai/blog/understanding-your-agents-behavior-in-production)
