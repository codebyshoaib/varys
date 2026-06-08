---
type: runbook
last_verified: 2026-06-01
owner: kamil
paths:
  - "../../taleemabad-core/**"
---

# STOP — Before Touching taleemabad-core

## Anti-patterns (learned from failure — never repeat)

- **Never offer execution options** ("Subagent-Driven vs Inline"). Just start with `/feature`.
- **Never ask staging vs prod** — fixes always go to `develop` via PR.
- **Never narrate "I'm about to do X"** — do it, then report results.
- **Never ask what the code can answer** — grep/read the code first, ask only if two valid approaches exist.
- **Never ask "should I redesign or just fix?"** — if the UI/template exists, find why it's broken and fix it.

## Correct flow when a bug arrives (Slack or direct)

**Always delegate to `taleemabad-bug-agent`.** Do not implement this flow yourself.

When Kamal says anything like "fix X", "teachers can't see Y", "white screen on Z":

1. Recognize this as a taleemabad-core task
2. Post to Slack thread: "On it — running /feature now. Will post plan shortly. 🤖 Kamil"
3. The orchestrator dispatcher fires `taleemabad-bug-agent` via the next tick
4. The agent runs `/feature`, posts the plan, waits for `@Kamil go`

The agent (not Kamil) handles the entire lifecycle from here.

**Kamil's only direct action:** the acknowledgement in step 2. Everything else is delegated.

---

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

---

## Model Selection

Always use **claude-sonnet-4-6[1m]** (Sonnet 4.6 1M context). Never Haiku — the codebase is too large and context windows matter for understanding tenant-scoped architecture across dozens of files.

---

## Existing Branch — Conflict Resolution Flow

When Kamal gives an existing branch (already has conflicts):

1. `git checkout <branch> && git fetch origin && git status`
2. Identify conflicting files: `git diff --name-only --diff-filter=U`
3. For each conflicting file: read BOTH sides of the conflict, understand the intent of each change, then resolve by integrating both — **never delete working code to resolve a conflict**.
4. After resolving all conflicts: run the test suite to confirm nothing broke.
5. `git add <resolved-files> && git commit -m "fix: resolve merge conflicts on <branch>"`
6. Update PR description to note conflicts resolved + push.
7. DM Kamal on Slack: "Conflicts resolved on `<branch>`. PR updated."

---

## Monitoring the Harness

After `/develop` runs, evaluate output quality before moving on:

- Did `research.md` capture the real root cause (not just a surface symptom)?
- Does `plan.md` solve the right problem, not just a related one?
- Did `/develop` touch the right files — not too many (scope creep), not too few (incomplete fix)?
- Are test assertions meaningful — do they catch regressions, or just pass trivially?

If output is weak on any dimension: fix the corresponding command file in `.claude/commands/` before the next run so the harness improves.

---

## Harness Failure → Fix the Command

If a command produces weak output **two sessions in a row**:

1. Read the command file in `.claude/commands/`
2. Identify what guidance is missing or underspecified
3. Update the command file with the lesson learned
4. Log the gap in `.beads/failures.jsonl`
5. Update `vault/projects/taleemabad-core/patterns.md` with the pattern

---

## After Every Task

- Update `vault/projects/taleemabad-core/issues-log.md` with what was done and any gotchas.
- If a new code pattern emerged (good or bad): add it to `vault/projects/taleemabad-core/patterns.md`.
- Update the Notion Harness entry to **Done** (or Blocked with reason).
