---
description: Kamil-owned delivery gate. Runs after confidence ≥86% — verifies everything is clean, creates the PR, runs /reflect, updates Notion Harness, and DMs Kamal with the PR link + confidence score. Kamil never claims delivery without completing every check.
---

# Command: /deliver

Kamil owns this command. No human approval needed to run it — Kamil is the approver.
Kamil never asks Kamal to create the PR or verify anything. Kamil does it all.

**Usage**: `/deliver <feature-slug>`

---

## Pre-flight: Gate Check (STOP if any fail)

Before doing anything, verify every gate. If any gate fails, stop and fix it — do not create PR.

```
Gate 1 — Confidence ≥ 86%
  Read: .claude/features/<slug>/confidence.md
  Check: confidence score ≥ 86%
  FAIL action: run /fix <slug> → /test <slug> until ≥ 86%, then re-run /deliver

Gate 2 — Verifier PASS (bug-fix features only)
  Read: .claude/features/<slug>/verification.md
  Check: file exists AND contains "PASS"
  FAIL action: run /test <slug> (verifier will re-run), fix failures, re-run /deliver

Gate 3 — Linter clean
  Run: cd /home/oye/Documents/taleemabad-core && python -m flake8 --max-line-length=120 --statistics . 2>&1 | tail -20
  Run: cd /home/oye/Documents/taleemabad-core && python -m black --check . 2>&1 | tail -10
  FAIL action: run black . && isort . to auto-fix, then re-check

Gate 4 — Type check passes
  Run: cd /home/oye/Documents/taleemabad-core && python -m mypy taleemabad_core --ignore-missing-imports 2>&1 | tail -20
  FAIL action: fix type errors in affected files, re-run

Gate 5 — Tests pass
  Run: cd /home/oye/Documents/taleemabad-core && python manage.py test --verbosity=0 2>&1 | tail -20
  FAIL action: if failures are in touched modules → /fix; if regressions in unrelated modules → note in PR body

Gate 6 — No open CRITICAL/HIGH bugs
  Read: .claude/features/<slug>/bugs.md
  Check: no bugs with Status: 🔴 OPEN and Severity: CRITICAL or HIGH
  FAIL action: resolve all CRITICAL + HIGH bugs, re-run /test, then re-run /deliver

Gate 7 — Migrations verified
  Run: cd /home/oye/Documents/taleemabad-core && python manage.py migrate --check 2>&1
  If any unapplied: run python manage.py migrate and verify no errors

Gate 8 — Branch is not develop/main
  Run: git symbolic-ref --short HEAD
  Check: branch name starts with "kamil/"
  FAIL action: something went very wrong — stop and report to Kamal
```

Print gate summary before proceeding:
```
Pre-flight check:
  ✅ Confidence: 88% (≥ 86%)
  ✅ Verifier: PASS
  ✅ Linter: clean
  ✅ Type check: pass
  ✅ Tests: 45/45 passing
  ✅ Open bugs: 0 CRITICAL, 0 HIGH
  ✅ Migrations: applied
  ✅ Branch: kamil/beaconhouse-feature-flag

All gates passed. Proceeding to delivery.
```

---

## Step 1: Commit everything

```bash
cd /home/oye/Documents/taleemabad-core
git add -A
git status  # confirm what's staged
git commit -m "feat(<slug>): <one-line summary of what was built>

- <key change 1>
- <key change 2>
- <key change 3>

Confidence: <score>%
Tests: <N>/<N> passing
Coverage: <N>%"
```

---

## Step 2: Push branch

```bash
git push origin kamil/<slug>
```

If push fails (remote has diverged):
```bash
git pull --rebase origin develop
git push origin kamil/<slug>
```

---

## Step 3: Create PR via gh

Read `.claude/features/<slug>/plan.md` for goal + success criteria.
Read `.claude/features/<slug>/confidence.md` for score breakdown.
Read `.claude/features/<slug>/bugs.md` for any known open LOW/MEDIUM issues.

```bash
gh pr create \
  --base develop \
  --title "feat: <slug> — <one-line description>" \
  --body "$(cat <<'EOF'
## What

<1-2 sentences: what this PR does and why>

## Changes

- <file or area>: <what changed>
- <file or area>: <what changed>

## Quality Gates

| Check | Result |
|-------|--------|
| Confidence score | <N>% (target ≥ 86%) |
| Test coverage | <N>% (target ≥ 85%) |
| Linter | ✅ PASS |
| Type check | ✅ PASS |
| Verifier | ✅ PASS / N/A (greenfield) |
| Open CRITICAL bugs | 0 |
| Open HIGH bugs | 0 |

## Known Issues (LOW/MEDIUM only)

<list any open LOW/MEDIUM bugs, or "None">

## Test Plan

- [ ] Golden path: <describe>
- [ ] Edge case: <describe>
- [ ] Regression: existing tests pass

## Feature Docs

`.claude/features/<date>-<slug>/`
- `plan.md` — approved plan
- `confidence.md` — score breakdown
- `bugs.md` — all bugs found + status

🤖 Delivered by Kamil (personal-agent-v2)
EOF
)"
```

Capture the PR URL from the output.

---

## Step 4: Run /reflect

```bash
/reflect <slug>
```

This extracts lessons, updates MEMORY.md, promotes rules. Always run — never skip.

---

## Step 5: Update Notion Harness entry

Find the Harness DB entry for this task (created at session start by kamil-task-interceptor.py).

Update:
- **Phase**: Done
- **PR**: `<PR number> — <PR URL>`
- **Confidence**: `<final score>`
- **Last Activity**: today's date
- **Plan Summary**: append "PR created: <URL> | Confidence: <score>%"

---

## Step 6: DM Kamal on Slack

Send to Kamal (U0AV1DX3WSE):

```
✅ PR ready: <task description>

PR: <URL>
Branch: kamil/<slug>
Confidence: <score>%
Tests: <N>/<N> passing | Coverage: <N>%
Verifier: PASS / N/A

Open issues: <count LOW/MEDIUM bugs, or "none">

Feature docs: taleemabad-core/.claude/features/<date>-<slug>/
```

---

## Step 7: Log to vault

Append to `/home/oye/Documents/free_work/personal-agent-v2/vault/logs/YYYY-MM-DD.md`:

```
- HH:MM — [<slug>]: PR created #<number> | Confidence: <score>% | Status: delivered
```

---

## What Kamil Never Does

- ❌ Creates PR with confidence < 86%
- ❌ Creates PR with open CRITICAL or HIGH bugs
- ❌ Skips /reflect
- ❌ Asks Kamal to run any of these steps
- ❌ Claims delivery without Slack DM sent
- ❌ Merges to develop — PR review is Kamal's call

---

## Full Pipeline (where /deliver fits)

```
/feature  (research + plan, Kamil self-approves)
  → /develop  (implement)
    → /test  (verify + confidence scoring)
      → /fix  (loop until ≥ 86%)
        → /deliver  (gate check → commit → push → PR → /reflect → Notion → Slack DM)  ← YOU ARE HERE
```

Kamal only acts after the Slack DM. His job: review the PR and merge or comment.
