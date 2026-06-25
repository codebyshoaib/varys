---
type: reference
last_verified: 2026-06-01
owner: varys
paths:
  - ".claude/hooks/*.py"
---

# Observability Contract

All hooks log via `varys_log.py` (typed events → Axiom `varys-logs` + persistent local fallback).
Every event carries: schema_version, severity, component, event, trace_id, host, pid.

## Sinks
- Axiom: ALL events. Query with APL.
- Notion "{{AGENT_NAME}} Observability" DB ({{config:NOTION_OBSERVABILITY_DB_ID}}): signal only (ERROR/FATAL, self-heal, daily digest) with Status (🔴 Needs {{USER_NAME}} / 🟡 Pending / 🟢 Solved / ⚪ Monitoring).
- ~/.varys-harness/axiom-fallback.jsonl: fallback (persistent across reboots; the ONLY sink when no Axiom token is configured); /tmp/varys-notion-queue.jsonl: MCP-flush queue.

## Self-healing
`varys-observer.py` (hourly at :15): detect anomalies → diagnose → auto-fix within the fence / escalate.
Fence (never auto-fixed): secrets, settings.json, crontab, listener daemon, migrations.
Kill switch: `touch ~/.claude/hooks/.observer-paused`.

## Adding a new hook
Import varys_log; call the right klog_* (klog_cron for crons, klog_external for API calls,
klog_error for failures). Route the cron through cron-wrap.sh. Never let logging raise.
