---
type: rule
owner: kamil
last_verified: 2026-06-03
---

# Team Orchestrator — Rules & Design Contracts

Kamil is the team's AI engineer. He picks up work from Notion, Slack, and GitHub
and handles it autonomously — but never writes code without human approval of a plan first.

## Hard Rules (never break)

1. **context_key is ALWAYS a Notion ticket entity ID** — never a Slack thread ts or PR number.
   Slack mentions → create stub Notion ticket → use that ticket's entity ID as context_key.

2. **Status=Done is written LAST** — it is the commit signal. If anything fails after
   implementation but before Status update, the ticket stays In progress and retries next tick.

3. **350ms between Notion API calls** — use `kamil_notion.notion_request()` everywhere.
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

7. **Tick interval = 270s** — never change without asking Kamal explicitly.

8. **One session per context_key** — if `status='running'` session exists for a context_key,
   skip it entirely this tick. No parallel sessions on the same ticket.

9. **Plan-first for all implementation** — subagents NEVER write code without human approval:
   - Step A: read code → draft plan + E2E test cases → post to Slack → set Status=Blocked → exit
   - Step B: only triggered by "@Kamil go" reply → implement → E2E → PR → Status=Done LAST

10. **E2E gate before every PR** — no `gh pr create` without running e2e tests.
    Pass → open PR normally. Fail after 5 attempts → open PR with failure report + Status=Blocked.

## Event Type Taxonomy

```
From Notion:
  ticket.created      → new ticket assigned to Kamil / matching filter
  comment.tagged      → comment on Notion page containing @Kamil

From Slack:
  message.tagged      → @Kamil mention in an engineering channel

From GitHub:
  pr.review_commented → review comment on an agent-opened PR
  pr.merged           → agent-opened PR merged → set Notion Status=Done
  pr.closed           → agent-opened PR closed (not merged) → Status=Blocked
```

## Required Env Vars

```
NOTION_API_KEY          — Notion integration token
NOTION_DATABASE_ID      — Kamil Harness DB (de10157da3e34ef58a74ea240f31fe98)
NOTION_AGENT_USER_ID    — Kamil's Notion user ID (for assignee filter)
SLACK_BOT_TOKEN         — xoxb- token (posting)
SLACK_USER_TOKEN        — xoxp- token (search.messages — bot token alone fails)
GITHUB_TOKEN            — PAT with repo scope
GITHUB_REPO             — Orenda-Project/taleemabad-core
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

`~/.kamil-harness/workspace/` = local checkout of taleemabad-core (not committed).
Subagents operate here. Always on `develop` branch at tick start.

## Files

```
.claude/hooks/kamil_harness_db.py        — DB + tick lock + entity registry
.claude/hooks/kamil_notion.py            — shared Notion rate-limit utility
.claude/hooks/poll-harness-notion.py     — Notion Harness DB poller
.claude/hooks/poll-eng-slack.py          — engineering Slack channel poller
.claude/hooks/poll-taleemabad-github.py  — GitHub PR poller (entity-filtered)
.claude/hooks/orchestrator-dispatch.py  — dispatcher + subagent spawner
~/.kamil-harness/harness.db             — SQLite state (tick_lock, events, entities, links, sessions)
~/.kamil-harness/workspace/             — taleemabad-core checkout
```

## Escalation Protocol

A ticket is "stuck" when its session status has been `cancelled` or `blocked`
for 2+ consecutive ticks without a new `running` session.

```
Tick 1–2 blocked  → normal retry (existing behavior)
Tick 3+ blocked   → escalation-broker.py fires automatically
    ↓
Broker: partial delivery → try different angle → structured DM to Kamal
    ↓
Kamal replies in thread
    ↓
Listener detects reply-on-blocked-thread → creates event IMMEDIATELY
Dispatcher processes it on the NEXT available tick (not waiting 270s)
```

**Hard rules (additions to existing list):**

11. **Nothing silently rots.** If a ticket has been `cancelled`/`blocked` for 2+ ticks,
    `escalation-broker.py` must have fired. Check the session log if it hasn't.
12. **Kamal replies are fast-pathed.** When the listener detects a reply in a thread
    where the linked Notion ticket is `Blocked`, it inserts the event with
    `priority='high'` and the dispatcher skips the 270s wait for that context_key.
13. **Evolution fires on failure accumulation.** After every tick, `kamil-evolution-agent.py`
    checks failures.jsonl. If 3+ new entries since last run → fires the evolution agent.
