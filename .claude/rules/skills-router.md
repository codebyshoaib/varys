---
type: reference
last_verified: 2026-06-01
owner: kamil
---

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
| design / post / carousel / thumbnail / banner / "make a graphic" / "create an image" | `canva` |
| marketing / SEO / ads / email / content strategy | `marketing-skills/*` |
| Obsidian vault / wikilinks / bases | `obsidian-skills/*` |
| creating or editing a skill | `skill-creator` |
| Supabase / Postgres work | `supabase` |
| recurring / scheduled task | `loop` / `schedule` |
| delivering a taleemabad PR | `deliver` |
| Claude API / Anthropic SDK work | `claude-api` |

If unsure which applies, prefer invoking the closest match over guessing — an invoked skill that turns out wrong can be dropped; a skipped skill is lost capability.
