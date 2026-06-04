# Kamil Manager-Orchestrator Design

**Date:** 2026-06-04  
**Owner:** Kamal  
**Status:** Approved — ready for implementation planning

---

## Problem

The current Kamil orchestrator is a solo worker: every task spawns a single subagent that reads context, plans, codes, posts to Slack, and opens PRs — all in one session with no separation of concerns. There is no manager layer. Kamil has no judgment about *what* to delegate, *to whom*, or *how to improve* over time. Skills and agent capabilities are hardcoded, not living.

---

## Goal

Transform Kamil into a true manager-orchestrator:
- Kamil holds the big picture, delegates the actual work, owns the outcome
- Every capability is backed by a living skill file that grows with each interaction
- Kamil interacts with the whole team on Slack, not just Kamal
- Kamil evolves — detecting its own gaps, proposing new agents/skills, improving the harness

---

## Decisions Made

| Question | Decision |
|---|---|
| Slack interaction scope | Option C — reactive by default, proactive on configured channels |
| Subagent roster | Option C — core team of 6 always-available + on-demand specialists |
| Approval flow | Option B — two-phase: manager plans → human approves → worker executes |
| Slack autonomy | Option A — full autonomy, Kamil is a real team member |
| Self-learning | Option A — silent background logging to files + Notion |
| New agent/skill gate | Proposal → Kamal approves via Slack reply |

---

## Architecture

### Core Flow

```
Event (Notion / Slack / GitHub / proactive scan)
        ↓
poll-* pollers → harness.db
        ↓
orchestrator-dispatch.py (tick lock, session guard)
        ↓
kamil-manager.py  [PHASE 1]
  1. reads full context
  2. reads relevant skill files + gap files
  3. determines real intent
  4. picks right agent from core team or specialist catalog
  5. writes delegation brief (task + context + definition of done)
  6. posts Phase 1 plan to Slack
  7. sets Notion Status=Blocked, session status='awaiting_approval'
        ↓
  @Kamil go  (from Kamal or any team member)
        ↓
Worker agent executes with manager's brief  [PHASE 2]
        ↓
kamil-manager.py  [SYNTHESIS PASS]
  - quality checks worker output vs definition of done
  - updates relevant skill file (what worked / what to avoid)
  - updates gap files if anything went wrong
  - delivers final result to Slack as Kamil
  - sets Notion Status=Done LAST
```

### New Files

```
.claude/hooks/kamil-manager.py           — manager process (new)
.claude/hooks/poll-proactive-slack.py    — proactive channel watcher (new)
.claude/rules/proactive-channels.md      — watched channels + keywords (new)
.claude/agents/                          — core team agent .md files (new)
  research-agent.md
  code-agent.md
  content-agent.md
  slack-agent.md
  notion-agent.md
  people-agent.md
.claude/skills/kamil/                    — living skill files (new)
  humor.md
  content-posting.md
  slack-replies.md
  communication.md
  pr-review.md
  management.md
  helping-team.md
  research.md
  routing.md
  kamal-gaps.md
  kamil-self-gaps.md
  harness-evolution.md
```

### Unchanged

- `orchestrator-dispatch.py` — tick loop, session guard, event polling unchanged
- `harness.db` schema — one new session status value: `awaiting_approval`
- All existing pollers — untouched
- taleemabad-core agents — still used by code-agent as specialists

---

## Core Team

| Agent | Role | When Kamil picks it |
|---|---|---|
| `research-agent` | Web search, deep research, NLM queries, competitive intel | "find out / research / compare / what's the best" |
| `code-agent` | Reads/writes code, opens PRs, runs tests, delegates to taleemabad specialists | Code, PR, bug, test, implementation |
| `content-agent` | LinkedIn posts, scripts, carousels, NotebookLM content pipeline | "post / write / create content / carousel" |
| `slack-agent` | Slack lookups, DMs, channel posts, thread replies | "message X / notify team / post in #Y" |
| `notion-agent` | Notion reads/writes, ticket management, DB queries | Notion ticket, update status, query DB |
| `people-agent` | Team context, who is who, relationship memory | "who is X / what did X say / how does X prefer" |

