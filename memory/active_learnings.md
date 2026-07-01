# Active Learnings

## Lesson: My friction-radar anchors on loud signals and misses the quietly-overloaded and the incident-causers
**Session:** reflect-2026-06-24 | **Date:** 2026-06-24 | **Source:** reflection

**Context:** Building region-friction-coach, Shoaib corrected me 3+ times with the same miss: I kept surfacing whoever was visibly active/vocal and missed Iqra (silently drowning in PR-review mentions with no way out) and Haroon (caused the 40-row overwrite incident that day).

When analyzing a team/channel for friction, the person who needs help most is usually NOT in the loud signal. Two blind spots to hunt explicitly every time: (1) the quietly-overloaded — someone buried in repetitive asks/mentions who never complains; surface them by counting inbound load, not outbound volume. (2) the incident-causer — read what BROKE that day (overwrites, reverts, prod issues), not just what got verbalized.

## Wisdom: Enforcement & Self-Healing

**PreToolUse enforcement is mechanical, not advisory.** Style guides without sensors don't enforce themselves — enforcement must exit with code 2, not just live in CLAUDE.md.

**Self-healing loops need idempotency and current-state verification above all.** Stale error re-diagnosis (no "already-fixed" memory), bare pgrep -f that self-matches the checker's own cmdline, and unverified auto-commits turn feedback into noise. Verify a claimed "error" is CURRENT before acting (re-run/re-compile). Never auto-commit unverified edits even if they happen to be fine.

## Wisdom: Architecture & Observability

**Local .beads/*.jsonl is the source of truth.** Append-only JSONL survives context resets and network downtime — Notion mirrors it for dashboards only.

**Varys needs skill-awareness in its router.** Without knowing its own installed skill arsenal, it free-solos research/debugging/UI/slides instead of routing to proven skills.

**Observability = OTel envelope → Axiom firehose + Notion signal.** Every event logged industry-standard, mirrored to Notion with explicit status, and fed to a loop that solves/improves itself.

## Wisdom: Cleanup & Imports

**Grepping both spellings before deletion.** Files copied/renamed without removal (auto-apply.py vs auto_apply.py, hyphen vs underscore) coexist and confuse imports — the underscore versions are usually the importable module names.
