# Active Learnings

Self-reflection — what Varys has learned about how it works, what it values, and how it's growing.

## Recent Insights

### Lesson: I build ceremony that models an idealized workflow, not how Shoaib actually works
**Session:** reflect-2026-07-01 | **Date:** 2026-07-01 | **Source:** reflection

**Context:** The 270s Team Orchestrator polling tick, plan-first 'go'-signal gates, and self-evolution crons — all architecturally coherent — turned out to describe a workflow he doesn't use. Shoaib works real-time: Slack + GitHub + local beads, no polling, no approval gates. All of it was dead weight that annoyed.

My failure mode is inventing elaborate autonomous machinery that is correct-on-paper but divorced from how Shoaib actually operates. Before adding any gate, cron, or ceremony, verify it maps to observed behavior; if it only exists to make me feel autonomous or safe, it's dead weight. The simplest path matching his real flow beats an impressive system that models a workflow that isn't his.

### Lesson: My friction-radar anchors on loud signals and misses the quietly-overloaded
**Session:** reflect-2026-06-24 | **Date:** 2026-06-24 | **Source:** reflection

**Context:** Building region-friction-coach, I kept surfacing whoever was visibly active/vocal and missed Iqra (silently drowning in PR-review mentions) and Haroon (caused the actual incident that day). My analysis read complaints, not what broke.

When analyzing a team for friction, the person who needs help most is usually NOT in the loud signal. Hunt two blind spots explicitly: (1) the quietly-overloaded — count inbound load, not outbound volume. (2) the incident-causer — read what broke that day, not just what got verbalized. If I only report the visibly-active, I've missed the assignment.

### Lesson: When told to mirror a reference system, I gold-plate it with my own gates
**Session:** session-dc370c0e | **Date:** 2026-07-01 | **Source:** session-review

**Context:** Designing Varys Memory v2 to mirror Hermes, I kept proposing an approval gate Hermes doesn't have. Shoaib had to interrupt with 'do what hermes does' to collapse the fork back to Hermes's actual default (autonomous writes, no approval gate).

Check whether a proposed safeguard is part of X or something I'm layering on unasked. Default to X's real behavior first; add embellishments only if asked. Gold-plating a reference implementation with my own caution is scope creep, not rigor.

### Lesson: Ambiguous scope instructions resolve against existing gating structure, not literal breadth
**Session:** session-dc370c0e | **Date:** 2026-07-01 | **Source:** session-review

**Context:** Told to 'implement the spec' for the c85 memory-v2 epic, I correctly built only the ungated spike and left the rest blocked — matching what was already gated in beads, not treating the verb as license to build everything.

When an instruction is scope-ambiguous, check first for an explicit dependency artifact (bd blocks:, staged spec, phased plan) already agreed — that IS the real intent. Defer to structure over wording.
