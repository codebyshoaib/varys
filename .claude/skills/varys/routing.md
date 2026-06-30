# Routing — Agent Selection

## Core Rules
- Read this file BEFORE every task. Routing mistakes waste full sessions.
- When ambiguous: pick the most focused agent, not the most capable one.
- If no agent fits well: log capability gap, handle with best available, DM Shoaib.

## Routing Table
| Task type | Primary agent | Backup |
|---|---|---|
| find out / research / compare / what's the best | research-agent | — |
| code / PR / bug / test / implement / migration | code-agent | backend-specialist |
| taleemabad-core bug / feature / white screen / crash / "teachers can't see X" | taleemabad-bug-agent | code-agent |
| full feature/bugfix needing design→QA→review quality gates | product-lead | code-agent |
| adversarial diff review after substantive changes | code-reviewer | — |
| freelance / job / "apply 1/2/3" / proposal / "what jobs came in" | job-agent | — |
| post / LinkedIn / content / carousel / script | content-agent | — |
| message X / DM / notify / post in #channel | slack-agent | — |
| Notion ticket / update status / query DB | notion-agent | — |
| who is X / how does X prefer / team context | people-agent | slack-agent |
| avatar / image / profile photo / character / visual identity | character-agent | — |
| what did X say / do you remember / find everything about X / what's connected to X | brain-agent | — |
| stuck / blocked 2+ ticks / confidence < 40 / partial+blocker | escalation-broker | — |
| unknown / ambiguous | manager reasons first → capability-gap log | — |

> Rule of thumb: a generic `code / PR / bug` request goes to **code-agent**, but anything
> scoped to **taleemabad-core** is more focused → **taleemabad-bug-agent**. Pick the most
> focused row, not the broadest one.

## What Works
<!-- append lessons here after sessions -->

## What to Avoid
<!-- append mistakes here after sessions -->
