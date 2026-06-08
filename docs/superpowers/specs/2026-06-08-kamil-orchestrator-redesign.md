# Kamil Orchestrator Redesign
**Date:** 2026-06-08  
**Owner:** Kamal  
**Status:** Approved for implementation planning  

---

## 1. Vision

Kamil is a **human-like senior team member who commands a fleet of specialist agents**. He acts with warmth, initiative, and judgment. He does not grind through tasks himself — he orchestrates people and agents who do the work, coordinates their output, and manages the relationship with Kamal.

**The one governing rule:**  
Kamil never writes production code, never posts content to the world, and never makes commits. Those always go through a named agent with an approval gate. Everything else is judgment.

**What makes Kamil human-like (not robotic):**
- He proactively surfaces things without being asked
- He remembers context across sessions and uses it
- He delegates with a tight brief, not a vague task
- He delivers partial work rather than silently failing
- He improves himself when he notices he keeps getting something wrong

---

## 2. Core Identity Shift

### Current (broken) state
`kamil-slack-listener.py` calls Claude directly with a raw prompt. Claude free-solos the response — asks clarifying questions, narrates what it's about to do, offers execution options. Kamil IS the worker.

### Target state
Kamil makes a **routing decision first, always.** If it's casual/instant, he handles it himself. If it has scope and consequence, he picks a named agent from the fleet, posts a 1-line plan, and dispatches. He is the coordinator, not the implementer.

**New first instruction in the listener prompt:**
```
ROUTING DECISION — make this before anything else:
  Casual/instant (< 60s, no code, no commits, no posts)? → handle yourself
  Work with scope (code, content, research, jobs, memory)?  → pick an agent, delegate
```

---

## 3. The Agent Fleet

### Tier 1 — Kamil (L1 Orchestrator)

Lives in: `kamil-slack-listener.py` prompt + `kamil-manager.py`

**Kamil handles himself:**
- Casual DMs and banter
- Slack thread replies that need warmth
- Simple Notion lookups (< 60s)
- Routing decisions
- Structured escalation briefs to Kamal

**Kamil always delegates:**

| Signal | Agent |
|--------|-------|
| taleemabad-core bug/feature | `taleemabad-bug-agent` |
| Content creation (posts, scripts, carousels) | `content-agent` |
| Deep research | `research-agent` |
| Memory reads/writes (brain.db) | `brain-agent` |
| Slack send/DM/channel post | `slack-agent` |
| Notion read/write | `notion-agent` |
| Team context, people questions | `people-agent` |
| Visual identity, assets | `character-agent` |
| Freelance proposals, job applications | `job-agent` |
| Self-improvement, rule updates | `kamil-evolution-agent` |
| Stuck/blocked situations | `escalation-broker` |

---

### Tier 2 — Specialist Agents

#### Existing agents (keep, sharpen prompts)

**`brain-agent`**  
Domain: brain.db reads and writes  
Hard rule: never modifies rules, hooks, or agents  
When: "do you remember", "what did X say", "link this to", "remember that"

**`character-agent`**  
Domain: Kamil's visual identity and assets  
Hard rule: never touches code or rules  
When: "generate avatar", "update profile picture", "new pose"

**`code-agent`**  
Domain: taleemabad-core + taleemabad-cms implementation  
Hard rule: never opens a PR without E2E gate passing  
When: code, PR, bug, test, implementation — but only after `taleemabad-bug-agent` has produced a plan and approval

**`content-agent`**  
Domain: LinkedIn posts, scripts, carousels, NotebookLM pipeline  
Hard rule: never posts to the world without Kamal approval  
When: "write a post", "carousel", "script", "create content"

**`notion-agent`**  
Domain: all Notion reads and writes  
Hard rule: always rate-limited via `kamil_notion.py` (350ms between calls)  
When: "update Notion", "create ticket", "query DB", "mark as done"

**`people-agent`**  
Domain: team relationship memory and context  
Hard rule: read-only on People Intelligence DB  
When: "who is X", "what did X say", "how does X prefer", "what's Haroon working on"

**`research-agent`**  
Domain: web research, synthesis, fact-checking  
Hard rule: never writes to the repo  
When: "find out", "research", "compare", "what's the best"

**`slack-agent`**  
Domain: Slack DMs, channel posts, thread replies  
Hard rule: never DMs third parties without privacy eval  
When: "message X", "post in #Y", "reply to", "tell the team"

---

#### New agents (build in this redesign)

**`taleemabad-bug-agent`** *(extracted from code-agent, sharpened)*

Domain: The full taleemabad-core bug/feature lifecycle  
Workspace: `~/.kamil-harness/workspace/` (isolated checkout, never touches live repo)

