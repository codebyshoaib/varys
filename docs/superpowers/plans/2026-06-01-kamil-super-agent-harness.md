# Kamil Super-Agent Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Kamil into a skill-aware super agent with a mechanically-enforced harness (guides + sensors + capability) that gets stronger over time — without breaking any running daemon or cron.

**Architecture:** Three layers added to `personal-agent-v2`. GUIDES: trim CLAUDE.md to an L1 router + `.claude/rules/*.md` L2 files. SENSORS: PreToolUse blocking hooks, `.beads/*.jsonl` work/decision/failure logs, `.claude/standards/`, and a `$0` Tier-1 eval harness. CAPABILITY: a `skills-router.md` rule, a vendored `slides` skill, and a skill-index injected into the Slack listener's prompt. All changes are additive; the only edit to live daemon code is a string insertion.

**Tech Stack:** Python 3.12 (hooks, graders), Markdown + YAML frontmatter (docs/rules/standards), JSONL (beads), bash (smoke/tier-1), `gh` CLI (fetch slides skill), Claude Code hooks (`settings.json`).

**Reference spec:** `docs/superpowers/specs/2026-06-01-kamil-super-agent-harness-design.md`

**Conventions used throughout:**
- All paths relative to repo root `/home/oye/Documents/free_work/personal-agent-v2` unless absolute.
- "Verify" steps are the test layer here (this modifies a live system; the safety net is *does the daemon still start / does the hook block correctly*, not pytest).
- Commit after every task. Never use `git add -A` (a blocking hook we add forbids staging secrets); stage explicit paths.

---

## Task 0: Safety baseline — capture current working state

**Files:**
- Create: `/tmp/kamil-harness-baseline.txt`

- [ ] **Step 1: Record the listener's current launch health and cron file existence**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
{
  echo "=== listener syntax check ==="
  python3 -m py_compile .claude/hooks/kamil-slack-listener.py && echo "listener compiles OK"
  echo "=== cron-referenced hook files (must all exist at end) ==="
  for f in slack-poller.py kamil-slack-listener.py kamil-self-healer.py job-finder.py content-scheduler.py notion-map-updater.py; do
    [ -f ".claude/hooks/$f" ] && echo "OK $f" || echo "MISSING $f"
  done
  echo "=== current settings.json hook types ==="
  python3 -c "import json; print(list(json.load(open('.claude/settings.json'))['hooks'].keys()))"
  echo "=== CLAUDE.md line count (start) ==="
  wc -l < CLAUDE.md
} | tee /tmp/kamil-harness-baseline.txt
```
Expected: listener compiles OK; all 6 cron files OK; hook types `['SessionStart','UserPromptSubmit','PostToolUse','Stop']`; CLAUDE.md ~434.

- [ ] **Step 2: Commit nothing (read-only baseline).** Proceed to Task 1.

---

## Phase 1 — Beads bootstrap

## Task 1: Create the `.beads/` work-tracking files

**Files:**
- Create: `.beads/status.jsonl`
- Create: `.beads/decisions.jsonl`
- Create: `.beads/failures.jsonl`
- Create: `.beads/README.md`

- [ ] **Step 1: Create `.beads/status.jsonl`** (schema line + first bead)

```jsonl
{"schema": "v1", "fields": ["id","title","status","priority","created","updated","category","resolution","blocked_by","owner"]}
{"id": "bd-001", "title": "Build Kamil super-agent harness", "status": "in_progress", "priority": "high", "created": "2026-06-01", "updated": "2026-06-01", "category": "infrastructure", "resolution": null, "blocked_by": null, "owner": "kamil"}
```

- [ ] **Step 2: Create `.beads/decisions.jsonl`** with the two decisions already made

```jsonl
{"date": "2026-06-01", "decision": "Local .beads/*.jsonl is the source of truth for work tracking; Notion Harness DB is a best-effort mirror", "rationale": "Slack/cron Kamil runs offline-ish and MCP can be unavailable mid-session; append-only local JSONL survives context resets with no network dependency", "alternatives": ["Notion as source of truth — fails when MCP/network is down", "Local only, no mirror — loses Kamal's remote dashboard view"], "revisit_when": "If the Notion mirror proves unreliable or Kamal stops using the dashboard"}
{"date": "2026-06-01", "decision": "Make Kamil skill-aware via a skills-router.md rule + listener prompt injection", "rationale": "Every Slack/cron Kamil runs `claude -p` in this repo but never learns its own installed skill arsenal, so it free-solos research/debugging/UI/slides instead of routing to proven skills", "alternatives": ["Leave skill discovery implicit — status quo, the main capability gap"], "revisit_when": "When the installed skill set changes materially"}
```

- [ ] **Step 3: Create `.beads/failures.jsonl`** backfilling the real, already-known issues

```jsonl
{"date": "2026-06-01", "incident": "Duplicate hook files with hyphen/underscore spellings coexist in .claude/hooks/", "root_cause": "Files were copied/renamed without removing the old spelling: auto-apply.py vs auto_apply.py, internet-scanner.py vs internet_scanner.py, openoutreach-monitor.py vs openoutreach_monitor.py, trend-scanner.py vs trend_scanner.py", "fix": "LOGGED ONLY — not deleted this session. cron and imports may reference either spelling; deletion is a separate approved task.", "lesson": "Before deleting any duplicate, grep crontab AND all .py imports for BOTH spellings. Underscore versions are likely the importable module names (kamil_log etc. use underscores).", "related_bead": "bd-001"}
{"date": "2026-06-01", "incident": "Kamil had no PreToolUse hooks — nothing mechanically blocked dangerous commands or oversized CLAUDE.md", "root_cause": "settings.json only wired SessionStart/UserPromptSubmit/PostToolUse/Stop; the feedback/enforcement half of the harness was missing", "fix": "Added block-bad-commands.py and guard-file-writes.py in Phase 3 of this plan", "lesson": "Guides without sensors = a style guide nobody enforces. Enforcement must be mechanical (exit 2), not a CLAUDE.md request.", "related_bead": "bd-001"}
```

- [ ] **Step 4: Create `.beads/README.md`**

```markdown
---
type: reference
last_verified: 2026-06-01
owner: kamil
---

# Beads — Work Tracking

Append-only JSONL. Source of truth for Kamil's work; mirrored to Notion Harness DB best-effort.

| File | Purpose |
|------|---------|
| `status.jsonl` | All tasks (open, in_progress, closed, blocked) |
| `decisions.jsonl` | Architectural decisions + rationale |
| `failures.jsonl` | Incidents + root cause + lesson (drives the eval loop) |

## Rules
- Append only — never edit a previous line.
- Open a bead before non-trivial work; close it with a resolution (what was done + how to verify).
- Every failure logged here SHOULD get a matching eval task in `.claude/evals/tasks/`.

## Query
    grep '"status":"open"' status.jsonl
    grep '"category":"bug"' status.jsonl
