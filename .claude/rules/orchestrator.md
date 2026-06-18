---
type: rule
owner: varys
last_verified: 2026-06-03
---

# Team Orchestrator — Rules & Design Contracts

{{AGENT_NAME}} is the team's AI engineer. He picks up work from Notion, Slack, and GitHub
and handles it autonomously — but never writes code without human approval of a plan first.

## Hard Rules (never break)

1. **context_key is ALWAYS a ticket entity ID** (Notion ticket or bead) — never a Slack thread ts
   or PR number. The orchestrator does NOT ingest Slack — that's the real-time listener's job.

2. **Status=Done is written LAST** — it is the commit signal. If anything fails after
   implementation but before Status update, the ticket stays In progress and retries next tick.

3. **350ms between Notion API calls** — use `varys_notion.notion_request()` everywhere.
   Never call `urllib.request.urlopen()` directly against Notion.

4. **Deterministic event IDs** — always derived from source + external_id:
   - Notion:  `notion-<page_id>`,  `notion-comment-<comment_id>`
   - Slack:   `slack-<channel_id>-<message_ts>`
   - GitHub:  `github-taleemabad-core-<pr_num>-<type>`
   Re-polling is always safe because INSERT OR IGNORE on primary key handles duplicates.

5. **Two-query pattern for events** — never GROUP_CONCAT JSON payloads (commas break it):
   ```sql
   -- Step 1: distinct context keys
   SELECT DISTINCT context_key FROM events WHERE status='pending';
   -- Step 2: full rows per key
   SELECT id, source, type, payload FROM events WHERE context_key=? AND status='pending';
   ```

6. **Tick atomicity** — if ANY poller fails during a tick:
   - Release tick lock immediately
   - Do NOT update `last_sync_at`
   - Exit — everything retries next tick (safe because event IDs are deterministic)

7. **Tick interval = 270s** — never change without asking {{USER_NAME}} explicitly.

8. **One session per context_key** — if `status='running'` session exists for a context_key,
   skip it entirely this tick. No parallel sessions on the same ticket.

9. **Plan-first for all implementation** — subagents NEVER write code without human approval:
   - Step A: read code → draft plan + E2E test cases → post to Slack → set Status=Blocked → exit
   - Step B: only triggered by "@{{AGENT_NAME}} go" reply → implement → E2E → PR → Status=Done LAST

10. **E2E gate before every PR** — no `gh pr create` without running e2e tests.
    Pass → open PR normally. Fail after 5 attempts → open PR with failure report + Status=Blocked.

## Event Type Taxonomy

```
From Notion / beads:
  ticket.created      → new ticket assigned to {{AGENT_NAME}} / matching filter (Notion or `bd ready`)
  comment.tagged      → comment on Notion page containing @{{AGENT_NAME}}

From Slack (real-time listener only — NOT polled):
  message.go_signal   → Shoaib (and ONLY Shoaib) replies "go"/"approve"/"proceed" on a plan
                        thread → listener inserts this event → dispatch fires Phase 2 (worker).
                        Non-Shoaib "go" is refused in-thread. This is the sole Slack→orchestrator
                        event; ordinary mentions are answered by slack-worker, never reach here.

Slack work-request lifecycle (anyone may request; only Shoaib approves):
  @Varys "fix X in <repo>" → slack-worker mints an origin-tagged bead (links the bead's
  context_key to the Slack thread) + posts an ack IN THAT THREAD → poll-beads → ticket.created
  → manager plans IN THAT THREAD, Status=awaiting_approval → Shoaib "go" → implement → PR,
  all reported back in the same thread. Origin link means no channel guessing.

From GitHub:
  pr.review_commented → review comment on an agent-opened PR
  pr.merged           → agent-opened PR merged → set Notion Status=Done
  pr.closed           → agent-opened PR closed (not merged) → Status=Blocked
```

## Required Env Vars

```
NOTION_API_KEY          — Notion integration token
NOTION_DATABASE_ID      — {{AGENT_NAME}} Harness DB ({{config:NOTION_HARNESS_DB_ID}})
NOTION_AGENT_USER_ID    — {{AGENT_NAME}}'s Notion user ID (for assignee filter)
SLACK_BOT_TOKEN         — xoxb- token (posting results to a ticket's origin thread / DM)
# SLACK_USER_TOKEN no longer used by the tick (was for poll-eng-slack search.messages).
# Still consumed by other Slack hooks (proactive watch, daily digest).
GITHUB_TOKEN            — PAT with repo scope
GITHUB_REPO             — {{YOUR_GITHUB_ORG}}/{{YOUR_REPO}}
GITHUB_AGENT_LOGIN      — GitHub username of agent account
```

## Required Notion DB Properties

Must exist in Harness DB before first tick:

| Property | Type |
|---|---|
| `Status` | Status: Not started / In progress / Done / Blocked / In review / Cancelled |
| `Agent Session ID` | Rich Text |
| `Last Agent Update` | Date |
| `GitHub PR` | URL |
| `Slack Thread` | URL |

## Workspace

`~/.varys-harness/workspace/` = local checkout of taleemabad-core (not committed).
Subagents operate here. Always on `develop` branch at tick start.

## Files

```
.claude/hooks/varys_harness_db.py        — DB + tick lock + entity registry
.claude/hooks/varys_notion.py            — shared Notion rate-limit utility
.claude/hooks/poll-beads.py              — bd ready poller (active tick poller)
.claude/hooks/poll-harness-notion.py     — Notion Harness DB poller
.claude/hooks/poll-taleemabad-github.py  — GitHub PR poller (entity-filtered, active tick poller)
# poll-eng-slack.py — DELETED. Slack intake is the real-time listener's job, not polled.
.claude/hooks/orchestrator-dispatch.py  — dispatcher + subagent spawner
~/.varys-harness/harness.db             — SQLite state (tick_lock, events, entities, links, sessions)
~/.varys-harness/workspace/             — taleemabad-core checkout
```

## Escalation Protocol

A ticket is "stuck" when its session status has been `cancelled` or `blocked`
for 2+ consecutive ticks without a new `running` session.

```
Tick 1–2 blocked  → normal retry (existing behavior)
Tick 3+ blocked   → escalation-broker.py fires automatically
    ↓
Broker: partial delivery → try different angle → structured DM to {{USER_NAME}}
    ↓
{{USER_NAME}} replies in thread
    ↓
Listener detects reply-on-blocked-thread → creates event IMMEDIATELY
Dispatcher processes it on the NEXT available tick (not waiting 270s)
```

**Hard rules (additions to existing list):**

11. **Nothing silently rots.** If a ticket has been `cancelled`/`blocked` for 2+ ticks,
    `escalation-broker.py` must have fired. Check the session log if it hasn't.
12. **{{USER_NAME}} replies are fast-pathed.** When the listener detects a reply in a thread
    where the linked Notion ticket is `Blocked`, it inserts the event with
    `priority='high'` and the dispatcher skips the 270s wait for that context_key.
13. **Evolution fires on failure accumulation.** After every tick, `varys-evolution-agent.py`
    checks failures.jsonl. If 3+ new entries since last run → fires the evolution agent.