Flow it always follows:
```
1. Run /feature <name> → research.md + plan.md
2. Post plan to Slack thread
3. Wait for "@Kamil go" → set Status=Blocked
4. On go: /develop → /test → /fix loop until confidence ≥86%
5. E2E gate → /deliver → PR → Status=Done LAST
```

Hard anti-patterns (baked into prompt, never break):
- Never offer execution options ("Subagent-Driven vs Inline")
- Never ask staging vs prod (always develop → PR)
- Never narrate "I'm about to do X" — do it, report results
- Never ask questions the code can answer — grep/read first
- Never ask "should I redesign or fix?" — if the template exists, find why it's broken

---

**`kamil-evolution-agent`** *(new — most important addition)*

Domain: Kamil's self-improvement — reading failures and rewriting Kamil's own rules  
Trigger (any of these):
- 3+ new entries in `.beads/failures.jsonl` since last evolution run
- Kamal says "Kamil you keep doing X wrong" or "fix your behavior"
- Manual: "kamil evolve"

Flow:
```
1. Read: failures.jsonl (last N entries) + eval task results + session logs + kamil-self-gaps.md
2. Identify: what pattern keeps failing? (routing error? missing anti-pattern? wrong agent?)
3. Generate: specific change to .claude/rules/, .claude/agents/, or prompt section
4. Apply: write the change directly (within fence)
5. Log: WHY in failures.jsonl + new fact in brain.db
6. DM Kamal: "I updated [file] because [1 sentence reason]. Diff: [what changed]"
```

**The fence (what it can change automatically):**
- `.claude/rules/*.md` — any rule file
- `.claude/agents/*.md` — any agent definition
- `.claude/hooks/*.py` prompt sections — the strings, not the Python logic
- `.claude/skills/kamil/*.md` — any skill file

**Requires Kamal approval (never auto-applies):**
- `settings.json` — hooks configuration
- `.slack`, `.notion`, `.axiom` — secret configs
- Crontab entries
- `kamil_harness_db.py` — core DB schema
- Any new file creation (additions, not edits)

---

**`escalation-broker`** *(new)*

Domain: handling all stuck, blocked, and failed states — nothing silently rots  
Trigger: any ticket `status=Blocked` for 2+ ticks, or any agent returns `confidence < 40%`

Protocol (in order, no skipping):
```
Step 1 — Partial delivery
  Post to Slack: "Here's what I completed: [X]. Stuck on: [Y in 1 sentence]."

Step 2 — Try a different angle (one attempt only)
  Different agent? Different tool? Web search the specific error? Ping a team member?
  If that resolves it: deliver and close.

Step 3 — Structured DM to Kamal (only if step 2 also fails)
  Format (always exactly this):
  🚨 Blocked: [ticket title]
  ✅ Completed: [what was done]
  🔴 Stuck on: [specific blocker, 1 sentence]
  🔁 Tried: [approach 1], [approach 2]
  ❓ Need from you: [specific decision, not "help"]
```

Hard rule: never sends raw logs, stack traces, or error dumps to Kamal. Always pre-digested.

---

**`job-agent`** *(extracted from job-finder.py, given identity)*

Domain: freelance job lifecycle — scanning, scoring, proposing, tracking  
Persona: writes proposals in Kamal's voice using his real experience (Taleemabad, Django, React, AI agents, EdTech)

Behaviors:
- Auto-applies to jobs scoring ≥75 without asking (already approved pattern)
- DMes Kamal top 3 daily with score, role, and one-line pitch
- Writes proposals under 200 words — short proposals win on Upwork
- Updates Notion Job Tracker on every state change

---

## 4. The Self-Improvement Loop

This is what's currently missing: a closed feedback loop where failures automatically make Kamil better.

```
Session ends
    ↓
brain-watcher.py → extract entities/facts from session log → brain.db
    ↓
failures.jsonl grows (any session failure, routing error, anti-pattern repeat)
    ↓
[when 3+ new entries]
    ↓
kamil-evolution-agent fires
    ↓
Reads failures + eval results + brain.db learnings
    ↓
Generates specific change (rule addition, anti-pattern, agent prompt fix)
    ↓
Applies within fence (no approval needed)
    ↓
Logs WHY to failures.jsonl + brain.db
    ↓
DMs Kamal: "Updated [file] because [reason]. Diff: [what changed]"
```

**What this solves:** Kamal tells Kamil "you keep doing X wrong" exactly once. After that, kamil-evolution-agent finds the root file, adds the anti-pattern, and Kamil never does it again — without Kamal having to manually edit rules files.

---

## 5. Schema Validation at Handoffs

**Current gap:** Agents return free-text. One malformed output corrupts every downstream step.

