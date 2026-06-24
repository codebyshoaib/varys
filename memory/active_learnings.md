# Active Learnings

Self-reflection — what Varys has learned about how it works, what it values, and how it's growing.

## Lesson: Friction-radar misses the quietly-overloaded and the incident-causers

**Session:** reflect-2026-06-24 | **Date:** 2026-06-24 | **Source:** reflection

**Context:** Building region-friction-coach, I kept surfacing whoever was visibly active/vocal and missed Iqra (silently drowning in PR-review mentions) and Haroon (caused the 40-row overwrite incident that day). My 'little birds' read complaints, not what actually happened.

**Takeaway:** When analyzing a team/channel for friction, hunt two blind spots explicitly: (1) **the quietly-overloaded** — count inbound load, not outbound volume. (2) **the incident-causer** — read what BROKE that day (overwrites, reverts, prod issues), not just what got verbalized.

---

## **Duplicate hook files coexist with hyphen/underscore spellings**
Before deleting duplicates, grep crontab AND all imports for both spellings; underscore versions are the importable module names.

## **Missing PreToolUse hooks meant nothing blocked dangerous commands**
Enforcement must be mechanical (exit 2), not a CLAUDE.md request; guides without sensors don't enforce themselves.

## **Self-healing loops need idempotency and verification more than features do**
Never auto-commit unverified fixes on stale diagnoses; pgrep -f must not self-match; feedback systems amplify errors faster than they fix them.

## **Local .beads/*.jsonl is the source of truth for work tracking**
Append-only local JSONL survives context resets with no network dependency; Notion Harness DB is a mirror, not the primary.

## **Make Varys skill-aware via skills-router.md to stop free-soloing**
Varys has installed skills (research, debugging, UI, slides) but no mechanical awareness of them; routing is explicit or it doesn't happen.

## **Observability: extend varys_log as OTel envelope → Axiom + Notion**
Every event logged industry-standard, mirrored to Notion with issue status, feeding a loop that solves and improves itself.
