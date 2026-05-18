# Kamil — Bug Memory (Sentinel Pattern)

Every bug Kamil helps diagnose or fix gets appended here.
Kamil reads this at session start — recall before observe.

Format:
## [DATE] [one-line symptom]
- **Layer**: react | network | django | data | native | sync
- **Trigger**: how it was discovered
- **Hypothesis**: root cause
- **Root cause**: confirmed cause
- **Fix**: PR link or "unresolved" + why
- **Prevention**: what stops this recurring
- **Time-to-resolve**: minutes
- **Notes**: hints for future runs

---

## [2026-05-18] coaching.test.ts — 2 failures in fidelity section tests
- **Layer**: react / frontend tests
- **Trigger**: PR #5109 CI failing — SonarCloud quality gate failed
- **Hypothesis**: Pre-existing failures on develop branch, not introduced by Kamal's PR
- **Root cause**: Pre-existing on develop. `libs/db/src/transformers/coaching.test.ts` — fidelity section tests failing before Kamal's changes
- **Fix**: Unresolved — Hammad Sarfraz assigned to investigate. Kamal skipped these tests in PR for now.
- **Prevention**: Fix the underlying test on develop so future PRs don't inherit the failure
- **Time-to-resolve**: Pending
- **Notes**: Not Kamal's fault. Do not blame his PR. Separate track from SonarCloud quality gate issue.

## [2026-05-06] CMS changes caused container memory spike — Metabase 504
- **Layer**: infrastructure / Django / CMS
- **Trigger**: Abdul Ahad Fiaz flagged in #engineering — CMS changes by Kamal causing memory spike affecting all containers including Metabase
- **Hypothesis**: Kamal's CMS changes introduced unbounded memory growth (possibly large response objects, missing pagination, or unbounded querysets)
- **Root cause**: TBD — Ahad fixed symptoms temporarily, root cause not yet investigated
- **Fix**: Unresolved — needs Kamal to profile CMS memory usage
- **Prevention**: Profile before deploy; add memory limits to CMS container; add QuerySet limits
- **Time-to-resolve**: Pending
- **Notes**: Saima uses CMS for content uploads. Fix must not break her workflow.