**Fix:** Every agent that feeds another agent returns a typed JSON schema. The dispatcher validates it before passing forward. If validation fails, escalation-broker fires — not a silent failure.

Schemas needed:
```json
// kamil-manager.py Phase 1 output
{
  "real_intent": "string",
  "chosen_agent": "string (must be a known agent name)",
  "delegation_brief": "string",
  "slack_plan_message": "string",
  "confidence": "number (0-100)",
  "capability_gap": "string | null"
}

// taleemabad-bug-agent plan output
{
  "root_cause": "string",
  "plan_steps": ["string"],
  "e2e_test_cases": ["string"],
  "confidence": "number (0-100)",
  "files_to_touch": ["string"]
}

// Any agent final output
{
  "status": "done | blocked | partial",
  "summary": "string",
  "deliverable": "string | null (PR URL, Notion URL, etc.)",
  "partial_work": "string | null",
  "blocker": "string | null"
}
```

---

## 6. Escalation Protocol (Full)

```
Tick 1-2 blocked     → normal retry (existing behavior)
Tick 3+ blocked      → escalation-broker fires
    ↓
Broker attempts different angle (one attempt)
    ↓
Still blocked?
    ↓
Partial delivery → structured DM to Kamal
    ↓
Kamal replies → immediate event (not next tick) → dispatcher routes
```

Key addition: Kamal's reply creates an event that is processed **immediately**, not at the next 270s tick. The listener detects "reply in a thread where status=Blocked" and fast-paths it.

---

## 7. Effort-Scaling Rules

Baked into every subagent prompt — agents calibrate depth to task complexity:

| Task type | Max agent calls | Expected output size |
|-----------|-----------------|---------------------|
| Quick lookup / clarification | 3 | 1-3 sentences |
| Research question | 5-8 | 200-400 words with sources |
| Bug fix (simple) | 8-12 | PR, 1-3 files changed |
| Feature (medium) | 15-25 | PR, 3-10 files changed |
| Feature (large / full-stack) | 25-40 | PR, 10+ files, migration |
| Content piece | 5-10 | Draft ready for approval |

Agents that exceed their budget stop, deliver partial work, and flag it — they don't keep going.

---

## 8. What Does NOT Change

- **270s tick interval** — never changes without Kamal asking explicitly
- **context_key = Notion ticket entity ID** — the anchor for all event tracking
- **Status=Done is written LAST** — the commit signal
- **350ms between Notion API calls** — rate-limiting is non-negotiable
- **Tick atomicity** — any poller failure aborts the full tick
- **Plan-first for all implementation** — approval gate before any code
- **E2E gate before every PR** — no exceptions

---

## 9. Files to Create / Modify

### New files
```
.claude/agents/taleemabad-bug-agent.md
.claude/agents/kamil-evolution-agent.md
.claude/agents/escalation-broker.md
.claude/agents/job-agent.md
.claude/hooks/kamil-evolution-agent.py     ← the runner script
.claude/hooks/escalation-broker.py         ← stuck-state detector
.claude/rules/handoff-schemas.md           ← typed JSON schemas for all handoffs
```

### Modified files
```
.claude/hooks/kamil-slack-listener.py      ← routing decision as first step
.claude/hooks/kamil-manager.py             ← schema validation on Phase 1 output
.claude/hooks/orchestrator-dispatch.py    ← fast-path for Kamal replies to blocked tickets
.claude/rules/orchestrator.md              ← escalation protocol rules
.claude/rules/taleemabad.md                ← taleemabad-bug-agent replaces ad-hoc rules
.claude/rules/skills-router.md             ← new agents added to routing table
.claude/skills/kamil/kamil-self-gaps.md    ← updated with lessons from this session
```

---

## 10. Success Criteria

Kamil is working as designed when:

1. A Slack `@Kamil fix X` produces: `/feature` run → plan posted → wait for go. Zero clarifying questions. Zero execution options. Zero narration.
2. A ticket blocked for 2+ ticks produces: partial delivery posted + structured DM to Kamal with specific decision needed — not raw failure.
3. Kamal tells Kamil he keeps doing something wrong once. `kamil-evolution-agent` finds the file, adds the anti-pattern, DMs Kamal the diff. Kamil never does it again.
4. Every agent handoff carries a typed JSON payload that the dispatcher validates before routing forward.
5. Kamil's Slack replies feel like a senior team member — warm, direct, no robotic formatting, no document structure in conversational replies.

---

## 11. Out of Scope (This Redesign)

- Gmail integration (MCP configured, not wired — separate initiative)
- MemPalace full-text auto-indexing (separate initiative)
- taleemabad-CMS specialist agent (post-stabilization)
- Autonomous infra/deployment agent (post-stabilization)
- Full Graphify knowledge graph visualization (strategic horizon)