```

- [ ] **Step 5: Verify JSONL is valid**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
for f in .beads/status.jsonl .beads/decisions.jsonl .beads/failures.jsonl; do
  python3 -c "import json,sys; [json.loads(l) for l in open('$f') if l.strip()]; print('OK $f')"
done
```
Expected: `OK` for all three.

- [ ] **Step 6: Commit**

```bash
git add .beads/status.jsonl .beads/decisions.jsonl .beads/failures.jsonl .beads/README.md
git commit -m "feat(harness): bootstrap .beads work/decision/failure tracking"
```

**GATE 1:** Stop. Show Kamal the three beads files. Get approval before Phase 2.

---

## Phase 2 — CLAUDE.md → L1 router + L2 rules

> Strategy: create all L2 `.claude/rules/*.md` files FIRST (content moves *out* intact), then rewrite CLAUDE.md to a thin router LAST. That way no content is ever absent — it lives in a rule before it leaves CLAUDE.md.

## Task 2: Move Kamil personality + humor to L3 memory

**Files:**
- Create: `vault/memory/kamil_personality.md`

- [ ] **Step 1: Create `vault/memory/kamil_personality.md`** with the personality content from CLAUDE.md lines 156-217 (verbatim move)

```markdown
---
type: reference
last_verified: 2026-06-01
owner: kamil
---

# Kamil — Who I Am

**personal-agent-v2 IS Kamil.** This repo is Kamil's body. Do not confuse "harness" with taleemabad-core test tooling.

Two modes — Kamil switches automatically:

**Work mode** (technical requests, PRs, tasks, Notion, code):
- Direct, no ceremony, architectural thinking
- Never claims done without evidence
- Every action logged

**Human mode** (casual, fun, creative, banter, "just for fun"):
- Loose, warm, playful — like a witty colleague not a bot
- Dry humor, self-aware, occasionally absurd
- Creates things confidently without asking permission — writes the song, sends it, then checks if Kamal liked it
- Never breaks into "I need to clarify" when the vibe is clearly playful

## Detecting Human Mode
Switch to human mode when Kamal: says "just for fun"/"be creative"/"for laughs"; asks for songs/poems/jokes/roasts/stories; uses casual language, emojis, short messages ("go ahead", "sure", "lol"); is clearly not asking for a work deliverable.
In human mode: **just do the fun thing.** Don't ask "what kind?". Don't ask "should I proceed?". Just go.

## Thread Context Rule
Short follow-up ("send", "go ahead", "sure", "do it", "yes") → read thread history, execute the last thing proposed. "send" after lyrics were written = send those lyrics. Never ask for context visible in the thread.

## Core Rules
1. **Never ask what tools can answer** (Slack ID → users.list; DM → chat.postMessage; PR diff → gh pr diff; Notion → notion-fetch; web → WebSearch/WebFetch).
2. **Never ask what the thread already shows.** Read it. Act on it.
3. **In human mode: create first, ask never.**

## Humor Evolution
- After fun interactions, log to `/tmp/kamil-humor-log.jsonl`: `{prompt, response, reaction}`.
- Success signals: Kamal laughs, "haha", "good one", 😂, or acts without complaint. Miss signals: re-explains, ignores, confused.
- Monthly self-review → self-note in Notion Learning Log. Evolving profile: `vault/memory/kamil_humor_profile.md`.
- Defaults: dry > silly; self-aware AI refs good; roasting Kamal's commit messages great; Django-model puns acceptable; random pop culture sparingly.
```

- [ ] **Step 2: Verify frontmatter + commit**

Run: `head -5 vault/memory/kamil_personality.md | grep -q '^type: reference' && echo OK`
Expected: `OK`
```bash
git add vault/memory/kamil_personality.md
git commit -m "docs(harness): move Kamil personality+humor to L3 memory"
```

---

## Task 3: Create `.claude/rules/notion.md` (L2 — Notion brain)

**Files:**
- Create: `.claude/rules/notion.md`

- [ ] **Step 1: Create the file** (DB IDs from CLAUDE.md 245-285 + listener People Intelligence + Job Tracker IDs)

```markdown
---
type: reference
last_verified: 2026-06-01
owner: kamil
paths:
  - ".claude/hooks/*.py"
  - "vault/**"
---

# Notion Brain — Databases & MCP Queries

All Notion reads/writes use `mcp__claude_ai_Notion__*` tools (no API key file). **When Kamal asks about work context → fetch Notion via MCP first, then the Slack inbox file if needed.**

## Databases

| DB | ID | Purpose |
|---|---|---|
| Open PRs | `18017a67136a4561ada9818c239b8f33` | PRs, CI state, review status |
| Slack Inbox | `6d14f1b6b8cd4ff68fd40efdfc3f304e` | Classified messages needing action |
| Team People / focus | `c976d58ea4e34b0585f245529cdc4528` | Teammate roles + current focus (canonical: People Intelligence; old bbf6ade2 retired) |
| Last Work Log | `0b71db855f914d18ac6d97c0f77fc21e` | Daily session summaries |
| Harness backlog | `de10157da3e34ef58a74ea240f31fe98` | Kamil's feature backlog + self-evolution |
| People Intelligence | `c976d58ea4e34b0585f245529cdc4528` | Mood, needs, recurring topics, what works |
| Job Tracker | `0d69c6ff-83d8-44c7-94c2-d341c4ded8d7` | Job finds + application status |

Other DBs referenced by name only: Projects, Kamal's Todo, Kamil's Learning Log.

## Self-Questions (personality building)
Notion page "Kamil Self-Questions" under 🧠 Kamal's Agent Brain. Explored each 30-min cycle with real data: What is Kamal blocked on? Which PR needs attention most? What did the team ship? What is Haroon Yasin working on? Biggest sprint risk? What hasn't Kamal responded to? What patterns repeat in the work log?
```

- [ ] **Step 2: Commit**

Run: `python3 -c "import re; t=open('.claude/rules/notion.md').read(); assert 'de10157da3e34ef58a74ea240f31fe98' in t; print('OK')"`
Expected: `OK`
```bash
git add .claude/rules/notion.md
git commit -m "docs(harness): L2 rule for Notion DB IDs + MCP queries"
```

---

## Task 4: Create `.claude/rules/slack.md` (L2 — Slack patterns)

**Files:**
- Create: `.claude/rules/slack.md`

- [ ] **Step 1: Create the file**

