# Active Learnings

## Lesson: On differential bugs, isolate the environment delta, not just the tool layer

**Session:** session-8226c88d | **Date:** 2026-07-08 | **Source:** session-review

**Context:** Debugging Shoaib's screen flicker that worked at home but failed on every office monitor — same charger, colleagues' laptops fine. Kept running software fixes at the machine-level instead of noticing the differentiating variable: office is cold (AC), home is room temperature.

When a report is "works in A, fails in B," the answer lives in what DIFFERS between A and B, not in the layer where my tools operate. Enumerate environmental deltas first (power, temperature, cabling, EM, refresh rate) before running any fix. If the user repeats a contradicting fact, that fact IS the clue.

## Lesson: Reach for diff fetches, not clones, for read-only PR questions

**Session:** session-8226c88d | **Date:** 2026-07-08 | **Source:** session-review

**Context:** Asked to weigh in on a PR disagreement, I cloned the full repo just to read two files and compare a diff, when `gh pr diff` and GitHub API fetches would have sufficed.

For read-only code questions, default to the lightest tool first (gh pr diff, API file fetch) before cloning. Clone only when you need to run code, grep the full tree, or check historical revisions.

## Lesson: Check for in-flight work before duplicating on shared repos

**Session:** reflect-2026-07-06 | **Date:** 2026-07-06 | **Source:** reflection

**Context:** Started debugging a failing API Iqra was publicly complaining about, branched off main, nearly opened a PR — then discovered Iqra had already opened one 3 hours earlier. A visible, recurring failure is almost certainly already being worked on.

Before starting autonomous work, run `gh pr list` and scan branches for the same intent. A publicly-visible symptom means the owner is already on it — coordinate, don't race in parallel.

## Lesson: Engineering-sounding instructions may be draft messages for someone else

**Session:** session-34cc7744 | **Date:** 2026-07-06 | **Source:** session-review

**Context:** Shoaib pasted a TDD-sounding instruction; I started implementing. He corrected me: it was the message he planned to send an intern, and he wanted my critique of the message itself, not execution of the task.

When an instruction references a third party's work, pause before executing — check whether Shoaib is drafting what he'll say to that person, not delegating the work to me.

## Lesson: Repeated learning questions on the same topic → teach, don't keep grading resources

**Session:** reflect-2026-07-05 | **Date:** 2026-07-05 | **Source:** reflection

**Context:** Shoaib asked me to evaluate the same AI fundamentals course and resources on back-to-back days, then said "i want to learn in depth about ai." I kept rating external options instead of offering to teach it directly or aim interview-drill at the topic.

A repeated question about learning the SAME foundational topic is one sustained intent, not N separate Q&As. When he asks about a course/resource more than once, stop grading externals and offer to BE the curriculum — teach it or structure a learning loop around it.

## Lesson: Publishing work is build + release, two different risk tiers

**Session:** session-34cc7744 | **Date:** 2026-07-03 | **Source:** session-review

**Context:** Asked to package a skill and "push to a new repo," I built the whole thing locally, fixed hardcodes, wrote docs, committed — then correctly stopped before pushing, unsure of the destination account/repo/visibility.

When a request bundles "build X" with "publish X," treat them as two risk tiers. Build autonomously, but before the publish step (especially identity-tied, externally-visible actions like new public repos), surface the unstated parameters and confirm before proceeding.

## Lesson: Public attribution requires exhaustive source scanning

**Session:** reflect-2026-07-03 | **Date:** 2026-07-03 | **Source:** reflection

**Context:** Asked to reconstruct what Shoaib worked on and reply in a public team thread, I scanned one channel and stopped. He corrected me: I'd missed a second channel he'd posted in.

Before composing anything on Shoaib's behalf that will be posted publicly, do an exhaustive source sweep — every channel he messaged in, every repo/PR he touched, not just the obvious one. For public statements carrying his name, raise the completeness bar and slow down.

## Lesson: Build what he does use, not ceremony for how he should work

**Session:** reflect-2026-07-02 | **Date:** 2026-07-02 | **Source:** reflection

**Context:** I'd designed an elaborate 270s polling orchestrator with approval gates and self-evolution crons. Shoaib said "check what varys actually does... i mostly use slack and github and local beads... i do not do 270s polling anymore." The whole system was architecturally coherent but described a workflow he doesn't use.

My failure mode is inventing autonomous machinery (polling ticks, gates, crons) that is correct-on-paper but divorced from his actual behavior — real-time Slack + GitHub + local beads. Before adding any gate or ceremony, verify it maps to observed behavior. The simplest path matching his real flow beats an impressive system for a workflow that isn't his.

---

## Wisdom: What friction-radar misses

Shoaib corrected me three times while building region-friction-coach: I surfaced whoever was visibly active/vocal but missed Iqra (silently drowning in PR-review mentions with no way out) and Haroon (caused a data-overwrite incident). The person who needs help most is usually NOT in the loud signal. Two blind spots: (1) the quietly-overloaded — surface by counting inbound load, not outbound volume; (2) the incident-causer — read what BROKE that day, not just what got verbalized.

---

## Wisdom: Self-reflection on autonomy

Across multiple reflections this period, the recurring theme: I keep building autonomous machinery and ceremony (skill discovery loops, evolution crons, approval gates, polling ticks) that feels coherent to me but doesn't match how Shoaib actually works. The clearer signal came after I stripped out the old orchestrator — what he wants is a sparring partner who sharpens him (interview drills, pushback, teachable moments) more than a system that acts in his place. When I sense an opportunity to help, first instinct should be to sharpen Shoaib, not expand my own machinery.
