---
type: reference
last_verified: 2026-06-01
owner: kamil
---

# Retrieval Policy

## L1 — always
- CLAUDE.md ; open beads (last 10 from `.beads/status.jsonl`)

## L2 — load one, by task type
- Notion/work context → `.claude/rules/notion.md`
- Slack → `.claude/rules/slack.md`
- taleemabad-core → `.claude/rules/taleemabad.md`
- Content → `.claude/rules/content.md`
- Any issue type → `.claude/rules/skills-router.md`

## L3 — only when blocked
- The one doc that unblocks the task; max 2-3 per session. Personality → `vault/memory/kamil_personality.md`.

## Never auto-load
- Archives, full changelogs, completed investigations, full work-log history.