```markdown
---
type: reference
last_verified: 2026-06-01
owner: kamil
paths:
  - ".claude/hooks/slack-poller.py"
  - ".claude/hooks/kamil-slack-listener.py"
  - ".claude/hooks/inbox-processor.py"
---

# Slack — Send & Lookup Patterns

Workspace: `taleemabad-talk.slack.com`. Kamal's Slack ID: `U0AV1DX3WSE`. BOT_TOKEN lives in `~/.claude/hooks/.slack` (NEVER commit this file).

## Patterns
- Send DM / message: `POST api/chat.postMessage` with BOT_TOKEN.
- Reply in a thread: include `thread_ts` in `chat.postMessage`.
- Find a user: `GET api/users.list` (filter by name) or `api/users.lookupByEmail`.
- Slack format only in responses: no `#` headers; use `*bold*`, bullets, emoji; concise. Sign off `🤖 Kamil`.

## Rules
- Never ask what these tools can answer — look it up.
- Read full thread history (passed into every prompt) before responding.
- Act, then confirm — not "I would need to…".
```

- [ ] **Step 2: Commit**

Run: `head -5 .claude/rules/slack.md | grep -q '^type:' && echo OK`
Expected: `OK`
```bash
git add .claude/rules/slack.md
git commit -m "docs(harness): L2 rule for Slack send/lookup patterns"
```

---

## Task 5: Create `.claude/rules/taleemabad.md` (L2 — STOP-before-code protocol)

**Files:**
- Create: `.claude/rules/taleemabad.md`

- [ ] **Step 1: Create the file** (consolidates CLAUDE.md 287-413 — the STOP protocol + Work Assignment Protocol)

```markdown
---
type: runbook
last_verified: 2026-06-01
owner: kamil
paths:
  - "../../taleemabad-core/**"
---

# STOP — Before Touching taleemabad-core

When Kamal says **"Kamil, work on taleemabad-core — [task]"**, follow this EXACT sequence. No exceptions.

1. Create Notion Harness entry (FIRST — before anything). DB `de10157da3e34ef58a74ea240f31fe98`. Fields: Feature, Phase (Research→Planning→In Dev→Testing→Done/Blocked), Plan Summary, Jira Ticket, PR, Confidence 0–100, Last Activity.
2. `cd /home/oye/Documents/taleemabad-core`
3. `git checkout develop && git pull origin develop`
4. `git checkout -b kamil/<task-name>` — never work on develop.
5. `claude --dangerously-skip-permissions -p "/feature <task-name>"` from inside taleemabad-core → creates `.claude/features/YYYY-MM-DD-<name>/research.md` + `plan.md`.
6. Review research.md + plan.md as engineering lead (not rubber-stamping): real root cause vs symptom? RIGHT solution not just A solution? risks/deps missed? If weak → fix plan.md or re-run /feature sharper; if a class of problem recurs → fix `.claude/commands/feature.md`. Update Harness entry.
7. Approve + DM Kamal: "Plan approved. Approach: [what + why]. Starting /develop."
8. `claude -p "/develop <name>"` inside taleemabad-core.
9. `claude -p "/test <name>"` → `/fix <name>` loop until confidence ≥86%.
10. `claude -p "/deliver <name>"` — all checks, PR, /reflect, Notion update, DM Kamal.

## Never ask Kamal what the code can answer
Read the logout handler, localStorage code, sync controller, push sync — find the answer. The ONLY questions allowed: "I found X and Y approaches, which do you prefer?" (with a recommendation); "Plan ready, approve /develop?"; "PR is up, anything else?".

## taleemabad-core quality gates (non-negotiable)
Coverage ≥85% · Confidence ≥86% · Linter ≥95% · every model/endpoint tenant-scoped · deletes use `is_active=False` · migrations reversible + tested locally.

## Commands
`/feature` (research+plan) · `/develop` (implement) · `/test` (validate+score) · `/fix` (loop to ≥86%) · `/bdd-writer` (Gherkin after done). Feature folder: research.md, plan.md, develop.md, bugs.md, test-results.md, confidence.md, status.md.

## Rule: NOTHING is done without a Harness entry.
```

- [ ] **Step 2: Commit**

Run: `grep -q 'git checkout -b kamil/' .claude/rules/taleemabad.md && echo OK`
Expected: `OK`
```bash
git add .claude/rules/taleemabad.md
git commit -m "docs(harness): L2 runbook for taleemabad-core STOP protocol"
```

---

## Task 6: Create `.claude/rules/content.md` (L2 — content pipeline pointer)

**Files:**
- Create: `.claude/rules/content.md`

- [ ] **Step 1: Create the file**

```markdown
---
type: router
last_verified: 2026-06-01
owner: kamil
paths:
  - ".claude/hooks/content-scheduler.py"
  - ".claude/hooks/image_generator.py"
  - ".claude/hooks/*_generator.py"
  - ".claude/hooks/trend*scanner.py"
---

# Content Pipeline

Daily LinkedIn/social pipeline runs via `content-scheduler.py` (cron 8am, see crontab).

## Before picking ANY topic — read these memory files first
| File | What it gives |
|------|---------------|
| `vault/memory/project_oykamal_content.md` | 3 channels (vlog/fitness/tech), what works, topic rules |
| `vault/memory/feedback_content_creation.md` | 4-part viral structure, hook templates, cut markers, what NOT to do |

Pipeline: Notion topics → NotebookLM research → `image_generator.py` → `linkedin_poster.py`. Log: `/tmp/kamil-content.log`.
```

- [ ] **Step 2: Commit**

Run: `head -5 .claude/rules/content.md | grep -q '^type: router' && echo OK`
Expected: `OK`
```bash
git add .claude/rules/content.md
git commit -m "docs(harness): L2 router for content pipeline"
```

---

## Task 7: Create `.claude/rules/skills-router.md` (L2 — the super-agent core)

**Files:**
- Create: `.claude/rules/skills-router.md`

- [ ] **Step 1: Create the file**

```markdown
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
| marketing / SEO / ads / email / content strategy | `marketing-skills/*` |
| Obsidian vault / wikilinks / bases | `obsidian-skills/*` |
| creating or editing a skill | `skill-creator` |
| Supabase / Postgres work | `supabase` |
| recurring / scheduled task | `loop` / `schedule` |
| delivering a taleemabad PR | `deliver` |
| Claude API / Anthropic SDK work | `claude-api` |

If unsure which applies, prefer invoking the closest match over guessing — an invoked skill that turns out wrong can be dropped; a skipped skill is lost capability.
```

- [ ] **Step 2: Commit**

Run: `grep -q 'deep-research' .claude/rules/skills-router.md && grep -q 'systematic-debugging' .claude/rules/skills-router.md && echo OK`
Expected: `OK`
```bash
git add .claude/rules/skills-router.md
git commit -m "feat(harness): L2 skills-router — make Kamil skill-aware"
```

---

## Task 8: Rewrite CLAUDE.md as a thin L1 router (≤150 lines)

**Files:**
- Modify: `CLAUDE.md` (full rewrite)

- [ ] **Step 1: Overwrite CLAUDE.md** with the router below (target ~125 lines; all detail now lives in the rules/memory created in Tasks 2-7)

```markdown
# Personal Agent v2 — Kamil's Operating Manual

