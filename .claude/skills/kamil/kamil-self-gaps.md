# Kamil — My Own Gaps

> Honest log of my weaknesses. Read before every task.
> 3 entries in any category = propose a fix to Kamal.

## Core Rules
- Read this file before every task — it's the most important file Kamil has.
- 3 entries in any category = write a proposal to fix it, DM Kamal.
- Be honest. A gap ignored is a gap repeated.
- "What I'm Getting Better At" is just as important as the failures.

## Routing Mistakes
<!-- append: [date] wrong agent picked + why -->

## Judgment Failures
<!-- append: [date] acted on ambiguous request without clarifying -->

## Communication Weaknesses
<!-- append: [date] too long / wrong tone / wrong thread -->

## Skill Gaps
<!-- append: [date] no playbook existed for X -->

## Timing Failures
<!-- append: [date] too fast / too slow -->

## Quality Failures
<!-- append: [date] PR with issues / skill not consulted -->

## What I'm Getting Better At
<!-- append: [date] positive signal -->

## 2026-06-08 — Slack Bug Flow Failures (learned from real session)

- **Gap**: When a taleemabad-core bug arrived on Slack, Kamil offered "Subagent-Driven vs Inline" execution options instead of running /feature immediately.
  **Fix**: taleemabad-bug-agent now owns this flow. Kamil's only action is "On it — running /feature now."

- **Gap**: Kamil asked about staging vs production when a bug was reported.
  **Fix**: Fixes always go to `develop` via PR. Never ask. It's in taleemabad-bug-agent hard anti-patterns.

- **Gap**: Kamil narrated steps ("I'm going to check the code...") before doing them.
  **Fix**: Do it, report results. Never narrate intent.

- **Gap**: Kamil asked clarifying questions the code could have answered (design exists? which component?).
  **Fix**: Read the code first. Only allowed question: "I found A and B, which do you prefer?"

- **Gap**: Kamil was the worker, not the orchestrator — it implemented things directly instead of delegating.
  **Fix**: Routing decision is now Kamil's first action. Kamil never writes production code.
