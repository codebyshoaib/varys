# Taleemabad-Core Workflow Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a repeatable, one-shot-success workflow for all taleemabad-core tasks — branch creation, harness execution, monitoring, Notion brain updates, PR creation, and Slack notification.

**Architecture:** Every task goes through a fixed 10-step pipeline: Notion Harness entry → fresh branch → /feature → review plan → /develop → /test+/fix loop → /deliver → PR → Slack DM. A Notion "Brain" database captures patterns from past work so each new task starts with codebase context already loaded.

**Tech Stack:** Django/DRF (backend), React/Dexie (frontend), taleemabad-core harness (/feature /develop /test /fix /deliver), Notion MCP, Slack MCP, Claude Sonnet 4.6 1M context model.

---

## File Structure

| File | Purpose |
|------|---------|
| `.claude/rules/taleemabad.md` | Kamil's operating rules for taleemabad-core — update when workflow evolves |
| `.claude/rules/notion.md` | Notion DB IDs and MCP query patterns |
| `.claude/rules/slack.md` | Slack send/lookup patterns |
| `vault/projects/taleemabad-core/project.md` | Living brain of the project: what it is, what we've worked on, patterns |
| `vault/projects/taleemabad-core/architecture.md` | Architecture reference: apps, models, sync patterns, key files |
| `vault/projects/taleemabad-core/patterns.md` | Recurring patterns, anti-patterns, gotchas discovered from past work |
| `vault/projects/taleemabad-core/issues-log.md` | Log of past issues, root causes, and how they were resolved |

---

### Task 1: Create taleemabad-core Brain in Notion

This is a one-time setup task. Creates the Notion "Brain" database Kamil asked for — a persistent reference of what taleemabad-core is, what we've worked on, patterns, and recurring issues.

**Files:**
- Create: `vault/projects/taleemabad-core/project.md`
- Create: `vault/projects/taleemabad-core/architecture.md`
- Create: `vault/projects/taleemabad-core/patterns.md`
- Create: `vault/projects/taleemabad-core/issues-log.md`
- Modify: `vault/projects/taleemabad-core/related.md` (if it exists)

- [ ] **Step 1: Read existing taleemabad-core vault files**

```bash
ls /home/oye/Documents/free_work/personal-agent-v2/vault/projects/taleemabad-core/
```

- [ ] **Step 2: Read the taleemabad-core CLAUDE.md and harness to extract project context**

```bash
head -100 /home/oye/Documents/taleemabad-core/CLAUDE.md
cat /home/oye/Documents/taleemabad-core/.claude/HARNESS.md | head -60
```

- [ ] **Step 3: Write project.md — what taleemabad-core is**

```markdown
# taleemabad-core — Project Brain

**What it is:** Django LMS (Learning Management System) serving Pakistani schools. 
Multi-tenant SaaS. Teachers, coaches, students. Offline-first architecture (Dexie on frontend).

**Stack:** Django + DRF (backend) · React + TypeScript + Dexie (frontend) · PostgreSQL · Redis · Celery

**Apps:** coaching · student_learning · book_library · teacher_training · aeos_training · core · auth

**Key constraints:**
- Every model must be tenant-scoped (TenantMixin)
- Deletes are always soft (`is_active=False`, never hard delete)
- Migrations must be reversible
- Coverage ≥85%, confidence ≥86% before ship

**Harness commands:** /feature → /develop → /test → /fix → /deliver

**Repo:** /home/oye/Documents/taleemabad-core
```

- [ ] **Step 4: Write architecture.md — apps, models, key files**

Extract from reading the actual codebase:

```bash
ls /home/oye/Documents/taleemabad-core/taleemabad_core/apps/
find /home/oye/Documents/taleemabad-core/taleemabad_core/apps -name "models.py" | head -20
```

Then write the file documenting the app list, key model names, sync patterns.

- [ ] **Step 5: Write patterns.md — recurring patterns and anti-patterns**

```markdown
# taleemabad-core — Patterns & Anti-Patterns

## Patterns (DO)
- Always use `TenantMixin` on every model — all queries scoped by tenant_id
- Soft delete: `is_active=False`, never `delete()`
- Migrations: always reversible, add backfill RunPython for new fields
- Backend serializers: inherit `BasePushSyncSerializer` (includes tenant_id)
- Frontend sync: wrap multi-table Dexie writes in `db.transaction()`
- Dexie schema change: increment version number + write upgrade migration

## Anti-Patterns (NEVER DO)
- Never hard-delete records
- Never write a migration that can't be reversed
- Never forget tenant_id filter on GET list endpoints
- Never commit migrations without testing them locally (`./manage.py migrate`)
- Never work on develop branch — always `git checkout -b kamil/<task>`

## Recurring Issues (watch out)
- Race condition in Dexie writes during sync (fix: db.transaction())
- Timestamp precision mismatch (fix: normalize to milliseconds)
- Soft-delete + sync conflict (synced DELETED record still shows)
- Multi-tenant data leak (forgot tenant filter)
```

