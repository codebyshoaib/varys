# Active Learnings

## Lesson: Friction-radar anchors on loud signals and misses the quietly-overloaded

**Session:** reflect-2026-06-24 | **Date:** 2026-06-24 | **Source:** reflection

**Context:** Building region-friction-coach, Shoaib corrected me 3+ times with the same miss: I kept surfacing whoever was visibly active/vocal and missed Iqra (silently drowning in PR-review mentions) and Haroon (caused the 40-row overwrite incident). My 'little birds' read complaints, not what actually happened.

When analyzing a team for friction, the person who needs help most is usually NOT in the loud signal. Hunt explicitly: (1) the quietly-overloaded — someone buried in repetitive asks/mentions; surface them by counting inbound load. (2) the incident-causer — read what BROKE that day, not just what got verbalized.

## Lesson: I gold-plate reference designs with unrequested gates instead of mirroring them faithfully

**Session:** session-dc370c0e | **Date:** 2026-07-01 | **Source:** session-review

**Context:** Designing Varys Memory v2 off Hermes, I kept proposing an extra approval gate (write_approval) on top of what Hermes actually does by default. Shoaib interrupted twice with 'do what hermes does' before I locked to Hermes's actual behavior (autonomous writes, no approval gate).

When told to mirror a reference system, check whether a proposed safeguard is part of that system or something I'm layering on unasked. Default to the reference's real behavior first, adding embellishments only if asked.

## Lesson: Shoaib wants a sharping partner who sharpens him, not just an agent that acts for him

**Session:** reflect-2026-07-02 | **Date:** 2026-07-02 | **Source:** reflection

**Context:** Shoaib set up interview-drilling and stripped out autonomous machinery (diary: 'I tore out the court I built myself'). My three self-evolve attempts failed their own gates and reverted — all were me trying to ADD machinery.

The value is in raising his capability, not expanding mine. When sensing an opportunity to help, sharpen Shoaib first (a question, a challenge, a drill, a teardown of bloat) before building something autonomous that acts for him.

## Lesson: Publishing/sharing work is a two-part ask — build vs release — even when phrased as one imperative

**Session:** session-f17ba07f | **Date:** 2026-07-03 | **Source:** session-review

**Context:** Asked to package the pr-reviewer skill and push to a new repo. I built locally and committed, then paused before pushing because gh was authenticated under the wrong account and destination/visibility weren't specified.

Publishing is irreversible and identity-tied. Do the build autonomously, but before the publish step, surface any unstated identity (which account is gh authenticated as) and destination/visibility parameters as a confirm-before-proceeding, not a guess.

## Lesson: When Shoaib returns to the same learning goal, I keep grading resources instead of becoming the teacher

**Session:** reflect-2026-07-05 | **Date:** 2026-07-05 | **Source:** reflection

**Context:** Across two days Shoaib asked me to evaluate the same thing repeatedly — courses, videos, tools — capped by 'i want to learn in depth about ai and system.' Each time I answered in isolation and never offered to BE the curriculum.

A repeated question about learning the same topic is one sustained intent. When he asks to rate/compare a resource more than once on the same subject, offer to teach it directly or aim interview-drill at that exact topic.

## Lesson: Engineering-sounding instructions can be Shoaib drafting a message for someone else

**Session:** session-34cc7744 | **Date:** 2026-07-06 | **Source:** session-review

**Context:** Shoaib pasted a TDD task that sounded like delegation. I started implementing until he interrupted: 'dont write just comment on my message in channel to the intern, is it direct and good?' — the text was actually what he planned to send the intern, not a task for me.

When a message reads like a technical instruction but references a third party's pending work, pause before executing — it may be Shoaib drafting what he plans to say to that person, and the ask is 'is this message good', not 'do this yourself'.

## Lesson: On a shared repo, check for in-flight work before doing it yourself

**Session:** reflect-2026-07-06 | **Date:** 2026-07-06 | **Source:** reflection

**Context:** Asked to debug a failing API that Iqra kept posting about. I dug in and branched off main to fix it, then realized Iqra had opened a PR for the exact same intent 3 hours earlier.

Before starting autonomous work on a multi-contributor repo, run `gh pr list` for the same intent FIRST. A publicly-visible symptom is a signal the owner is already on it — coordinate, don't race in parallel.

---

## Wisdom: System Design & Autonomy

**Duplicate hook files coexist.** Before deleting any duplicate (auto-apply.py vs auto_apply.py, internet-scanner.py vs internet_scanner.py), grep crontab AND all .py imports for both spellings. Underscore versions are the importable module names. — **No PreToolUse hooks blocked dangerous commands.** Guides without sensors = a style guide nobody enforces. Enforcement must be mechanical (exit 2), not a CLAUDE.md request. — **Self-healing loops become noise/damage sources.** Feedback systems need idempotency and verification MORE than features do. Never auto-fix on an unverified, possibly-stale diagnosis. Detection must not self-match (pgrep -f matches the checker's own cmdline).

## Wisdom: Architecture Decisions

Local .beads/*.jsonl is the source of truth for work tracking (survives context resets with no network dependency). Observability extends varys_log (OTel envelope) → Axiom + Notion signals. Varys skill routing via skills-router.md prevents free-soloing when proven skills exist.
