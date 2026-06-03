# Parallel Task Isolation — Design Spec
**Date:** 2026-06-03  
**Owner:** Kamil  
**Status:** Draft

---

## Problem

When Kamil receives multiple Slack tasks for taleemabad-core simultaneously, each `claude -p` call runs in the same `/home/oye/Documents/taleemabad-core` directory. If two tasks are in flight:
- Task A and Task B share the same working tree → edits collide
- A `git checkout` by one task switches branch for the other
- Notion Harness entries exist but there's no enforcement that each task has its own isolated environment

Result: mixed code, wrong-branch commits, context loss on restart.

---

## Solution: One Worktree Per Task

Each Slack-triggered task gets its own git worktree at `/home/oye/Documents/taleemabad-worktrees/<task-name>`. All `claude -p` commands run from that worktree, not from the main repo. The main repo (`taleemabad-core`) is never used for active development — only for `git worktree add/remove` operations.

---

## Architecture

### Worktree Layout
```
/home/oye/Documents/taleemabad-core/          ← main repo, no active work here
/home/oye/Documents/taleemabad-worktrees/
  kamil-fix-grand-quiz/                       ← Task A worktree
  kamil-add-attendance-report/                ← Task B worktree
  kamil-auth-token-fix/                       ← Task C worktree
```

### Per-Task Flow (replaces step 4 in taleemabad.md)

Old step 4: `git checkout -b kamil/<task-name>`

New steps 4a–4c:
```bash
# 4a. Create branch + worktree in one shot
git -C /home/oye/Documents/taleemabad-core worktree add \
  /home/oye/Documents/taleemabad-worktrees/kamil-<task-name> \
  -b kamil/<task-name>

# 4b. All subsequent commands run from the worktree, not main repo
cd /home/oye/Documents/taleemabad-worktrees/kamil-<task-name>

# 4c. Store worktree path in Notion Harness entry (new field: Worktree Path)
```

### Notion Harness — New Field
Add **Worktree Path** field to Harness DB (`de10157da3e34ef58a74ea240f31fe98`).  
On restart: Kamil reads this field → `cd <worktree-path>` → full context restored instantly.

### Model Enforcement
All `claude -p` calls use `--model claude-sonnet-4-6` flag explicitly. Never rely on default.

### Cleanup
When `/deliver <name>` completes and PR is merged:
```bash
git -C /home/oye/Documents/taleemabad-core worktree remove \
  /home/oye/Documents/taleemabad-worktrees/kamil-<task-name>
```
Notion Harness entry updated to Done + Worktree Path cleared.

---

## What Changes

### `taleemabad.md` rule file
- Step 4: replace `git checkout -b` with `git worktree add` (steps 4a–4c above)
- Add model flag to all `claude -p` calls: `claude --model claude-sonnet-4-6 -p "/feature ..."`
- Add cleanup step to `/deliver` flow

### Notion Harness DB
- Add **Worktree Path** text field (stores `/home/oye/Documents/taleemabad-worktrees/<name>`)
- This is the restart anchor — if session dies, Kamil reads path and resumes instantly

### kamil-task-interceptor.py (optional guard)
If Kamil accidentally runs a `claude -p` from the main repo instead of a worktree, the interceptor can detect `$PWD == /home/oye/Documents/taleemabad-core` and warn before proceeding.

---

## Failure / Restart Protocol

1. Session dies mid-task
2. Kamil queries Notion Harness: `worktree_path` + `phase` fields
3. `cd <worktree_path>` — all work is still there, uncommitted or committed
4. Resume from the recorded phase: `/develop`, `/test`, or `/fix`
5. No code lost, no context guessing

---

## What This Does NOT Change

- The `/feature → /develop → /test → /fix → /deliver` pipeline stays identical
- All quality gates stay: coverage ≥85%, confidence ≥86%, linter ≥95%
- Notion Harness entry still required before ANY work begins
- Slack DM protocol unchanged

---

## Out of Scope

- Parallel worktrees for frontend (taleemabad-cms) — same pattern applies but not in this spec
- Auto-cleanup cron — manual cleanup via `/deliver` is sufficient for now
