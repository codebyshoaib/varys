---
type: reference
last_verified: 2026-06-01
owner: kamil
paths:
  - ".claude/hooks/*.py"
  - "vault/**"
---

# Notion Brain — Databases & MCP Queries

All Notion reads/writes use `mcp__claude_ai_Notion__*` tools (no API key file). **When {{USER_NAME}} asks about work context → fetch Notion via MCP first, then the Slack inbox file if needed.**

## Retrieval and Write Rules
Retrieval and write rules are defined in `.claude/hooks/kamil_context.py` — do not re-specify here.

## Databases

| DB | ID | Purpose |
|---|---|---|
| Open PRs | `{{config:NOTION_MY_PRS_DB_ID}}` | PRs, CI state, review status |
| Slack Inbox | `{{config:NOTION_INBOX_DB_ID}}` | Classified messages needing action |
| Last Work Log | `{{config:NOTION_WORK_LOG_DB_ID}}` | Daily session summaries |
| Harness backlog | `{{config:NOTION_HARNESS_DB_ID}}` | {{AGENT_NAME}}'s feature backlog + self-evolution |
| People Intelligence | `{{config:NOTION_PEOPLE_DB_ID}}` | Mood, needs, recurring topics, what works |
| Job Tracker | `{{config:NOTION_JOBS_DB_ID}}` | Job finds + application status |
| Observability | `{{config:NOTION_OBSERVABILITY_DB_ID}}` | Errors, self-heal actions, daily digest — Status: 🔴 Needs {{USER_NAME}} / 🟡 Pending / 🟢 Solved / ⚪ Monitoring. Firehose in Axiom `kamil-logs`. |
| Canva Designs | `{{config:NOTION_CANVA_DB_ID}}` | Canva design assets — topic, channel, format, eval scores, asset URLs, status (draft/approved/posted/Needs-{{USER_NAME}}). Under Social Media Growth Plan. |

Other DBs referenced by name only: Projects, {{USER_NAME}}'s Todo, {{AGENT_NAME}}'s Learning Log.

## Self-Questions (personality building)
Notion page "{{AGENT_NAME}} Self-Questions" under 🧠 {{USER_NAME}}'s Agent Brain. Explored each 30-min cycle with real data: What is {{USER_NAME}} blocked on? Which PR needs attention most? What did the team ship? What is [team member] working on? Biggest sprint risk? What hasn't {{USER_NAME}} responded to? What patterns repeat in the work log?
