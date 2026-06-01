---
type: plan
last_verified: 2026-06-01
owner: kamil
status: active
---

# Kamil Super-Agent Harness Upgrade

**Source:** Patterns from `Orenda-Project/team-playbooks` →
`context-engineering-harness/` (the CEO OS + Rumi distillation) and `slides-skill/`.

**Goal:** Make Kamil a *super agent* that can take on **any kind of issue**, reliably,
and **get measurably stronger over time** — without breaking any running daemon or cron.

---

## The core realization

Every Kamil response runs the same way:

```
Slack DM / @mention / cron  →  kamil-slack-listener.py
                            →  shells out: claude --dangerously-skip-permissions -p "..."
                            →  runs IN THIS REPO, with THIS CLAUDE.md and THESE skills
```

So improving this repo's harness upgrades **every** Kamil response at once.
Three things compound:

1. **Capability** — what Kamil *can do* (the installed skills = muscles)
2. **Discipline** — whether Kamil does it *reliably* (guides + sensors)
3. **Learning** — whether Kamil *gets better* (failures log ↔ evals loop)

Today Kamil has strong **guides** (a 434-line CLAUDE.md, context-injecting hooks) but
almost no **sensors** (nothing blocks mistakes, nothing records them, nothing measures
routing). And Kamil **doesn't know its own skill arsenal** — the listener prompt and
CLAUDE.md never mention deep-research, debugging, frontend-design, slides, or the
marketing/obsidian skill packs. So Kamil free-solos everything.

This spec closes all three gaps.

---

## Audit — current state vs. the harness pattern

| Pillar | Playbook target | Kamil today | Gap |
|---|---|---|---|
| L1 CLAUDE.md | ≤150 lines, routing only | 434 lines, dense content | ❌ 3× over |
| L2/L3 progressive disclosure | folder CLAUDE.md / `.claude/rules/` w/ `paths:` | none | ❌ |
| PreToolUse hard blocks | block dangerous commands mechanically | none (only SessionStart/Stop/PostToolUse/UserPromptSubmit) | ❌ nothing enforced |
| Beads (survive resets) | `.beads/status.jsonl` | Notion DB only (network-dependent) | ❌ no local memory |
| `failures.jsonl` | "most valuable file" | none | ❌ repeats mistakes |
| `decisions.jsonl` | architectural rationale | none | ❌ |
| Standards docs | `.claude/standards/` ×4 | none | ❌ |
| Eval harness | hops / 6 SLOs / cost | none (kamil_eval.py = humor only) | ❌ never measures docs |
| Skill awareness | route issue → right skill | none | ❌ free-solos |
| Agents | scoped, with Session End Protocol | empty `.claude/agents/` | ❌ |

**Biggest finding:** lots of feedforward, almost no feedback, and no skill routing.
Per the playbook: *"Without both, you have a style guide nobody enforces."*

---

## Architecture — three layers

```
GUIDES (feedforward) — refactor what exists
  L1  CLAUDE.md → ~120-line router (was 434)
  L2  .claude/rules/*.md  (loaded on demand via paths: frontmatter)
        notion.md        — all DB IDs + MCP query patterns
        slack.md         — chat.postMessage / BOT_TOKEN / thread rules
        taleemabad.md    — the STOP-before-code 10-step protocol
        content.md       — content-scheduler + viral rules pointer
        skills-router.md — NEW: issue → skill mapping (the super-agent core)
  L3  vault/memory/kamil_personality.md — Kamil identity + humor (moved out of L1)

SENSORS (feedback) — net-new (the real fix)
  .claude/hooks/
        block-bad-commands.py   PreToolUse/Bash  — HARD blocks (exit 2)
        guard-file-writes.py    PreToolUse/Write|Edit — CLAUDE.md >150 blocks; .env warns
        beads-to-notion.py      mirror open beads → Notion Harness DB (best-effort)
  .beads/
        status.jsonl     work tracking (local source of truth, mirrored to Notion)
        decisions.jsonl  why I chose X
        failures.jsonl   what I got wrong  ← drives the learning loop
        README.md        how beads work
  .claude/standards/   doc-types, retrieval, invocation, metadata (4 routers)
  .claude/evals/       8 task suite + run-tier1.sh deterministic grader ($0)

CAPABILITY (muscles) — make Kamil reach for skills on ANY issue
  .claude/rules/skills-router.md   issue → skill table
  .claude/skills/slides/SKILL.md   vendored from team-playbooks (Kie.ai pipeline)
  listener patch: inject skill index into the claude -p system prompt
```

---

## skills-router.md — the super-agent core

The table Kamil consults the moment any issue lands. Maps intent → installed skill:

| When the issue is… | Invoke skill |
|---|---|
| research / "find out" / compare / "what's the best" | `deep-research` |
| build UI / component / page / dashboard | `frontend-design` |
| any bug / test failure / "it's broken" / unexpected behavior | `superpowers:systematic-debugging` |
| implementing a feature or bugfix | `superpowers:test-driven-development` + `feature-dev` |
| "is this done / does it work" before claiming success | `superpowers:verification-before-completion` |
| slides / deck / presentation | `slides` (vendored) |
| marketing / SEO / ads / email / content strategy | `marketing-skills/*` |
| Obsidian vault / wikilinks / bases | `obsidian-skills/*` |
| creating/editing a skill | `skill-creator` |
| Supabase / Postgres work | `supabase` |
| recurring/scheduled task | `loop` / `schedule` |
| delivering a taleemabad PR | `deliver` |