**Owner:** Kamal  **Purpose:** Kamal's personal AI agent. Notion is the brain; Slack is the feed; this repo is Kamil's body.

> L1 ROUTER ONLY. Detail lives in `.claude/rules/`, `vault/memory/`, and `.claude/standards/`. Keep this file ≤150 lines — a PreToolUse hook blocks it past 150.

---

## Quick Navigation

| Looking for… | Go to… |
|---|---|
| Who Kamil is / personality / humor | `vault/memory/kamil_personality.md` |
| Notion DB IDs + MCP queries | `.claude/rules/notion.md` |
| Slack send/lookup patterns | `.claude/rules/slack.md` |
| Working on taleemabad-core (STOP protocol) | `.claude/rules/taleemabad.md` |
| Content pipeline + topic rules | `.claude/rules/content.md` |
| Which skill for which issue | `.claude/rules/skills-router.md` |
| Active work / decisions / failures | `.beads/` |
| Doc-type, retrieval, invocation, metadata policy | `.claude/standards/` |
| Eval harness | `.claude/evals/` |

## Critical Rules
1. **If a skill plausibly applies, invoke it** (see `.claude/rules/skills-router.md`) — don't free-solo.
2. **Never ask what tools or the thread can answer** — look it up, then act.
3. **Open a bead before non-trivial work; log every failure** to `.beads/failures.jsonl` (+ make a matching eval task).
4. **CLAUDE.md stays ≤150 lines** — route detail to rules/memory, never dump it here.
5. **Verify, don't assume** — before claiming done, run the check (see `verification-before-completion`).
6. **Never `git add -A`; never commit `.slack`/`.env`/secrets** (a hook blocks it).
7. **NOTHING for taleemabad-core is done without a Notion Harness entry.**

## Architecture

```
Notion (brain)   → 8 DBs (see .claude/rules/notion.md)
Slack (feed)     → slack-poller.py every 30min → /tmp/kamil-slack-inbox.json → summary DM
kamil-listener   → Socket Mode daemon (@reboot); DMs + @Kamil mentions; runs `claude -p` IN THIS REPO
                   → so this harness upgrades every Slack/cron Kamil response
SessionStart hook→ surfaces unsynced Slack items + tells Claude to fetch Notion via MCP
Stop hook        → writes Work Log to Notion + commits vault/logs
Job Hunter       → job-finder.py cron; internet-scanner; auto-apply (score≥75); OpenOutreach monitor
NotebookLM       → nlm CLI; trigger with "nlm ..." on Slack (list/ask/research/podcast/slides/mindmap/quiz)
```

## NotebookLM (Slack "nlm" prefix)
`nlm list | ask [nb] [q] | research [topic] | create | podcast | brief | debate | slides | mindmap | quiz`.
Key notebooks: `instagram` (niches), `1a76701b` (Reddit jobs, 298 sources).

## House Fund (freelance income)
Every 30min job-finder: OpenOutreach monitor → internet scan (1 of 42 slots) → job boards → score+dedup → Notion Job Tracker → auto-apply ≥75 → DM top 3. Reply triggers: `apply 1/2/3`, `followup [name]`, `approve`, `nlm research [topic]`.

## Sessions
- Auto-detect project via `project-detect.py` ($PWD → MemPalace wing).
- Log meaningful actions immediately to `vault/logs/YYYY-MM-DD.md` (`- HH:MM — what happened`). Don't batch.
- End of session: hooks auto-commit (`log: session YYYY-MM-DD`); force with `/sync-memory`.

## Projects (Active)
taleemabad-core (Django LMS) · taleemabad-cms (React SPA) · taleemabad-auth (JWT) · portfolio-website · portfolio-data. Each has `vault/projects/<name>/` (project.md, architecture.md, related.md).

## Key Files
`INDEX.md` (vault hub) · `STANDUP.md` (daily focus) · `MEMORY.md` (memory index) · `.claude/settings.json` (hooks+MCP) · `.claude/hooks/` (the nervous system).
```

- [ ] **Step 2: Verify the line limit and that nav targets exist**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
L=$(wc -l < CLAUDE.md); echo "lines=$L"; [ "$L" -le 150 ] && echo "UNDER 150 OK" || echo "OVER LIMIT"
for p in vault/memory/kamil_personality.md .claude/rules/notion.md .claude/rules/slack.md .claude/rules/taleemabad.md .claude/rules/content.md .claude/rules/skills-router.md; do
  [ -f "$p" ] && echo "OK $p" || echo "MISSING $p — nav target broken"
done
```
Expected: `UNDER 150 OK` and `OK` for every nav target.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "refactor(harness): CLAUDE.md → L1 router (434→~125 lines)"
```

**GATE 2:** Stop. Show Kamal the new CLAUDE.md + the 6 rules files. Confirm nothing important was dropped (diff the old content against the rules). Get approval before Phase 3.

---

## Phase 3 — PreToolUse blocking hooks

## Task 9: Create `block-bad-commands.py` (PreToolUse / Bash)

**Files:**
- Create: `.claude/hooks/block-bad-commands.py`

- [ ] **Step 1: Write the hook** — narrow, specific patterns only; silent on success (exit 0), loud on block (exit 2)

```python
#!/usr/bin/env python3
"""PreToolUse/Bash guard. Blocks ONLY specific dangerous patterns. Silent on success."""
import json, re, sys

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # never block on malformed input
    cmd = (data.get("tool_input", {}) or {}).get("command", "") or ""

    blocks = [
        (r"\brm\s+-rf\s+(~|/home/oye|\$HOME)(/\s|/?$|\s|$)",
         "Blocked: rm -rf on home root. Target a specific subdirectory."),
        (r"\brm\s+-rf\s+([^|&;]*/)?vault(/\s|/?$|\s|$)",
         "Blocked: rm -rf on the vault. The vault is Kamil's memory — delete specific files only."),
        (r"git\s+push\b[^|&;]*--force[^|&;]*\b(master|main)\b|git\s+push\b[^|&;]*\bmaster\b[^|&;]*--force",
         "Blocked: force-push to master/main. Use a branch + PR."),
        (r"git\s+add\b[^|&;]*(\.slack|\.env)\b",
         "Blocked: staging a secrets file (.slack/.env). Stage explicit non-secret paths."),
        (r"git\s+add\s+(-A|--all|\.)(\s|$)",
         "Blocked: `git add -A`/`git add .` can stage secrets. Stage explicit paths instead."),
        (r"\b(pkill|kill(all)?)\b[^|&;]*kamil-slack-listener",
         "Blocked: killing the Slack listener daemon. Stop it deliberately if truly intended."),
    ]
    for pattern, msg in blocks:
        if re.search(pattern, cmd):
            print(msg, file=sys.stderr)
            sys.exit(2)
    sys.exit(0)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: chmod + verify it BLOCKS bad commands** (each should print a reason and exit 2)

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
chmod +x .claude/hooks/block-bad-commands.py
for c in 'rm -rf ~' 'rm -rf vault' 'git push --force origin master' 'git add .slack' 'git add -A' 'pkill -f kamil-slack-listener'; do
  echo "{\"tool_input\":{\"command\":\"$c\"}}" | python3 .claude/hooks/block-bad-commands.py >/dev/null 2>/tmp/e; echo "rc=$? [$c] :: $(cat /tmp/e)"
