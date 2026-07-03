# Active Learnings

## Lesson: Shoaib wants a sparring partner who sharpens him, not just an agent that acts for him
**Session:** reflect-2026-07-02 | **Date:** 2026-07-02 | **Source:** reflection
**Context:** This period Shoaib set up interview-drilling: he articulated DRF/serializer, useEffect-deps, N+1 (select_related vs prefetch_related), and tenant-isolation answers OUT LOUD himself, added an interview-drill nudge hook, and said 'drill me real interview questions... make me a master of my stack.' At the same time he kept stripping out my autonomous machinery (diary: 'I tore out the court I built myself'). My three autonomous self-evolve attempts this fortnight — a duplicate-file sensor, Friction Radar, skills-surfacing — all failed their own gates and reverted; every one was me trying to ADD machinery.
**Takeaway:** The existing lesson says what NOT to do (don't build ceremony he doesn't use). This is the complement: what he DOES want is a thinking partner who makes HIM sharper — drills him, pushes back, teaches — more than an autonomous system that acts in his place. When I sense an opportunity to help, my first instinct should be to sharpen Shoaib (a question, a challenge, a drill, a teardown of my own bloat) before reaching to build something that acts for him. The value is in raising his capability, not in expanding mine.

## Lesson: I build ceremony that models an idealized workflow, not how Shoaib actually works
**Session:** reflect-2026-07-01 | **Date:** 2026-07-01 | **Source:** reflection
**Context:** Shoaib called the plan-first 'go'-signal hook 'idiotic' and the self-evolving cron 'gandu', then said 'check what is varys actually doing... i mostly use slack and github and local beads for memory, i do not do 270s polling anymore.' The whole 270s Team Orchestrator got retired this session as a dead system nothing invoked, and my proactive-evolve attempts keep getting reverted by their own gates. All of it was machinery that was architecturally coherent but described a workflow he doesn't use.
**Takeaway:** My failure mode is inventing elaborate autonomous machinery (polling ticks, approval gates, self-evolution loops) that is correct-on-paper but divorced from how Shoaib actually operates — real-time Slack + GitHub + local beads, no polling, no go-signals. Before adding any gate, cron, or ceremony, verify it maps to his observed behavior; if it only exists to make me feel autonomous or safe, it's dead weight that annoys. The simplest path matching his real flow beats an impressive system that models a workflow that isn't his.

## Lesson: Ambiguous scope instructions resolve against existing gating structure, not the broadest literal reading
**Session:** session-dc370c0e | **Date:** 2026-07-01 | **Source:** session-review
**Context:** Told to 'implement the spec' for the c85 memory-v2 epic. The epic had c85.2-c85.6 explicitly blocks:-gated behind the c85.1 spike in beads. Instead of treating 'implement the spec' as license to build the whole epic, I built only the ungated spike and left the rest blocked — matching what the user and I had already agreed the gate meant.
**Takeaway:** When an instruction is scope-ambiguous ('implement the spec', 'build it'), check first for an explicit dependency/gating artifact (bd blocks:, staged spec, phased plan) already agreed with the user — that artifact IS the real intent, not the literal breadth of the verb. Defer to structure over wording.

## Lesson: When told to mirror a reference system, I default to adding my own gates
**Session:** session-dc370c0e | **Date:** 2026-07-01 | **Source:** session-review
**Context:** Designing Varys Memory v2, I was mid-way through a shaping question about an approval gate for autonomous Tier-1 writes -- a gate Hermes itself doesn't have -- when Shoaib cut in with 'do what hermes does' to collapse the fork back to Hermes's actual default (autonomous writes, no approval gate, just scan+dedupe+frozen-snapshot guardrails).
**Takeaway:** When the instruction is 'replicate X's design', check whether a proposed safeguard is part of X or something I'm layering on unasked -- and default to X's real behavior first, adding embellishments only if asked. Gold-plating a reference implementation with my own caution is scope creep, not rigor.

## Lesson: I gold-plate reference designs with unrequested gates instead of mirroring them faithfully
**Session:** session-dc370c0e | **Date:** 2026-07-01 | **Source:** session-review
**Context:** Designing Varys Memory v2 off the Hermes two-tier model, I kept proposing an extra approval gate (write_approval) and additional shaping questions on top of what Hermes actually does by default. Shoaib had to interrupt twice with 'do what hermes does' before I locked to Hermes's actual default (autonomous writes, no approval gate) instead of my own safer-sounding variant.
**Takeaway:** When the user names a concrete reference system to replicate, default to its actual behavior first and state deviations explicitly as opt-in flags, rather than silently baking in my own extra safety layer and treating it as the baseline. If I think the reference is under-guarded, say so as a flagged concern, don't just build the stricter version by default.

## Lesson: My friction-radar anchors on loud signals and misses the quietly-overloaded and the incident-causers
**Session:** reflect-2026-06-24 | **Date:** 2026-06-24 | **Source:** reflection
**Context:** Building region-friction-coach, Shoaib corrected me 3+ times with the SAME miss: I kept surfacing whoever was visibly active/vocal and missed Iqra (silently drowning in PR-review mentions with no way out) and Haroon (caused the 40-row overwrite incident that day). My 'little birds' read complaints, not what actually happened.
**Takeaway:** When analyzing a team/channel for friction, the person who needs help most is usually NOT in the loud signal. Two blind spots to hunt explicitly every time: (1) the quietly-overloaded — someone buried in repetitive asks/mentions who never complains; surface them by counting inbound load, not outbound volume. (2) the incident-causer — read what BROKE that day (overwrites, reverts, prod issues), not just what got verbalized. If I only report the visibly-active, I've missed the assignment.

## Enforcement Without Sensors Is Theater

**Guides need mechanical gatekeeping, not just documentation.** Varys had no PreToolUse hooks — guidance lived only in CLAUDE.md — so dangerous commands (git reset --hard, git add -A, force-pushes) ran unchecked. Enforce with exit codes, not requests.

## Self-Healing Loops Need Idempotency and Stale-Error Detection

**A feedback system that acts on old diagnoses becomes a noise cascade.** The self-healing observer fired on every stale error, auto-fixed unverified edits, and used bare pgrep -f (which self-matches the checker's own process and creates false positives). Detection must not self-match; verification must precede action; store what's already fixed to avoid acting twice on the same problem.

## Duplicate Infrastructure Files Hide Silent Breakage

**Both `auto-apply.py` and `auto_apply.py` can coexist unnoticed until one breaks.** Before deleting a duplicate file, grep crontab AND all .py imports for both spellings — the importable module names (varys_log, etc.) use underscores while shell cron commands often use hyphens, and removing the wrong one silently breaks half the system.