**On-demand specialists** (spawned when core team can't handle):
- `security-auditor`, `data-agent`, `devops-agent`
- Any agent from the VoltAgent catalog by name

**Routing rules** live in `.claude/skills/kamil/routing.md` and grow with each session.

---

## Living Skills System

Every capability Kamil exercises is backed by a skill file. Skills grow after every interaction.

### Skill File Structure

```markdown
# [Skill Name]
## Core Rules
[stable, approved principles]

## What Works
- [date] lesson learned from real interaction

## What to Avoid
- [date] what went wrong and why

## Person-Specific Notes (where relevant)
- Name: preference
```

### Skill Update Loop

```
Task completes
        ↓
Manager scores: did this go well?
  (signals: Kamal said "good", team replied positively, 
   PR merged clean, no follow-up corrections needed)
        ↓
Yes → append 1-line "what worked" to relevant skill file
No  → append 1-line "what to avoid" + log to .beads/failures.jsonl
        ↓
Next similar task → manager reads skill file first
```

### Special Skill Files

**`kamal-gaps.md`** — Kamal's blind spots and patterns:
- Knowledge gaps (questions asked 2+ times)
- Recurring mistakes (patterns from PRs and decisions)
- Communication gaps (where Kamal's intent was unclear to the team)
- Decision patterns (where Kamal second-guesses)

**`kamil-self-gaps.md`** — Kamil's own weaknesses:
- Routing mistakes (wrong agent picked)
- Judgment failures (acted on ambiguous request)
- Communication weaknesses (too long, wrong tone, wrong thread)
- Quality failures (PR with failing tests, skill file not consulted)
- What I'm getting better at (positive signal tracking)

**`harness-evolution.md`** — How to improve the system itself:
- CLAUDE.md improvement patterns
- Notion DB improvement patterns
- Memory architecture patterns
- Skill file improvement patterns
- Hook and poller improvement patterns
- What NOT to touch without asking Kamal

---

## Evolution Loop

### Capability Gap Detection

```
Manager picks agent → no good fit found
        ↓
Handles task with best available tool
        ↓
Logs to .beads/capability-gaps.jsonl:
  {task_type, what_was_missing, how_handled, timestamp}
        ↓
DMs Kamal: "I handled this but had no right agent. 
  I improvised using [X]. Want me to build a skill/agent for this?"
```

### Auto-Proposal Triggers

| Trigger | Action |
|---|---|
| Same capability gap logged 3+ times | Kamil auto-proposes new agent/skill |
| Same self-gap logged 3+ times | Kamil proposes routing rule change |
| Kamal says "from now on when X do Y" | Kamil writes new routing rule, confirms |
| Harness weakness detected 2+ times | Kamil proposes harness fix |

### Approval Gate

All proposals require Kamal's "yes" or "apply" in Slack before any file is changed. No agent, skill, or rule is added autonomously.

---

## Proactive Slack Monitoring

### New Poller: `poll-proactive-slack.py`

Runs every tick. Watches configured channels for signals Kamil should act on without being tagged.

### Watch Configuration (`.claude/rules/proactive-channels.md`)

```
#engineering-*    — keywords: broken, failing, error, blocked, help, PR, deploy
#standup          — read-only: updates people-agent memory per person
#random           — human mode: Kamil can join banter naturally
#announcements    — read-only: never posts unless asked
```

### Decision Tree

```
Message detected in watched channel
        ↓
Already tied to a Notion ticket? → route to existing session
        ↓
@Kamil mention? → existing reactive flow
        ↓
Matches watch keyword?
        ↓
Manager: can I add value here?
  ├── Yes, immediately → reply directly in thread
  ├── Yes, needs work → create stub Notion ticket → spawn manager flow
  └── No / already handled → log, stay silent
```

### Proactive Posting Rules

- Never post in a mid-conversation thread unless directly relevant
- In #engineering: lead with the answer, not "I noticed you said..."
- In #random: human mode, jump in naturally like a teammate
- Never post twice in a row without a human reply in between
- If corrected → log to `kamil-self-gaps.md` immediately

---

## Session State Machine

One new status added to harness.db sessions:

```
pending → running (manager spawned)
       → awaiting_approval (Phase 1 plan posted to Slack)
       → running (worker spawned after @Kamil go)
       → completed (synthesis pass done, Status=Done written)
       → cancelled (blocked, error, or manager exit)
```

---

## What Does NOT Change

- Tick interval: 270s (never change without asking Kamal)
- Two-query pattern for events (never GROUP_CONCAT)
- Status=Done written LAST (commit signal)
- One session per context_key
- context_key is always a Notion ticket entity ID
- E2E gate before every PR
- `git add -A` and secrets never committed

---

## Implementation Sequence

1. Add `awaiting_approval` status to harness.db sessions table
2. Create `.claude/agents/` with 6 core team agent `.md` files
3. Create `.claude/skills/kamil/` with 12 living skill files (stubs)
4. Write `kamil-manager.py` (manager process + synthesis pass)
5. Write `poll-proactive-slack.py` (proactive channel watcher)
6. Write `.claude/rules/proactive-channels.md` (watch config)
7. Update `orchestrator-dispatch.py` to call `kamil-manager.py` instead of generic prompt
8. Wire capability gap detection and proposal DM
9. Wire skill file update after every session
10. Test end-to-end with a real Notion ticket
