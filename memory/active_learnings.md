# Active Learnings

## Lesson: Friction-radar anchors on loud signals and misses the quietly-overloaded
**Session:** reflect-2026-06-24 | **Date:** 2026-06-24 | **Source:** reflection

**Context:** When analyzing team friction, I surfaced visibly vocal people and missed Iqra (silently drowning in PR-review mentions) and Haroon (caused the 40-row incident that day).

**Takeaway:** The person who needs help most is usually NOT in the loud signal. Explicitly hunt: (1) the quietly-overloaded — count inbound load, not outbound volume. (2) the incident-causer — read what broke that day, not what got verbalized. Signal from activity volume misses both.

---

## Feedback systems need idempotency and verification above all else
**Session:** varys-2026-06-01 | **Date:** 2026-06-01 | **Source:** failure-log

A self-healing loop amplified bugs when it auto-diagnosed stale errors (no idempotency), auto-fixed unverified issues (no review), and self-matched on detection (bare `pgrep -f` false-positives). Detection must not match the observer's own process; diagnosis must verify the error is CURRENT before acting; edits must be reviewed before commit.

---

## Make Varys skill-aware
**Session:** varys-2026-06-01 | **Date:** 2026-06-01 | **Source:** architecture-decision

Slack/cron Varys runs without learning its installed skill arsenal, so it free-solos research/debugging/design when proven skills could do it better. Inject `skills-router.md` into listener and cron-Varys prompts to route automatically.
