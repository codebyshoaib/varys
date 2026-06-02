# Kamil Orchestrator Workflow — taleemabad-core Feature Delivery

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish Kamil as the PM/reviewer orchestrator for taleemabad-core features — running `/feature` to plan, assigning `/develop` to Claude subagents, monitoring via Notion, and capturing knowledge to `.claude/reflections/` so every session starts smarter.

**Architecture:** Kamil never free-codes. Every feature goes through the 5-phase harness (`/feature` → `/develop` → `/test` → `/fix` loop → `/reflect`). Kamil's job is to (1) kick off the harness, (2) approve plans, (3) review agent output at each gate, (4) log to Notion, and (5) run `/reflect` to bake lessons into the repo. Claude subagents do the coding.

**Tech Stack:** taleemabad-core harness commands, Notion MCP (Harness DB), Claude subagents, `.claude/features/`, `.claude/reflections/`

---

## Phase 0 — Apply this workflow to the current in-flight task first

The BH ELT Grand Quiz FE feature (`MC20-bh-elt-grand-quiz-fe`) has a hand-written plan but **never went through `/feature`**. Before starting anything new, register it properly.

### Task 0: Register the in-flight feature in the harness

**Files:**
- Create: `/home/oye/Documents/taleemabad-core/.claude/features/2026-06-02-bh-elt-grand-quiz-fe/` (all 6 scaffold files)
- Notion: Harness DB entry

- [ ] **Step 1: Open a taleemabad-core Claude session and run `/feature`**

```
cd /home/oye/Documents/taleemabad-core
# open Claude Code session here, then:
/feature bh-elt-grand-quiz-fe
```

The `/feature` command will:
- Create `.claude/features/2026-06-02-bh-elt-grand-quiz-fe/` with all 6 stub files
- Launch `@explorer-fe` + `@frontend-specialist` triage agents (FE-only scope)
- Produce `research.md` + `plan.md`
- Await Kamil's approval

- [ ] **Step 2: Provide context to the triage agents**

When `/feature` asks for context, paste:

```
Backend PR #5139 already merged. FE-only work.
Feature folder already has docs at .claude/features/2026-05-20-beaconhouse-elt-grand-quiz-capstone/
fe-integration-guide.md has the exact 5 changes needed.
Branch: create MC20-bh-elt-grand-quiz-fe from develop.
Do not change vendor configs. Guard all scoring changes with isGrandQuiz && allOpenEnded.
```

- [ ] **Step 3: Kamil reviews the plan.md produced by `/feature`**

Check against the design we already approved:
- ✅ `feedback` field added to `ISubmission` + `setSubmission()`
- ✅ Dexie schema bumped to v13
- ✅ `onAnswerCheck` callback extended with `feedback` param in Quiz DSM
- ✅ `totalMarks` guarded: `isGrandQuiz && allOpenEnded` → `questions.length * 5`
- ✅ `passingPercentage` guarded: `isGrandQuiz && allOpenEnded` → `70`
- ✅ Level filter `[3,4]` replaced with content-type detection
- ✅ E2E test step included

If plan matches → approve by running `/develop bh-elt-grand-quiz-fe`

- [ ] **Step 4: Log to Notion Harness DB**

Use Notion MCP. Create a record in the Harness DB with:
```
Name: MC20-bh-elt-grand-quiz-fe
Status: In Progress
Phase: 2 — develop
Feature folder: .claude/features/2026-06-02-bh-elt-grand-quiz-fe/
Branch: MC20-bh-elt-grand-quiz-fe
Backend PR: #5139 (merged)
FE PR: pending
Notes: FE-only. 5 targeted changes. Vendor-isolated scoring fix.
```

---

## Phase 1 — The Standard Orchestrator Loop (apply to every future feature)

This is Kamil's repeatable workflow for every taleemabad-core task going forward.

### Task 1: Kick off with `/feature` — never free-code

- [ ] **Step 1: Open taleemabad-core session and run `/feature <slug>`**

```bash
# In /home/oye/Documents/taleemabad-core Claude session:
/feature <slug>
```

Slug naming convention: `<ticket-id>-<short-description>` e.g. `MC21-teacher-profile-edit`

- [ ] **Step 2: Watch triage agents complete research.md**

Agents will append findings with `[Agent Name]` prefix. Read the output. If agents hit a blocker tagged `🔴 BLOCKER`, resolve it before proceeding — read the relevant code, answer the question, paste the answer back.

- [ ] **Step 3: Review plan.md before approving**

Use the approval checklist from `.claude/commands/feature.md`:
- ✅ Steps in right order?
- ✅ Risks identified + mitigated?
- ✅ No unresolved `?` questions in success criteria?
- ✅ E2E test step included for any user-facing change?
- ✅ UI feature? Design.md approved?

If plan is good → type `/develop <slug>` to hand off to coding agents.
If plan has gaps → read the code to answer open questions, update plan.md, then approve.

- [ ] **Step 4: Create Notion Harness entry immediately on approval**

Use Notion MCP. Template:
```
Name: <ticket-id>-<slug>
Status: In Progress
Phase: 2 — develop
Feature folder: .claude/features/YYYY-MM-DD-<slug>/
Branch: <branch-name>
Approved: 2026-06-02
Notes: <one-line summary of what this does>
```

