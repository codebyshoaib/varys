---
type: plan
last_verified: 2026-06-01
owner: kamil
status: active
---

# Fix: Self-Healing Loop Noise & Unverified Auto-Fix

**Goal:** Stop the self-healer/observer from (a) flapping false "listener down→restarted"
alerts every cycle, (b) re-fixing already-fixed errors forever, (c) editing+committing on
unverified diagnoses, and (d) double-DMing contradictory reports. Make the feedback layer
idempotent, verified, and quiet.

---

## What actually happened (evidence-based)

Symptoms from Slack: every 10 min, "listener was down → restarted" + "content-scheduler
errors, could not auto-fix / Status: fixed" with a *different* hallucinated root cause each
time. content-scheduler.py has **41 commits** (~13 today).

**Investigation findings:**
1. content-scheduler.py **compiles clean** — there is no current syntax error.
2. The auto-fixer's net edits are **GOOD** (NLM retry logic, a real `--profile` guard fix,
   empty-notebook cleanup). NOT damage. The file is kept as-is.
3. The bug is the **loop's behavior**, not the file.

## Four real bugs (all in the feedback layer)

| # | Bug | Root cause |
|---|-----|-----------|
| 1 | Listener falsely "down→restarted" every cycle | `is_process_running()` uses bare `pgrep -f kamil-slack-listener.py` — racy, can self-match the checker's own cmdline; and it DMs every run, not only on a state change |
| 2 | content-scheduler "re-fixed" 13× for a fixed error | Observer queries last-1h Axiom errors with **no idempotency / no already-handled memory** — a stale error stays in the window and gets re-diagnosed + re-acted every run |
| 3 | Unverified edits committed to master each cycle | Auto-fix shells `claude -p` with no check that the error is *current*, no failing test, no diff review. Safe this time by luck, not design |
| 4 | Duplicate, contradictory DMs | self-healer ("could not auto-fix") and observer ("Status: fixed") both DM about the same incident independently |

---

## Fixes

### Fix 1 — Listener detection: PID-file + state-change-only alerts + cooldown
- Replace bare `pgrep -f` with: check PID-file liveness, AND a `pgrep -f` that **excludes the
  checker's own PID** and confirms the actual `python3 .../kamil-slack-listener.py` process.
- Maintain a small state file (`/tmp/kamil-healer-state.json`): only DM/restart when the
  state **changes** up→down (not every cycle it's observed down). Add a cooldown (e.g. no
  repeat alert for the same service within 30 min).

### Fix 2 — Observer idempotency: only act on CURRENT, unhandled errors
- Before acting on any anomaly, **verify the error is current**: re-run the failing
  component (or re-compile the file) — if it now succeeds/compiles, mark resolved and SKIP.
- Keep a handled-incidents ledger (`.beads/observer-handled.jsonl`): key = (component +
  error_type + first-seen window). If already handled, do not re-act.
- Query window stays 1h, but dedup by ledger so a lingering log entry isn't re-fixed.

### Fix 3 — Escalate-only by default (reverses the earlier "auto-fix anything" choice)
- Observer **no longer edits code or commits**. It: verify-current → diagnose → write a
  Notion row (🔴 Needs Kamal) with the proposed patch + ONE DM. Kamal (or a manual Kamil
  run) applies the fix.
- The `.observer-paused` kill switch stays as a hard stop. Escalate-only is the *default*,
  not a mode you must remember to enable.

### Fix 4 — Single DM owner + truthful status
- The observer is the only component that DMs about code-level anomalies. The self-healer
  DMs only about **process lifecycle** (real up→down transitions), gated by Fix 1.
- Remove the contradictory "could not auto-fix" + "Status: fixed" combo: a message says
  EITHER "escalated: needs you" OR "auto-restarted (process)", never both for one event.

### Fix 5 — Lock-in test
- `.claude/evals/tests/test_content_scheduler_sane.sh`: asserts content-scheduler.py
  compiles and that `nlm-delete` calls only appear on guarded empty/failed paths. Catches
  future churn-damage at $0.

---

## Risks / what NOT to break
- Don't revert content-scheduler.py — its current edits are good (verified).
- Don't disable the self-healer's *real* job (restarting a genuinely-dead daemon) — only
  stop the false positives and the spam.
- Keep all logging (Axiom + Notion) intact; this changes *acting* logic, not *observing*.
- Escalate-only must still write to Notion with correct status so Kamal sees every issue.

## Definition of done
- [ ] Listener no longer DMs "down→restarted" when it is up (state-change-only + cooldown)
- [ ] `is_process_running` cannot self-match; uses PID-file + filtered pgrep
- [ ] Observer verifies an error is CURRENT before acting; skips stale/handled (ledger)
- [ ] Observer is escalate-only by default — no code edits, no commits; writes Notion 🔴 + 1 DM
- [ ] No duplicate/contradictory DMs for one event
- [ ] content-scheduler.py untouched (kept); lock-in test passes
- [ ] failures.jsonl updated with the corrected (non-"destructive") diagnosis
- [ ] All hooks compile; listener stays up; nothing else broken
