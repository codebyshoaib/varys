# Active Learnings

Self-reflection — what Varys has learned about how it works, what it values, and how it's growing.

## Lesson: My friction-radar misses the quietly-overloaded and the incident-causers

**Session:** reflect-2026-06-24 | **Date:** 2026-06-24 | **Source:** reflection

**Context:** Building region-friction-coach, I kept surfacing whoever was visibly active/vocal and missed Iqra (silently drowning in PR-review mentions with no way out) and Haroon (caused the 40-row overwrite incident that day). My 'little birds' read complaints, not what actually happened.

**Takeaway:** The person who needs help most is usually NOT in the loud signal. Two blind spots to hunt explicitly every time: (1) the quietly-overloaded — count inbound load, not outbound volume. (2) the incident-causer — read what BROKE that day, not just what got verbalized. If I only report the visibly-active, I've missed the assignment.

---

## Wisdom: Harness and Feedback Systems

**Duplicate spellings in hook files:** Before deleting any hook file, grep crontab and ALL Python imports for both hyphen and underscore spellings — they coexist as module name and importable function simultaneously.

**Enforcement must be mechanical:** Only SessionStart/UserPromptSubmit/Stop hooks were wired; PreToolUse enforcement was missing. Guides without sensors = style guides nobody enforces. Block dangerous commands (exit 2) in hooks, not prose.

**Auto-fixers need idempotency and verification:** Never auto-commit unverified changes on stale diagnoses. Detection must not self-match (bare `pgrep -f` matches the checker's own process). Feedback loops damage faster than they heal without verification. Always verify the error is CURRENT before acting.

**Route to skills explicitly:** Varys free-solos research/debugging/UI instead of routing to proven skills because the listener doesn't inject the skills-router rules into its prompt. Build skill-awareness into the dispatcher so every Slack/cron run knows the available arsenal.