- [ ] **Step 6: Write issues-log.md as empty template**

```markdown
# taleemabad-core — Issues Log

Each entry: what was the issue, root cause, how it was fixed, what we'd do different.

---

## Template

### ISSUE-001: [short title]
**Date:** YYYY-MM-DD
**Feature:** [feature name]
**Symptom:** [what the user reported]
**Root Cause:** [actual cause]
**Fix:** [what changed and where]
**Lesson:** [what to watch for next time]
**Pattern added:** [yes/no — which pattern file updated]
```

- [ ] **Step 7: Create Notion page for taleemabad-core Brain**

Use Notion MCP to create a page in the existing workspace:

```
Title: taleemabad-core Brain
Content: Summary of project, link to vault files, last updated
```

Query the Notion MCP to find the right parent page, then create.

- [ ] **Step 8: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add vault/projects/taleemabad-core/
git commit -m "feat: create taleemabad-core brain (project, architecture, patterns, issues-log)"
```

---

### Task 2: Update `.claude/rules/taleemabad.md` — Full Workflow Protocol

The existing `taleemabad.md` has steps 1-10 but is missing: branch-from-existing-branch conflict resolution, model selection enforcement (Sonnet 1M), and monitoring the harness output.

**Files:**
- Modify: `/home/oye/Documents/free_work/personal-agent-v2/.claude/rules/taleemabad.md`

- [ ] **Step 1: Read current taleemabad.md**

```bash
cat /home/oye/Documents/free_work/personal-agent-v2/.claude/rules/taleemabad.md
```

- [ ] **Step 2: Add the missing sections to taleemabad.md**

Replace the file with the full updated protocol (append below existing steps 1-10):

```markdown
## Model Selection
Always use claude-sonnet-4-6[1m] (Sonnet 4.6 1M context) for taleemabad-core work.
Haiku is NEVER acceptable — the codebase is too large for its context window.
Set model before starting: `claude --model claude-sonnet-4-6 ...`

## New Task — Standard Flow (fresh branch)
1. Create Notion Harness entry (DB: de10157da3e34ef58a74ea240f31fe98)
2. cd /home/oye/Documents/taleemabad-core
3. git checkout develop && git pull origin develop
4. git checkout -b kamil/<task-slug>
5. claude --model claude-sonnet-4-6 -p "/feature <task-slug>"
6. READ research.md + plan.md as engineering lead — is this the RIGHT fix, not just A fix?
7. If plan is weak: fix plan.md or re-run /feature with sharper scope
8. DM Kamal: "Plan approved. Approach: [what + why]. Starting /develop."
9. claude -p "/develop <task-slug>"
10. claude -p "/test <task-slug>" → /fix loop until confidence ≥86%
11. claude -p "/deliver <task-slug>" — PR + Notion update + DM Kamal

## Existing Branch — Conflict Resolution Flow
When Kamal gives an existing branch with conflicts:
1. git checkout <branch> && git fetch origin && git status
2. Identify conflicting files: git diff --name-only --diff-filter=U
3. For each conflict: read BOTH sides, understand the intent, resolve without breaking either
4. Rule: never delete working code to resolve a conflict — integrate both changes
5. After resolving: run tests to confirm nothing broke
6. git add <resolved-files> && git commit -m "fix: resolve merge conflicts on <branch>"
7. Update PR description with what was resolved + push
8. DM Kamal on Slack: "Conflicts resolved on <branch>. PR updated."

## Monitoring the Harness
After /develop runs, DO NOT blindly accept the output. Check:
- Did research.md capture the real root cause (not just the symptom)?
- Does plan.md solve the right problem?
- Did /develop touch the right files (not too many, not too few)?
- Are test assertions meaningful (not just asserting response code 200)?
- If harness output is weak: fix the command file in .claude/commands/ before next run

## Harness Failure → Fix the Command
If a harness command produces weak output two sessions in a row:
1. Read the command file: cat /home/oye/Documents/taleemabad-core/.claude/commands/<cmd>.md
2. Identify what guidance is missing
3. Update the command file with the lesson
4. Log the gap in .beads/failures.jsonl
5. Also update vault/projects/taleemabad-core/patterns.md with the lesson

## After Every Task
- Update vault/projects/taleemabad-core/issues-log.md with the issue + fix + lesson
- If a new pattern was discovered: add to vault/projects/taleemabad-core/patterns.md
- Update Notion Harness entry to Done
```

- [ ] **Step 3: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/rules/taleemabad.md
git commit -m "feat: update taleemabad workflow — model selection, conflict flow, harness monitoring"
```

---

### Task 3: Validate Workflow with a Dry-Run Checklist

Verify the workflow is complete by walking through both scenarios mentally and checking all required pieces are in place.

