---
type: reference
last_verified: 2026-06-01
owner: kamil
paths:
  - ".claude/hooks/*.py"
  - "vault/**"
---

# Notion Brain — Databases & MCP Queries

All Notion reads/writes use `mcp__claude_ai_Notion__*` tools (no API key file). **When Kamal asks about work context → fetch Notion via MCP first, then the Slack inbox file if needed.**

## Databases

| DB | ID | Purpose |
|---|---|---|
| Open PRs | `18017a67136a4561ada9818c239b8f33` | PRs, CI state, review status |
| Slack Inbox | `6d14f1b6b8cd4ff68fd40efdfc3f304e` | Classified messages needing action |
| Team People / focus | `c976d58ea4e34b0585f245529cdc4528` | Teammate roles + current focus (canonical: People Intelligence) |
| Last Work Log | `0b71db855f914d18ac6d97c0f77fc21e` | Daily session summaries |
| Harness backlog | `de10157da3e34ef58a74ea240f31fe98` | Kamil's feature backlog + self-evolution |
| People Intelligence | `c976d58ea4e34b0585f245529cdc4528` | Mood, needs, recurring topics, what works |
| Job Tracker | `0d69c6ff-83d8-44c7-94c2-d341c4ded8d7` | Job finds + application status |
| Observability | `8b0f5754470540dfb832a61380a2a9b9` | Errors, self-heal actions, daily digest — Status: 🔴 Needs Kamal / 🟡 Pending / 🟢 Solved / ⚪ Monitoring. Firehose in Axiom `kamil-logs`. |
| Canva Designs | `076960e8f8a84c618e23a4a74a950b48` | Canva design assets — topic, channel, format, eval scores, asset URLs, status (draft/approved/posted/Needs-Kamal). Under Social Media Growth Plan. |

Other DBs referenced by name only: Projects, Kamal's Todo, Kamil's Learning Log.

## Self-Questions (personality building)
Notion page "Kamil Self-Questions" under 🧠 Kamal's Agent Brain. Explored each 30-min cycle with real data: What is Kamal blocked on? Which PR needs attention most? What did the team ship? What is Haroon Yasin working on? Biggest sprint risk? What hasn't Kamal responded to? What patterns repeat in the work log?