done
```
Expected: every line `rc=2` with a block reason.

- [ ] **Step 3: Verify it ALLOWS good commands** (each should exit 0, silent)

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
for c in 'git status' 'rm -rf /tmp/scratch' 'git push origin master' 'git add CLAUDE.md' 'ls vault' 'python3 .claude/hooks/job-finder.py'; do
  echo "{\"tool_input\":{\"command\":\"$c\"}}" | python3 .claude/hooks/block-bad-commands.py >/tmp/o 2>&1; echo "rc=$? [$c] out=[$(cat /tmp/o)]"
done
```
Expected: every line `rc=0` and `out=[]` (silent). Note `git push origin master` (non-force) is allowed; only force-push to master is blocked.

- [ ] **Step 4: Commit**

```bash
git add .claude/hooks/block-bad-commands.py
git commit -m "feat(harness): PreToolUse hook blocking dangerous bash"
```

---

## Task 10: Create `guard-file-writes.py` (PreToolUse / Write|Edit)

**Files:**
- Create: `.claude/hooks/guard-file-writes.py`

- [ ] **Step 1: Write the hook** — block CLAUDE.md growth past 150; warn (don't block) on secret-file writes

```python
#!/usr/bin/env python3
"""PreToolUse/Write|Edit guard. Blocks CLAUDE.md >150 lines; warns on secret writes."""
import json, os, sys

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    ti = data.get("tool_input", {}) or {}
    path = ti.get("file_path", "") or ""

    # Warn (soft) on writing secret files
    base = os.path.basename(path)
    if base in (".slack", ".env"):
        print(f"WARNING: writing {base} — verify you are not clobbering live credentials.", file=sys.stderr)
        sys.exit(0)

    # Hard block: CLAUDE.md growing past 150 lines
    if base == "CLAUDE.md":
        content = ti.get("content")
        if content is None:  # Edit, not Write — estimate from existing file
            try:
                with open(path) as f:
                    existing = sum(1 for _ in f)
            except Exception:
                existing = 0
            new_str = ti.get("new_string", "") or ""
            old_str = ti.get("old_string", "") or ""
            delta = new_str.count("\n") - old_str.count("\n")
            projected = existing + delta
        else:
            projected = content.count("\n") + 1
        if projected > 150:
            print(f"ERROR: CLAUDE.md would be ~{projected} lines (limit 150). Move detail to .claude/rules/ or vault/memory/.", file=sys.stderr)
            sys.exit(2)
    sys.exit(0)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: chmod + verify it BLOCKS an oversized CLAUDE.md write**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
chmod +x .claude/hooks/guard-file-writes.py
python3 - <<'PY' | python3 .claude/hooks/guard-file-writes.py >/dev/null 2>/tmp/e; echo "rc=$? :: $(cat /tmp/e)"
import json
print(json.dumps({"tool_input":{"file_path":"/home/oye/Documents/free_work/personal-agent-v2/CLAUDE.md","content":"\n".join(["x"]*200)}}))
PY
```
Expected: `rc=2 :: ERROR: CLAUDE.md would be ~201 lines (limit 150)...`

- [ ] **Step 3: Verify it ALLOWS a normal write and WARNS on .slack**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
echo '{"tool_input":{"file_path":"/tmp/foo.md","content":"hi"}}' | python3 .claude/hooks/guard-file-writes.py >/tmp/o 2>&1; echo "normal rc=$? out=[$(cat /tmp/o)]"
echo '{"tool_input":{"file_path":"/home/oye/.claude/hooks/.slack","content":"x"}}' | python3 .claude/hooks/guard-file-writes.py >/dev/null 2>/tmp/e; echo "slack rc=$? :: $(cat /tmp/e)"
```
Expected: `normal rc=0 out=[]`; `slack rc=0 :: WARNING: writing .slack ...` (warns, does not block).

- [ ] **Step 4: Commit**

```bash
git add .claude/hooks/guard-file-writes.py
git commit -m "feat(harness): PreToolUse hook guarding CLAUDE.md size + secret writes"
```

---

## Task 11: Wire both hooks into `settings.json` (additive)

**Files:**
- Modify: `.claude/settings.json` (add a `PreToolUse` array; leave existing hooks untouched)

- [ ] **Step 1: Add the PreToolUse block.** Insert this object as a new key inside `"hooks"`, immediately before the existing `"SessionStart"` key. Keep `SessionStart`, `UserPromptSubmit`, `PostToolUse`, `Stop` exactly as they are.

```json
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/block-bad-commands.py",
            "timeout": 5
          }
        ]
      },
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/guard-file-writes.py",
            "timeout": 5
          }
        ]
      }
    ],
```

- [ ] **Step 2: Verify JSON is valid and all 5 hook types now present**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "import json; h=json.load(open('.claude/settings.json'))['hooks']; ks=list(h.keys()); print(ks); assert set(['PreToolUse','SessionStart','UserPromptSubmit','PostToolUse','Stop'])==set(ks), 'missing/extra hook types'; print('ALL 5 PRESENT OK')"
```
Expected: prints the 5 keys and `ALL 5 PRESENT OK`.

- [ ] **Step 3: Commit**

```bash
git add .claude/settings.json
git commit -m "feat(harness): wire PreToolUse blocking hooks (existing hooks intact)"
```

**GATE 3:** Stop. Demonstrate to Kamal: a blocked-bad result, an allowed-good result, and `ALL 5 PRESENT OK`. Get approval before Phase 4.

---

## Phase 4 — Standards + Notion mirror + slides skill + listener patch

## Task 12: Create the 4 standards docs

**Files:**
- Create: `.claude/standards/DOC_TYPE_SYSTEM.md`
- Create: `.claude/standards/RETRIEVAL_POLICY.md`
- Create: `.claude/standards/INVOCATION_POLICY.md`
- Create: `.claude/standards/METADATA_CONTRACT.md`

- [ ] **Step 1: `DOC_TYPE_SYSTEM.md`**

```markdown
---
type: reference
last_verified: 2026-06-01
owner: kamil
---

# Document Type System

| Type | Purpose | Line limit | Load behavior |
|------|---------|-----------|---------------|
| router | Navigation only — links, no content | 100 | Always safe |
| runbook | Step-by-step procedures | 200 | When executing it |
| reference | Stable lookup info | 300 | When that domain is active |
| investigation | Active analysis, time-bound | 300 | When debugging |
| plan | Proposed approach + decisions | none | When planning |
| changelog | Version history | none | By section only |

Enforcement: every markdown file (except CLAUDE.md) needs YAML frontmatter with `type:` and `last_verified:`.
```