---

### Task 2: Monitor `/develop` — review, don't rewrite

- [ ] **Step 1: Run `/develop <slug>` to dispatch coding agents**

```bash
/develop <slug>
```

Agents append to `develop.md` with timestamps. You watch, not code.

- [ ] **Step 2: Watch for 🔴 BLOCKER tags in develop.md**

If a blocker appears:
- Read the blocker description
- Read the relevant code (use Explore subagent if needed)
- Paste the answer into the session so the blocked agent can continue
- Do NOT start writing code yourself

- [ ] **Step 3: When agents finish, review the develop.md summary**

Check:
- All plan steps completed?
- Linter PASS?
- Type check PASS?
- Build PASS?
- Any 🟡 warnings that need decisions?

If all green → proceed to `/test`.

- [ ] **Step 4: Update Notion Harness entry**

```
Phase: 3 — test
Notes: append "develop complete YYYY-MM-DD — linter ✅ build ✅"
```

---

### Task 3: Gate on `/test` — do not skip

- [ ] **Step 1: Run `/test <slug>`**

```bash
/test <slug>
```

This runs:
- Phase 0 verifier (for bug fixes — reproduces bug before/after diff)
- Automated: linter ≥95%, build pass, tests ≥85% coverage
- Manual E2E: golden path + edge cases
- Confidence score — must reach ≥86%

- [ ] **Step 2: If confidence < 86%, run `/fix <slug>` and loop**

```bash
/fix <slug>
```

Then re-run `/test`. Max 3 loops. After 3, escalate with a Notion comment tagging the issue.

- [ ] **Step 3: When confidence ≥ 86%, create the PR**

```bash
cd /home/oye/Documents/taleemabad-core
gh pr create \
  --base develop \
  --title "<ticket-id>: <description>" \
  --body "$(cat .claude/features/YYYY-MM-DD-<slug>/plan.md | head -30)"
```

- [ ] **Step 4: Update Notion Harness entry**

```
Status: PR Open
Phase: 4 — review
PR URL: <url>
Confidence: <score>%
```

---

### Task 4: Run `/reflect` after PR — always

- [ ] **Step 1: After PR is merged (or immediately after PR created), run `/reflect`**

```bash
/reflect
```

This writes:
- `.claude/reflections/<slug>.md` — structured post-mortem
- `.claude/reflections/INDEX.md` — one-liner for future lookup
- Promotes hard lessons to `.claude/rules/` so all future agents load them

- [ ] **Step 2: Update Notion Harness entry to Done**

```
Status: Done
Phase: 6 — reflected
Reflected: YYYY-MM-DD
Notes: append link to .claude/reflections/<slug>.md
```

- [ ] **Step 3: Commit the reflection files**

```bash
cd /home/oye/Documents/taleemabad-core
git add .claude/reflections/
git commit -m "reflect: <slug> post-mortem"
git push
```

---

## Phase 2 — Knowledge persistence (how future sessions stay smart)

### Task 5: After every feature, check if MEMORY.md needs updating

After `/reflect` runs, scan `.claude/reflections/<slug>.md` for anything that would be useful in the personal-agent-v2 memory system (not just taleemabad-core).

- [ ] **Step 1: Read the reflection**

```bash
cat /home/oye/Documents/taleemabad-core/.claude/reflections/<slug>.md
```

- [ ] **Step 2: For each surprise or non-obvious lesson, save to personal memory**

If the lesson is taleemabad-specific (e.g. "Dexie schema bumps need a version increment"), write to:
```
/home/oye/.claude/projects/-home-oye-Documents-free-work-personal-agent-v2/memory/project_taleemabad_<topic>.md
```

If the lesson is general (e.g. "always check vendor isolation before touching scoring logic"), write to:
```
/home/oye/.claude/projects/-home-oye-Documents-free-work-personal-agent-v2/memory/feedback_<topic>.md
```

Then add a line to `MEMORY.md` index.

---

## Kamil's Cheat Sheet (print this)

```
Every taleemabad-core task:

1. /feature <slug>          ← triage + plan (Kamil approves)
2. Create Notion entry      ← immediately on approval
3. /develop <slug>          ← agents code (Kamil monitors)
4. /test <slug>             ← gate at ≥86% confidence
5. /fix <slug>              ← loop until green (max 3x)
6. gh pr create             ← after confidence green
7. Update Notion → PR Open
8. /reflect                 ← after PR merged
9. Update Notion → Done
10. Save lessons to MEMORY  ← if non-obvious
```

---

## Self-review

**Spec coverage:**
- ✅ Register in-flight BH ELT FE task via `/feature` (Task 0)
- ✅ Standard `/feature` → approve → Notion (Task 1)
- ✅ Monitor `/develop` without free-coding (Task 2)
- ✅ `/test` gate + `/fix` loop (Task 3)
- ✅ `/reflect` always (Task 4)
- ✅ Personal memory update from reflections (Task 5)
- ✅ Cheat sheet for quick reference

**Placeholder scan:** No TBDs. All Notion fields specified. All commands exact.

**Type consistency:** N/A — orchestration plan, no code types.