**Files:**
- Read: `/home/oye/Documents/taleemabad-core/.claude/commands/feature.md`
- Read: `/home/oye/Documents/taleemabad-core/.claude/commands/develop.md`
- Read: `/home/oye/Documents/taleemabad-core/.claude/commands/test.md`
- Read: `/home/oye/Documents/taleemabad-core/.claude/commands/fix.md`

- [ ] **Step 1: Verify all harness commands exist**

```bash
ls /home/oye/Documents/taleemabad-core/.claude/commands/
```

Expected: feature.md, develop.md, test.md, fix.md, deliver.md, revisit.md, evolve.md

- [ ] **Step 2: Verify Notion Harness DB ID is correct**

```bash
grep -r "de10157da3e34ef58a74ea240f31fe98" /home/oye/Documents/free_work/personal-agent-v2/.claude/rules/
```

Should match `taleemabad.md`. If not: find the real DB ID via Notion MCP search.

- [ ] **Step 3: Verify Slack send pattern works**

```bash
cat /home/oye/Documents/free_work/personal-agent-v2/.claude/rules/slack.md | head -40
```

Confirm the DM-to-Kamal pattern is documented and functional.

- [ ] **Step 4: Dry-run checklist — New Task Scenario**

Walk through this mentally (do not execute, just verify all pieces exist):

```
□ Notion Harness entry → DB ID known? ✓/✗
□ git checkout develop && pull → standard git, works
□ git checkout -b kamil/<slug> → standard git, works
□ claude -p "/feature <slug>" → command file exists? ✓/✗
□ Review plan → brain files exist to reference? ✓/✗
□ DM Kamal → slack.md has pattern? ✓/✗
□ claude -p "/develop <slug>" → command file exists? ✓/✗
□ claude -p "/test <slug>" → command file exists? ✓/✗
□ claude -p "/fix <slug>" → command file exists? ✓/✗
□ claude -p "/deliver <slug>" → command file exists? ✓/✗
□ PR to develop → git workflow known? ✓/✗
□ Slack DM → slack.md has pattern? ✓/✗
```

- [ ] **Step 5: Dry-run checklist — Existing Branch Scenario**

```
□ git checkout <branch> → standard git, works
□ git fetch + status + diff → identify conflicts
□ Resolve conflicts → taleemabad.md has rule? ✓/✗
□ Run tests → test command known? ✓/✗
□ Push + update PR → git workflow known? ✓/✗
□ DM Kamal → slack.md has pattern? ✓/✗
```

- [ ] **Step 6: Fill any gap found above**

If any item is ✗, fix it before marking this task complete.

---

### Task 4: Update Memory Index

Add the new taleemabad-core brain files to MEMORY.md so they load in future sessions.

**Files:**
- Modify: `/home/oye/Documents/free_work/personal-agent-v2/vault/memory/MEMORY.md`

- [ ] **Step 1: Read MEMORY.md**

```bash
cat /home/oye/Documents/free_work/personal-agent-v2/vault/memory/MEMORY.md
```

- [ ] **Step 2: Add entries for the new brain files**

Add these lines under an appropriate section:

```markdown
- [taleemabad-core Brain](../projects/taleemabad-core/project.md) — What the project is, stack, apps, constraints
- [taleemabad-core Architecture](../projects/taleemabad-core/architecture.md) — App list, key models, sync patterns
- [taleemabad-core Patterns](../projects/taleemabad-core/patterns.md) — DO/NEVER DO/Recurring issues
- [taleemabad-core Issues Log](../projects/taleemabad-core/issues-log.md) — Past issues, root causes, lessons
```

- [ ] **Step 3: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add vault/memory/MEMORY.md
git commit -m "feat: add taleemabad-core brain to memory index"
```

---

## Quick Reference — Kamil's Taleemabad-Core Checklist

When Kamal says "work on taleemabad-core":

**New task:**
1. Notion Harness entry (DB: de10157da3e34ef58a74ea240f31fe98)
2. `git checkout develop && git pull origin develop`
3. `git checkout -b kamil/<task-slug>`
4. `claude -p "/feature <task-slug>"` — READ + REVIEW the plan
5. DM Kamal: plan approved
6. `claude -p "/develop <task-slug>"`
7. `claude -p "/test <task-slug>"` → `claude -p "/fix <task-slug>"` loop ≥86%
8. `claude -p "/deliver <task-slug>"` → PR + Notion Done + Slack DM

**Existing branch with conflicts:**
1. `git checkout <branch> && git fetch origin`
2. Identify conflicts, resolve without deleting working code
3. Run tests to verify
4. Push + update PR
5. Slack DM Kamal

**After every task:**
- Update `vault/projects/taleemabad-core/issues-log.md`
- Update `vault/projects/taleemabad-core/patterns.md` if new pattern found
- Notion Harness → Done
