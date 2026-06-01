---
type: plan
last_verified: 2026-06-01
owner: kamil
status: active
---

# Kamil Observability & Self-Healing Harness

**Goal:** Every possible event in the Kamil harness is captured as an industry-standard
structured log, queryable in Axiom, surfaced in Notion with an explicit lifecycle status,
and fed into a self-healing loop that detects → diagnoses → auto-fixes (within a safety
fence) or escalates to Kamal. No more raw `/tmp/*.log` dumps.

---

## Why

`kamil_log.py` already ships typed JSON to Axiom (`kamil-logs`) with a `/tmp` fallback —
but only **14 of 35 hooks** use it, it lacks severity/trace correlation, crons still dump
to raw `/tmp/*.log`, and nothing reads the telemetry back to improve the system.
Kamal's requirement: logs detailed enough that the harness can **solve itself and improve**,
mirrored into **Notion** so every issue shows **what it was** and whether it's
**Solved / Pending / Needs-Kamal-attention**.

---

## Three sinks, by purpose

| Sink | Holds | Why |
|---|---|---|
| **Axiom** `kamil-logs` | ALL events (firehose) | High-volume, queryable telemetry (APL) |
| **Notion "Kamil Observability"** | Signal only: ERROR/FATAL, self-heal actions, escalations, daily digest | The human-readable view Kamal actually reads, with lifecycle status |
| `/tmp/kamil-axiom-fallback.jsonl` | Everything, local | Fallback only — survives if Axiom/Notion unreachable |

Raw crontab `>> /tmp/kamil-*.log` redirects are **replaced** by structured `cron_run` events.

---

## Pillar 1 — The event envelope (OTel-aligned)

Every event from every hook carries:

```
schema_version  "1.0"                         (lets analyzers evolve safely)
_time           ISO8601 (Axiom indexes ingest time; kept only in fallback)
severity        DEBUG | INFO | WARN | ERROR | FATAL
component       listener | poller | job-finder | content | self-healer | ...
event           typed name (conversation, claude_call, cron_run, external_call, ...)
trace_id        correlates a whole operation (e.g. one Slack message end-to-end)
span_id         this step within the trace
parent_span_id  call tree
session_id      process run
host, pid       resource attributes
duration_ms     for any timed op
```

Errors are **structured objects**, never bare strings:
`error_type`, `error_msg`, `traceback`, `context` (dict).

---

## Pillar 2 — Coverage (every possible log: 14/35 → 35/35)

| Hook class | Events instrumented |
|---|---|
| Listener | `conversation`, `claude_call`, `socket_*`, `privacy_filtered`, `humor_interaction`, `message_catchup` + trace_id threading + a span per sub-call (thread fetch → claude → privacy → slack send) |
| All crons (poller, job-finder, content-scheduler, self-healer, notion-map, daily/weekly/learn) | `cron_run` start/end: rc, duration_ms, items processed, error summary |
| PreToolUse hooks (block-bad-commands, guard-file-writes) | `policy_block`: what was blocked + why |
| External calls (Slack, Notion MCP, GitHub, Kie.ai, OpenOutreach, LinkedIn, NotebookLM) | `external_call`: target, status, latency_ms, retry_count |
| Lifecycle (session-start, stop, project-detect) | `system_start`, `session_end`: context loaded |
| Beads/eval | `bead_opened`, `bead_closed`, `eval_run` (pass/fail + 6 SLOs) |

Duplicate `.py` files: instrument the **canonical spelling only**; leave dupes (logged-not-deleted).

---

## Pillar 3 — Notion "Kamil Observability" DB

New database. One row per incident/action. Properties:

| Property | Type | Values |
|---|---|---|
| Title | title | short incident name |
| Severity | select | DEBUG / INFO / WARN / ERROR / FATAL |
| Component | select | listener / poller / job-finder / … |
| Event | text | typed event name |
| Trace ID | text | jump to the full story in Axiom |
| Root Cause | text | observer's diagnosis |
| **Status** | **select** | **🔴 Needs Kamal · 🟡 Pending · 🟢 Solved · ⚪ Monitoring** |
| Action Taken | text | "auto-fixed: created missing dir, commit abc123" / "proposed patch, awaiting approval" |
| Resolution | text | what fixed it + how to verify |
| Detected | date | first seen |
| Resolved | date | when closed |

**Lifecycle is enforced:** observer detects → writes 🟡 Pending → auto-fix flips to
🟢 Solved (commit + verification) → can't fix → 🔴 Needs Kamal (with proposed patch).
Kamal opens the DB and sees every issue, what it was, and whether it's done or waiting on him.

---

## Pillar 4 — Self-healing loop (`kamil-observer.py`)

Runs hourly (cron) + immediately when any ERROR/FATAL event lands.

```
1. QUERY Axiom (APL): last hour — error spikes, latency regressions, crash loops,
   anomalies vs. 7-day baseline.
2. DIAGNOSE each pattern → root cause (read traceback + the failing hook's source).
3. CLASSIFY & ACT:
   - Clear root cause AND outside the hard-exclusion fence → AUTO-FIX:
       reversible commit, re-run the hook to verify, write/flip Notion row → 🟢 Solved, DM Kamal.
   - In the fence OR low confidence → ESCALATE:
       .beads/failures.jsonl + matching eval task + Notion row → 🔴 Needs Kamal + proposed patch + DM.
4. LEARN: every incident → failures.jsonl + eval task (closes the self-improving loop).
```

### Hard-exclusion fence — auto-fix NEVER touches these (always escalate)
- `~/.claude/hooks/.slack`, `.axiom`, any `.env`/secret
- `.claude/settings.json`
- crontab
- `kamil-slack-listener.py` control flow
- anything the PreToolUse hook already blocks
- DB migrations

Kamal chose "auto-fix anything with a clear root cause" — honored, but **only within this
fence**, because a confident-but-wrong diagnosis editing a fenced item could brick the harness.

### Kill switch
`~/.claude/hooks/.observer-paused` (file exists) → observer logs + escalates but performs
**no** auto-fix. Instant manual off-switch.

---

## Risks & what NOT to break

- **Logger must never raise.** Already fire-and-forget; instrumenting 21 hooks adds logging
  *around* logic, never in a path that can throw. Verify each hook still runs unchanged.
- **Auto-fix is the real risk** — mitigated by the fence, reversible per-fix commits,
  re-run verification, immediate DM, and the kill switch.
- **Notion volume** — only signal goes to Notion (errors + self-heal + daily digest), never
  the firehose. Axiom holds everything.
- **Don't double-instrument** duplicate `.py` files.
- **Don't restart the listener daemon** automatically as part of this work (Kamal's call).

---

## Definition of done

- [ ] `kamil_log.py` extended: severity, trace_id/span_id/parent_span_id, schema_version, host/pid, duration_ms, structured errors — backward compatible (existing `klog_*` calls still work)
- [ ] All 35 hooks emit structured events (canonical spellings); 0 raw `print`-only logging paths in cron scripts
- [ ] Crontab `>> /tmp/kamil-*.log` replaced by a structured `cron_run` wrapper
- [ ] New event types added: `cron_run`, `external_call`, `policy_block`, `bead_opened/closed`, `eval_run`, `session_end`
- [ ] Notion "Kamil Observability" DB created with the 11 properties incl. Status workflow
- [ ] `kamil-notion-sink.py` mirrors signal events → Notion with correct Status
- [ ] `kamil-observer.py` built: hourly cron + ERROR trigger; detect → diagnose → auto-fix (fenced) / escalate; updates Notion Status; writes failures.jsonl + eval task
- [ ] Hard-exclusion fence enforced + tested (a fenced incident escalates, never auto-fixes)
- [ ] Kill switch works (`.observer-paused` disables auto-fix)
- [ ] All 6 cron files + listener still run; nothing broken; changes committed incrementally