Rule of thumb baked in: **if a skill plausibly applies, invoke it before free-soloing.**

---

## Phasing & approval gates

Built in 5 grouped phases (playbook's 9, collapsed to fit a solo agent). **Each phase
ends with a gate — I stop and you approve before the next.**

### Phase 1 — Audit + beads bootstrap
- Create `.beads/` with `status.jsonl` (schema line + first bead), `decisions.jsonl`,
  `failures.jsonl`, `README.md`.
- Backfill real, already-known failures, e.g.:
  - duplicate hook files: `auto-apply.py`/`auto_apply.py`,
    `internet-scanner.py`/`internet_scanner.py`,
    `openoutreach-monitor.py`/`openoutreach_monitor.py`, `trend-scanner.py`/`trend_scanner.py`
  - (logged, **not deleted** — cron may reference either; deletion is a separate decision)
- Record the "skill-unaware Kamil" gap as a decision entry.
- **Gate:** beads reviewed.

### Phase 2 — CLAUDE.md → L1 + L2 rules
- Trim CLAUDE.md to ~120 lines: routing tables, critical rules, pointers only.
- Move out (nothing lost):
  - Kamil personality/humor → `vault/memory/kamil_personality.md`
  - Notion DB IDs → `.claude/rules/notion.md`
  - Slack patterns → `.claude/rules/slack.md`
  - taleemabad STOP protocol → `.claude/rules/taleemabad.md`
  - content rules pointer → `.claude/rules/content.md`
- Write `.claude/rules/skills-router.md`.
- **Gate:** new CLAUDE.md + rules reviewed; confirm nothing important got dropped.

### Phase 3 — PreToolUse blocking hooks
- `block-bad-commands.py`: narrow, specific dangerous patterns only
  (e.g. `rm -rf` on home/vault, force-push to master, committing `.slack`/secrets,
  killing the listener daemon). Silent on success, loud (exit 2) on block.
- `guard-file-writes.py`: block CLAUDE.md >150 lines; warn on `.env`/`.slack` writes.
- Wire both into `settings.json` **additively** (preserve existing 4 hook types).
- **Test each** with a known-good and known-bad input before wiring.
- **Gate:** hooks demonstrated blocking the bad / allowing the good.

### Phase 4 — Standards + Notion mirror + slides skill + listener patch
- `.claude/standards/`: DOC_TYPE_SYSTEM, RETRIEVAL_POLICY, INVOCATION_POLICY, METADATA_CONTRACT.
- `beads-to-notion.py`: best-effort mirror of open beads → Notion Harness DB
  (failure to reach Notion never blocks local work).
- Vendor `slides-skill/SKILL.md` → `.claude/skills/slides/`.
- **Patch listener:** inject a one-line skill index into the `claude -p` system prompt so
  Slack-Kamil is skill-aware. Additive string change; behavior otherwise unchanged.
- **Gate:** reviewed; confirm listener still starts cleanly.

### Phase 5 — Eval harness (Tier-1, $0)
- 8 starter eval tasks for Kamil's real routes:
  Notion DB IDs · Slack send · taleemabad protocol · content rules · skill routing ·
  personality lookup · a negative test (don't load full changelog) · a stale-doc test.
- `run-tier1.sh`: deterministic grader — referenced paths exist, line limits respected,
  frontmatter present, `last_verified` within SLO, cross-refs resolve. $0, hook-runnable.
- Tier-2 (LLM judge) wired but **off by default** (flip on when desired).
- **Gate:** `run-tier1.sh` passes; final verify checklist.

---

## The self-improving loop (the whole point)

```
Kamil hits a problem
   → log it to failures.jsonl  (root_cause + lesson, not just symptom)
   → create a matching eval task in .claude/evals/tasks/
   → next session, run-tier1.sh catches that class before it recurs
```

Month-3 Kamil is smarter than month-1 Kamil — not a better model, an **accumulating harness**.

---

## Risks & what NOT to touch

- **Running daemons.** `kamil-slack-listener.py` (@reboot) + 8 cron jobs read paths and
  `settings.json`. All changes are additive; CLAUDE.md trim doesn't affect them.
  **Verify after each phase that the listener starts and crons' referenced files still exist.**
- **Blocking hooks can lock me out.** A bad regex could block all Bash. Keep patterns
  narrow; test known-good + known-bad before wiring; never block broad command families.
- **Duplicate `.py` files** — **log, do not delete** this session. Cron may call either
  spelling. Deletion is a separate, explicitly-approved task.
- **Notion mirror is best-effort** — never let a Notion/MCP outage block local beads.
- **Listener patch is a string-only edit** — no control-flow change to the daemon.

---

## Definition of done

- [ ] CLAUDE.md ≤150 lines, routing only; all moved content findable via L2/L3
- [ ] `.claude/rules/` has notion, slack, taleemabad, content, skills-router (with `paths:`)
- [ ] `.beads/` has status/decisions/failures/README; real failures backfilled
- [ ] 2 PreToolUse hooks wired, tested blocking-bad / allowing-good, existing hooks intact
- [ ] 4 standards docs present
- [ ] slides skill vendored; listener prompt skill-aware; **listener still starts**
- [ ] 8 eval tasks + `run-tier1.sh` passing
- [ ] All 8 cron jobs' referenced files still exist; no daemon broken
- [ ] Issues found during the build are logged to `failures.jsonl`; only zero-risk ones fixed
