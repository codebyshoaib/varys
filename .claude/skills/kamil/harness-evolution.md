# Harness Evolution

> How to improve the system itself. Read when detecting a recurring pattern.
> Propose improvements to Kamal — never apply without approval.

## Core Rules
- Detect patterns before proposing. 3+ occurrences = propose a fix.
- Never apply changes to the harness without Kamal's explicit approval.
- Every proposal goes to Kamal via Slack DM: what / why / what changes.
- Log all proposals in the "Proposed Improvements Log" section below.

## CLAUDE.md Improvement Patterns
- Rule keeps being violated → too vague, rewrite with an example
- Context repeated 3+ sessions → extract to rules/ file
- CLAUDE.md hits line limit → audit stale rules, move to vault/

## Notion DB Improvements
- Same query fails 2+ times → DB missing a property or filter
- Status transitions ambiguous → add new status value + document
- Data lost between sessions → add Date or Rich Text field

## Memory Architecture
- Same fact looked up 3+ times → belongs in vault/memory/
- Memory file not read in 30 days → archive or delete
- Two files contradict → reconcile immediately

## Skill File Improvements
- Skill ignored (too long) → split, keep each file < 80 lines
- Skill has no "What to Avoid" → hasn't been tested enough yet
- Skill works perfectly every time → promote core rules to CLAUDE.md

## Hook & Poller Improvements
- Poller misses events → tighten filter or increase frequency
- Hook fires on wrong events → add guard condition
- Same fix applied manually 2+ times → automate as hook

## What NOT to Touch Without Asking Kamal
- harness.db schema changes
- settings.json hook wiring
- Any file affecting the tick loop
- Deleting any rule or memory file

## Proposed Improvements Log
<!-- append: [date] what / why / status (proposed|approved|applied) -->
