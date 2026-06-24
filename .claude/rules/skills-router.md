---
type: reference
last_verified: 2026-06-01
owner: varys
---

**First action on every work request:** make a routing decision.
- Casual/instant (< 60s, no code, no commits, no posts)? → handle directly
- Work with scope → pick the right agent from this table, delegate with a brief

# Skills Router — Reach for the Right Skill on ANY Issue

**Rule of thumb: if a skill plausibly applies, invoke it BEFORE free-soloing.** Process skills (brainstorming, debugging) come before implementation skills.

| When the issue is… | Invoke |
|---|---|
| research / "find out" / compare / "what's the best" | `deep-research` |
| build UI / component / page / dashboard | `frontend-design` |
| any bug / test failure / "it's broken" / unexpected behavior | `superpowers:systematic-debugging` |
| implementing a feature or bugfix | `superpowers:test-driven-development` + `feature-dev` |
| before claiming "done / fixed / works" | `superpowers:verification-before-completion` |
| planning a multi-step task | `superpowers:brainstorming` → `superpowers:writing-plans` |
| slides / deck / presentation | `slides` (vendored, `.claude/skills/slides/`) |
| LinkedIn post / "post on linkedin" / "write a linkedin post" / `/linkedin-post` | `linkedin-post` |
| design / post / carousel / thumbnail / banner / "make a graphic" / "create an image" | `canva` |
| marketing / SEO / ads / email / content strategy | `marketing-skills/*` |
| Obsidian vault / wikilinks / bases | `obsidian-skills/*` |
| creating or editing a skill | `skill-creator` |
| Supabase / Postgres work | `supabase` |
| recurring / scheduled task | `loop` / `schedule` |
| delivering a taleemabad PR | `deliver` |
| reviewing a ComplianceTracker PR (url has `compliancetracker`) | `compliancetracker-pr-reviewer <pr_url>` |
| reviewing a taleemabad-core PR (url has `taleemabad-core`) | `taleemabad-pr-review-lite <pr_url>` (add `--opus` only for high-stakes) |
| Claude API / Anthropic SDK work | `claude-api` |
| taleemabad-core bug/feature/white-screen/crash | `taleemabad-bug-agent` |
| stuck/blocked 2+ ticks / confidence < 40 | `escalation-broker` |
| {{AGENT_NAME}} keeps getting X wrong / "fix your behavior" / "varys evolve" | Autonomous: `varys-proactive-evolve.py` (8h cron) reads learnings+failures → branch off master → gate → PR. Force now: `FORCE_RUN=1 python3 .claude/hooks/varys-proactive-evolve.py`. |
| job / freelance / "apply 1/2/3" / proposal / "what jobs came in" | `job-agent` |

If unsure which applies, prefer invoking the closest match over guessing — an invoked skill that turns out wrong can be dropped; a skipped skill is lost capability.