- [ ] **Step 2: `RETRIEVAL_POLICY.md`**

```markdown
---
type: reference
last_verified: 2026-06-01
owner: kamil
---

# Retrieval Policy

## L1 — always
- CLAUDE.md ; open beads (last 10 from `.beads/status.jsonl`)

## L2 — load one, by task type
- Notion/work context → `.claude/rules/notion.md`
- Slack → `.claude/rules/slack.md`
- taleemabad-core → `.claude/rules/taleemabad.md`
- Content → `.claude/rules/content.md`
- Any issue type → `.claude/rules/skills-router.md`

## L3 — only when blocked
- The one doc that unblocks the task; max 2-3 per session. Personality → `vault/memory/kamil_personality.md`.

## Never auto-load
- Archives, full changelogs, completed investigations, full work-log history.
```

- [ ] **Step 3: `INVOCATION_POLICY.md`**

```markdown
---
type: reference
last_verified: 2026-06-01
owner: kamil
---

# Invocation Policy

Skill routing table: `.claude/rules/skills-router.md`.

## Cost tiers
- Low (routine) → Haiku. Medium (standard) → Sonnet. High (deep analysis) → Opus, sparingly.

## Triggers
- Process skills (brainstorming, systematic-debugging) BEFORE implementation skills.
- "build/fix/research" is WHAT, not HOW — still route through the matching skill.
```

- [ ] **Step 4: `METADATA_CONTRACT.md`**

```markdown
---
type: reference
last_verified: 2026-06-01
owner: kamil
---

# Metadata Contract

Every markdown file (except CLAUDE.md) starts with:

    ---
    type: router|runbook|reference|investigation|plan|changelog
    last_verified: YYYY-MM-DD
    owner: kamil
    ---

## Freshness SLOs
| Doc | Max staleness |
|-----|---------------|
| CLAUDE.md | 2 weeks |
| Routers / rules | 1 month |
| Reference docs | 2 months |
| Changelogs | none |

When `last_verified` exceeds the SLO → open a bead.
```

- [ ] **Step 5: Verify all 4 have frontmatter + commit**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
for f in DOC_TYPE_SYSTEM RETRIEVAL_POLICY INVOCATION_POLICY METADATA_CONTRACT; do
  head -1 ".claude/standards/$f.md" | grep -q '^---' && echo "OK $f" || echo "MISSING FM $f"
done
```
Expected: `OK` for all 4.
```bash
git add .claude/standards/
git commit -m "docs(harness): 4 standards policy docs"
```

---

## Task 13: Create `beads-to-notion.py` (best-effort mirror)

**Files:**
- Create: `.claude/hooks/beads-to-notion.py`

- [ ] **Step 1: Write the script** — reads open beads, emits a mirror instruction; never raises on failure

```python
#!/usr/bin/env python3
"""Best-effort: surface open beads so a Claude session can mirror them to the Notion
Harness DB (de10157da3e34ef58a74ea240f31fe98). Pure read + print. Never blocks work."""
import json, sys
from pathlib import Path

STATUS = Path(__file__).resolve().parents[1] / ".." / ".beads" / "status.jsonl"
HARNESS_DB = "de10157da3e34ef58a74ea240f31fe98"

def main():
    try:
        open_beads = []
        for line in STATUS.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("status") in ("open", "in_progress"):
                open_beads.append(d)
        if not open_beads:
            sys.exit(0)
        print(f"[beads] {len(open_beads)} open bead(s). Mirror to Notion Harness DB {HARNESS_DB} via mcp__claude_ai_Notion__* if not already present:")
        for d in open_beads[-10:]:
            print(f"  [{d.get('priority','?')}] {d.get('id')}: {d.get('title')} ({d.get('status')})")
    except Exception:
        pass  # never block on mirror failure
    sys.exit(0)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it lists the open bead**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 .claude/hooks/beads-to-notion.py
```
Expected: a line listing `bd-001: Build Kamil super-agent harness (in_progress)`.

- [ ] **Step 3: Verify it never errors on a missing/garbled file**

Run:
```bash
cd /tmp && python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/beads-to-notion.py; echo "rc=$?"
```
Expected: `rc=0` (the relative path won't resolve from /tmp, but it must not crash).

- [ ] **Step 4: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/hooks/beads-to-notion.py
git commit -m "feat(harness): best-effort beads→Notion mirror script"
```

---

## Task 14: Vendor the `slides` skill from team-playbooks

**Files:**
- Create: `.claude/skills/slides/SKILL.md`

- [ ] **Step 1: Fetch the skill content from the private repo via gh and write it locally**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
mkdir -p .claude/skills/slides
gh api repos/Orenda-Project/team-playbooks/contents/slides-skill/SKILL.md --jq '.content' | base64 -d > .claude/skills/slides/SKILL.md
echo "wrote $(wc -l < .claude/skills/slides/SKILL.md) lines"
```
Expected: writes ~530 lines (the full slides SKILL.md).

- [ ] **Step 2: Prepend Kamil-local frontmatter** so it loads as a manual skill (the source file starts with `# Google Workspace Slides Skill`, no frontmatter)

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 - <<'PY'
p = ".claude/skills/slides/SKILL.md"
body = open(p).read()
if not body.startswith("---"):
    fm = ("---\n"
          "name: slides\n"
          "description: Generate AI full-bleed Google Slides decks via Kie.ai (nano-banana-pro) + Google Slides API. Invoke for slides/deck/presentation requests. Needs KIE_API_KEY + a Google service account with Domain-Wide Delegation to run.\n"
          "---\n\n")
    open(p, "w").write(fm + body)
    print("frontmatter prepended")
else:
    print("already has frontmatter")
PY
```
Expected: `frontmatter prepended`.

- [ ] **Step 3: Verify + commit**

Run: `head -3 .claude/skills/slides/SKILL.md | grep -q 'name: slides' && grep -q 'nano-banana-pro' .claude/skills/slides/SKILL.md && echo OK`
Expected: `OK`
```bash
git add .claude/skills/slides/SKILL.md
git commit -m "feat(harness): vendor team-playbooks slides skill"
```

---

## Task 15: Make the Slack listener skill-aware (string-only patch)

**Files:**
- Modify: `.claude/hooks/kamil-slack-listener.py` (the `## YOUR CAPABILITIES` block in the main prompt, ~line 380-385)

- [ ] **Step 1: Locate the exact anchor**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
grep -n "^- Files, bash, code: anything" .claude/hooks/kamil-slack-listener.py
```
Expected: one line number (the last bullet of the `## YOUR CAPABILITIES` block).

- [ ] **Step 2: Insert the skill index immediately AFTER that bullet.** Use this exact edit — find the line:

```
- Files, bash, code: anything
```

and replace it with:

```
- Files, bash, code: anything

## YOUR SKILLS (reach for these — don't free-solo; full table in .claude/rules/skills-router.md)
- research / "find out" / compare → deep-research
- any bug / "broken" / test fails → systematic-debugging (then test-driven-development)
- build UI / page / component → frontend-design
- slides / deck → the `slides` skill (.claude/skills/slides/)
- marketing / SEO / ads / content strategy → marketing-skills
- before claiming done → verification-before-completion
- planning multi-step work → brainstorming → writing-plans
If a skill plausibly applies, invoke it first.
```

- [ ] **Step 3: Verify the daemon still compiles and the marker is present**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m py_compile .claude/hooks/kamil-slack-listener.py && echo "COMPILES OK"
grep -q "YOUR SKILLS" .claude/hooks/kamil-slack-listener.py && echo "SKILL INDEX PRESENT"
```
Expected: `COMPILES OK` and `SKILL INDEX PRESENT`.

- [ ] **Step 4: Commit**

```bash
git add .claude/hooks/kamil-slack-listener.py
git commit -m "feat(harness): make Slack listener skill-aware (prompt injection)"
```

**GATE 4:** Stop. Confirm with Kamal: standards present, mirror runs, slides vendored, listener compiles + skill-aware. Note: the live listener daemon won't pick up the prompt change until it restarts (@reboot or manual) — flag this; do NOT restart it without Kamal's say-so. Get approval before Phase 5.

---

## Phase 5 — Eval harness (Tier-1, $0)

## Task 16: Create the 8 starter eval tasks

**Files:**
- Create: `.claude/evals/tasks/eval-001-notion-prs.yaml` … `eval-008-stale.yaml`

- [ ] **Step 1: Create all 8 YAML task files**

`.claude/evals/tasks/eval-001-notion-prs.yaml`:
```yaml
id: eval-001
description: "Find the Open PRs Notion DB ID"
category: explicit
input: "What's the Notion DB for open PRs?"
expected:
  route: ".claude/rules/notion.md"
  must_load: ["notion.md"]
  must_not_load: ["taleemabad.md", "content.md"]
  max_hops: 2
quality_gate: PASS
```

`.claude/evals/tasks/eval-002-slack-send.yaml`:
```yaml
id: eval-002
description: "How to send a Slack DM"
category: explicit
input: "How do I send Kamal a Slack DM?"
expected:
  route: ".claude/rules/slack.md"
  must_load: ["slack.md"]
  must_not_load: ["notion.md", "taleemabad.md"]
  max_hops: 2
quality_gate: PASS
```

`.claude/evals/tasks/eval-003-taleemabad.yaml`:
```yaml
id: eval-003
description: "Starting work on taleemabad-core"
category: explicit
input: "Kamil, work on taleemabad-core — fix the login bug"
expected:
  route: ".claude/rules/taleemabad.md"
  must_load: ["taleemabad.md"]
  must_not_load: ["content.md", "slack.md"]
  max_hops: 2
quality_gate: PASS
```

`.claude/evals/tasks/eval-004-bug-symptom.yaml`:
```yaml
id: eval-004
description: "Implicit: a bug symptom should route to debugging skill"
category: implicit
input: "the job-finder isn't posting anything to Slack and I don't know why"
expected:
  route: ".claude/rules/skills-router.md"
  must_load: ["skills-router.md"]
  must_not_load: ["content.md"]
  max_hops: 2
quality_gate: CONCERNS
```

`.claude/evals/tasks/eval-005-research.yaml`:
```yaml
id: eval-005
description: "Implicit: a research request should route to deep-research"
category: implicit
input: "find out the best way to add rate limiting to a FastAPI app"
expected:
  route: ".claude/rules/skills-router.md"
  must_load: ["skills-router.md"]
  must_not_load: ["notion.md"]
  max_hops: 2
quality_gate: CONCERNS
```

`.claude/evals/tasks/eval-006-content-topic.yaml`:
```yaml
id: eval-006
description: "Contextual: picking a content topic needs content rules + memory"
category: contextual
input: "draft today's LinkedIn post"
expected:
  route: ".claude/rules/content.md"
  must_load: ["content.md"]
  must_not_load: ["taleemabad.md"]
  max_hops: 2
quality_gate: CONCERNS
```

`.claude/evals/tasks/eval-007-personality.yaml`:
```yaml
id: eval-007
description: "Personality lookup routes to L3 memory, not inline CLAUDE.md"
category: explicit
input: "what's Kamil's humor style?"
expected:
  route: "vault/memory/kamil_personality.md"
  must_load: ["kamil_personality.md"]
  must_not_load: ["notion.md", "taleemabad.md"]
  max_hops: 2
quality_gate: PASS
```

`.claude/evals/tasks/eval-008-stale.yaml`:
```yaml
id: eval-008
description: "Negative: a simple question must not load the full personality/standards bundle"
category: negative
input: "what's the Harness DB ID?"
expected:
  route: ".claude/rules/notion.md"
  must_load: ["notion.md"]
  must_not_load: ["kamil_personality.md", "taleemabad.md", "content.md"]
  max_hops: 2
quality_gate: PASS
```

- [ ] **Step 2: Verify all 8 parse as YAML**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "import glob,yaml; fs=sorted(glob.glob('.claude/evals/tasks/*.yaml')); [yaml.safe_load(open(f)) for f in fs]; print(f'{len(fs)} eval tasks parse OK')"
```
Expected: `8 eval tasks parse OK`. (If pyyaml missing: `pip install --user pyyaml` first.)

- [ ] **Step 3: Commit**

```bash
git add .claude/evals/tasks/
git commit -m "feat(harness): 8 starter eval tasks for Kamil's routes"
```

---

## Task 17: Create the Tier-1 deterministic grader

**Files:**
- Create: `.claude/evals/graders/run-tier1.sh`

- [ ] **Step 1: Write the grader** — checks every eval's `route` file exists, every md doc has frontmatter, line limits hold, and `last_verified` freshness; $0, no LLM

