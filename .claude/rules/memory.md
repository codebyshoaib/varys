# Memory — Varys's Queryable Archive (engram)

Varys has a persistent, queryable archive in **engram** (project `varys`, local SQLite at
`~/.engram/engram.db`). It holds what Varys has learned and lived: **lessons, decisions,
failures, people/relationships, and an event log** (what happened, when, by whom). It is
populated automatically — `varys-session-review.py` dual-writes each session's summary +
lessons, and the historical corpus (learnings, beads decisions/failures/interactions,
vault logs, the brain.db team directory) was backfilled.

> **Reach for the archive BEFORE free-soloing or answering from guess.** If the answer is
> "something we already decided / learned / did / a person on the team", query engram first.

## How to query

| Context | How |
|---|---|
| Interactive agent (this session, Varys sessions) | `mem_search` MCP tool (`mcp__engram__mem_search`), `mem_context` for recent history |
| Autonomous (`claude -p`, crons, Slack listener) | `~/.local/bin/engram search "<query>" --project varys [--limit N] [--type TYPE]` |

Types: `lesson`, `decision`, `failure`, `event`, `person`.

## When to query

- "What did we decide about X / why did we choose Y?" → `--type decision`
- "Who is X? How do I reach them? Who's on <team>?" → `--type person` (name / channel / email / title)
- "What happened on <date> / who did <thing>?" → `--type event` (query the date or actor)
- "Have we hit this failure / made this mistake before?" → `--type failure` (or a lesson)

## It is keyword search (FTS), not semantic — query accordingly

There is no embedding provider configured (no API key needed, nothing to set up), so search
matches **words that actually appear in the record**, not paraphrase.

- Query with terms likely IN the record: **names, dates, the topic's own words**, the other
  person's phrasing — not an abstract restatement.
  - Good: `beads source of truth Notion mirror` · `screen flickering 2026-06-30` · `Iqra engineering`
  - Weak: `who leads HR` · `engineering team members` (no shared words → misses)
- If the first phrasing returns "No memories found", **try one or two other keyword sets**
  before concluding it's not there. Absence on one phrasing is not absence.

## Writing to the archive

Don't hand-write routinely — `varys-session-review.py` captures sessions automatically.
For a deliberate save: `~/.local/bin/engram save "<title>" "<body>" --type <type> --project varys`
(interactive: `mem_save`). Exact duplicates are rejected.
