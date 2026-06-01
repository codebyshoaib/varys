---
type: reference
last_verified: 2026-06-01
owner: kamil
paths:
  - ".claude/hooks/*.py"
---

# Observability Contract

All hooks log via `kamil_log.py` (typed events → Axiom `kamil-logs` + /tmp fallback).
Every event carries: schema_version, severity, component, event, trace_id, host, pid.

## Sinks
- Axiom: ALL events. Query with APL.
- Notion "Kamil Observability" DB (8b0f5754470540dfb832a61380a2a9b9): signal only (ERROR/FATAL, self-heal, daily digest) with Status (🔴 Needs Kamal / 🟡 Pending / 🟢 Solved / ⚪ Monitoring).
- /tmp/kamil-axiom-fallback.jsonl: fallback; /tmp/kamil-notion-queue.jsonl: MCP-flush queue.

## Self-healing
`kamil-observer.py` (hourly at :15): detect anomalies → diagnose → auto-fix within the fence / escalate.
Fence (never auto-fixed): secrets, settings.json, crontab, listener daemon, migrations.
Kill switch: `touch ~/.claude/hooks/.observer-paused`.

## Adding a new hook
Import kamil_log; call the right klog_* (klog_cron for crons, klog_external for API calls,
klog_error for failures). Route the cron through cron-wrap.sh. Never let logging raise.
