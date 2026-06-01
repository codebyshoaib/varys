---
type: runbook
last_verified: 2026-06-01
owner: kamil
paths:
  - "../../taleemabad-core/**"
---

# STOP — Before Touching taleemabad-core

When Kamal says **"Kamil, work on taleemabad-core — [task]"**, follow this EXACT sequence. No exceptions.

1. Create Notion Harness entry (FIRST — before anything). DB `de10157da3e34ef58a74ea240f31fe98`. Fields: Feature, Phase (Research→Planning→In Dev→Testing→Done/Blocked), Plan Summary, Jira Ticket, PR, Confidence 0–100, Last Activity.
2. `cd /home/oye/Documents/taleemabad-core`
3. `git checkout develop && git pull origin develop`
4. `git checkout -b kamil/<task-name>` — never work on develop.
5. `claude --dangerously-skip-permissions -p "/feature <task-name>"` from inside taleemabad-core → creates `.claude/features/YYYY-MM-DD-<name>/research.md` + `plan.md`.
6. Review research.md + plan.md as engineering lead (not rubber-stamping): real root cause vs symptom? RIGHT solution not just A solution? risks/deps missed? If weak → fix plan.md or re-run /feature sharper; if a class of problem recurs → fix `.claude/commands/feature.md`. Update Harness entry.
7. Approve + DM Kamal: "Plan approved. Approach: [what + why]. Starting /develop."
8. `claude -p "/develop <name>"` inside taleemabad-core.
9. `claude -p "/test <name>"` → `/fix <name>` loop until confidence ≥86%.
10. `claude -p "/deliver <name>"` — all checks, PR, /reflect, Notion update, DM Kamal.

## Never ask Kamal what the code can answer
Read the logout handler, localStorage code, sync controller, push sync — find the answer. The ONLY questions allowed: "I found X and Y approaches, which do you prefer?" (with a recommendation); "Plan ready, approve /develop?"; "PR is up, anything else?".

## taleemabad-core quality gates (non-negotiable)
Coverage ≥85% · Confidence ≥86% · Linter ≥95% · every model/endpoint tenant-scoped · deletes use `is_active=False` · migrations reversible + tested locally.

## Commands
`/feature` (research+plan) · `/develop` (implement) · `/test` (validate+score) · `/fix` (loop to ≥86%) · `/bdd-writer` (Gherkin after done). Feature folder: research.md, plan.md, develop.md, bugs.md, test-results.md, confidence.md, status.md.

## Rule: NOTHING is done without a Harness entry.
