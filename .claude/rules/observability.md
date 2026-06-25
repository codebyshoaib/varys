---
type: reference
last_verified: 2026-06-01
owner: varys
paths:
  - ".claude/hooks/*.py"
---

# Observability Contract

All hooks log via `varys_log.py` (typed events → local telemetry log, one JSON object per line).
Every event carries: schema_version, severity, component, event, trace_id, host, pid.

## Sinks
- `~/.varys-harness/telemetry.jsonl`: ALL events (the firehose). Persistent across reboots. Query with `jq`. (Axiom was removed 2026-06-25 — it was unused, no token was ever configured.)
- Notion "{{AGENT_NAME}} Observability" DB ({{config:NOTION_OBSERVABILITY_DB_ID}}): signal only (ERROR/FATAL, self-heal, daily digest) with Status (🔴 Needs {{USER_NAME}} / 🟡 Pending / 🟢 Solved / ⚪ Monitoring).
- /tmp/varys-notion-queue.jsonl: MCP-flush queue.

`varys-observer.py` and `varys-self-healer.py` read `telemetry.jsonl` for recent ERROR/FATAL events.

## Self-healing
`varys-observer.py` (hourly at :15): detect anomalies → diagnose → auto-fix within the fence / escalate.
Fence (never auto-fixed): secrets, settings.json, crontab, listener daemon, migrations.
Kill switch: `touch ~/.claude/hooks/.observer-paused`.

## Adding a new hook
Import varys_log; call the right klog_* (klog_cron for crons, klog_external for API calls,
klog_error for failures). Route the cron through cron-wrap.sh. Never let logging raise.