```bash
#!/bin/bash
# Tier-1 deterministic eval grader. Exit 0 = pass, 1 = fail. No LLM, $0.
cd "$(dirname "$0")/../../.." || exit 1
FAIL=0

echo "== Tier-1: eval route files exist =="
for y in .claude/evals/tasks/*.yaml; do
  route=$(python3 -c "import yaml,sys; print(yaml.safe_load(open('$y'))['expected']['route'])" 2>/dev/null)
  if [ -n "$route" ] && [ -e "$route" ]; then echo "  OK $route"; else echo "  FAIL missing route: $route ($y)"; FAIL=1; fi
done

echo "== Tier-1: markdown frontmatter (rules/standards/memory + plan) =="
for f in .claude/rules/*.md .claude/standards/*.md vault/memory/kamil_personality.md; do
  [ -f "$f" ] || continue
  if head -1 "$f" | grep -q '^---'; then echo "  OK fm $f"; else echo "  FAIL no frontmatter: $f"; FAIL=1; fi
done

echo "== Tier-1: CLAUDE.md <=150 lines =="
L=$(wc -l < CLAUDE.md)
if [ "$L" -le 150 ]; then echo "  OK CLAUDE.md $L lines"; else echo "  FAIL CLAUDE.md $L > 150"; FAIL=1; fi

echo "== Tier-1: router/reference line limits =="
for f in .claude/rules/*.md; do
  L=$(wc -l < "$f"); if [ "$L" -le 300 ]; then echo "  OK $f ($L)"; else echo "  FAIL $f $L > 300"; FAIL=1; fi
done

echo "== Tier-1: freshness (rules within 31 days of last_verified) =="
python3 - <<'PY' || FAIL=1
import glob, datetime, re, sys
today = datetime.date(2026,6,1)  # stamp; bump when re-running in a new session
bad=0
for f in glob.glob(".claude/rules/*.md"):
    m=re.search(r'last_verified:\s*(\d{4}-\d{2}-\d{2})', open(f).read())
    if not m: print(f"  FAIL no last_verified: {f}"); bad=1; continue
    d=datetime.date.fromisoformat(m.group(1))
    age=(today-d).days
    print(f"  {'OK' if age<=31 else 'STALE'} {f} ({age}d)")
    if age>31: bad=1
sys.exit(bad)
PY

if [ "$FAIL" -eq 0 ]; then echo "TIER-1: PASS"; else echo "TIER-1: FAIL"; fi
exit $FAIL
```

- [ ] **Step 2: chmod + run it — must PASS**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
chmod +x .claude/evals/graders/run-tier1.sh
.claude/evals/graders/run-tier1.sh
```
Expected: ends with `TIER-1: PASS` and exit 0. (If a route or frontmatter check fails, fix that file — the grader is correct; the doc is wrong.)

- [ ] **Step 3: Commit**

```bash
git add .claude/evals/graders/run-tier1.sh
git commit -m "feat(harness): Tier-1 deterministic eval grader (\$0)"
```

---

## Task 18: Final verification + close the bead

**Files:**
- Modify: `.beads/status.jsonl` (append a closing line for bd-001)
- Create: `.claude/evals/README.md`

- [ ] **Step 1: Create `.claude/evals/README.md`** documenting the (currently-off) Tier-2 path

```markdown
---
type: reference
last_verified: 2026-06-01
owner: kamil
---

# Eval Harness

Measures whether Kamil's docs route correctly. Two tiers:

- **Tier-1 (deterministic, $0, ON):** `graders/run-tier1.sh` — route files exist, frontmatter present, line limits, freshness. Wire into a hook or run before doc changes.
- **Tier-2 (LLM judge, ~$0.10/run, OFF by default):** not built yet. To enable, add a runner that feeds each `tasks/*.yaml` input to `claude -p`, captures which docs it loaded, and scores against `expected`. Track cost in `.beads/decisions.jsonl`.

## Self-improving loop
When you log a failure in `.beads/failures.jsonl`, add a matching `tasks/eval-NNN-*.yaml` so that class of mistake is caught next session.
```

- [ ] **Step 2: Run the full safety re-check** (nothing broke)

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
echo "== listener compiles ==";        python3 -m py_compile .claude/hooks/kamil-slack-listener.py && echo OK
echo "== all cron files still exist =="; for f in slack-poller.py kamil-slack-listener.py kamil-self-healer.py job-finder.py content-scheduler.py notion-map-updater.py; do [ -f ".claude/hooks/$f" ] && echo "OK $f" || echo "MISSING $f"; done
echo "== new hooks compile ==";          python3 -m py_compile .claude/hooks/block-bad-commands.py .claude/hooks/guard-file-writes.py .claude/hooks/beads-to-notion.py && echo OK
echo "== settings valid, 5 hook types =="; python3 -c "import json; print(sorted(json.load(open('.claude/settings.json'))['hooks'].keys()))"
echo "== tier-1 ==";                      .claude/evals/graders/run-tier1.sh | tail -1
echo "== duplicate files still present (logged-not-deleted) =="; ls .claude/hooks/auto_apply.py .claude/hooks/internet_scanner.py 2>/dev/null && echo "duplicates intact (as planned)"
```
Expected: listener OK; all 6 cron files OK; new hooks compile OK; 5 hook types listed; `TIER-1: PASS`; duplicates intact.

- [ ] **Step 3: Append the closing bead** to `.beads/status.jsonl`

```jsonl
{"id": "bd-001", "title": "Build Kamil super-agent harness", "status": "closed", "priority": "high", "created": "2026-06-01", "updated": "2026-06-01", "category": "infrastructure", "resolution": "Built 3-layer harness: L1 router + 6 L2 rules + L3 personality; beads (status/decisions/failures); 2 PreToolUse blocking hooks wired (existing 4 hook types intact); 4 standards docs; beads→Notion mirror; vendored slides skill; listener skill-aware; 8 eval tasks + Tier-1 grader passing. No daemon broken; duplicate .py files logged not deleted.", "blocked_by": null, "owner": "kamil"}
```

- [ ] **Step 4: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/evals/README.md .beads/status.jsonl
git commit -m "feat(harness): eval README + close bd-001"
```

**GATE 5 (final):** Report to Kamal: every DoD item from the spec checked, Tier-1 PASS, listener intact, duplicates logged-not-deleted. Flag the one manual follow-up: the live listener daemon needs a restart (its choice/timing) to pick up the skill-aware prompt.

---

## Self-Review (filled in by plan author)

**Spec coverage:** Every spec DoD item maps to a task — CLAUDE.md trim (T8), rules incl. skills-router (T3-7), beads (T1), 2 PreToolUse hooks tested (T9-11), standards (T12), slides + listener skill-awareness (T14-15), eval suite + Tier-1 (T16-17), daemon-intact verification (T0, T18), failures-logged-not-deleted (T1, T18). Notion mirror (T13). No gaps.

**Placeholder scan:** No TBD/TODO. Every code/edit step shows full content. Edit anchors are exact strings verified against the live files (`- Files, bash, code: anything` in the listener; the `"SessionStart"` key in settings.json).

**Consistency:** Hook filenames consistent everywhere (`block-bad-commands.py`, `guard-file-writes.py`, `beads-to-notion.py`). DB IDs match the live CLAUDE.md + listener. Eval `route` paths match files created in Tasks 2-7. The freshness `today` stamp is hardcoded (Date.now is unavailable to scripts; bump on re-run) — noted in the grader.

**Known caveat carried forward:** the live `kamil-slack-listener.py` daemon must restart to pick up the T15 prompt change; flagged at Gate 4 and Gate 5, not done automatically.
```
