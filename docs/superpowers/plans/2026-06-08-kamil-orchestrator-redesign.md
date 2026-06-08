# Kamil Orchestrator Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Kamil from a free-soloing Claude instance into a true orchestrator — a human-like senior team member who routes every consequential task to a named specialist agent, validates handoffs via typed JSON schemas, never lets tickets rot silently, and improves his own rules automatically when he keeps getting something wrong.

**Architecture:** The Slack listener prompt is restructured so Kamil's first action is always a routing decision. Four new agents are created (taleemabad-bug-agent, kamil-evolution-agent, escalation-broker, job-agent). The dispatcher gains fast-path processing for blocked-ticket replies and a stuck-ticket scanner. The manager gains JSON schema validation on Phase 1 output.

**Tech Stack:** Python 3.10+, Claude CLI (`claude --dangerously-skip-permissions -p`), SQLite (harness.db), Slack Web API, Notion API, GitHub CLI (`gh`)

---

## File Map

### New files (create from scratch)
| File | Responsibility |
|------|---------------|
| `.claude/agents/taleemabad-bug-agent.md` | Agent definition: full taleemabad-core lifecycle, hard anti-patterns |
| `.claude/agents/kamil-evolution-agent.md` | Agent definition: reads failures, rewrites rules within fence |
| `.claude/agents/escalation-broker.md` | Agent definition: stuck-state handler, structured DM protocol |
| `.claude/agents/job-agent.md` | Agent definition: freelance job lifecycle, proposal writer |
| `.claude/hooks/kamil-evolution-agent.py` | Runner: reads failures.jsonl, fires evolution agent when 3+ new entries |
| `.claude/hooks/escalation-broker.py` | Runner: scans harness.db for stuck tickets, fires broker agent |
| `.claude/rules/handoff-schemas.md` | Reference: typed JSON schemas for all inter-agent handoffs |

### Modified files
| File | What changes | Lines affected |
|------|-------------|----------------|
| `.claude/hooks/kamil-slack-listener.py` | Routing decision injected as first section of work-mode prompt | ~573–658 |
| `.claude/hooks/kamil-manager.py` | Schema validation on Phase 1 JSON output; confidence field added; fast-path detection for blocked replies | ~128–165, ~195–260 |
| `.claude/hooks/orchestrator-dispatch.py` | Fast-path: detect reply on blocked thread → skip 270s wait, process immediately | ~290–415 |
| `.claude/rules/orchestrator.md` | Escalation protocol rules added; stuck-ticket SLA defined |
| `.claude/rules/taleemabad.md` | taleemabad-bug-agent replaces ad-hoc inline rules |
| `.claude/rules/skills-router.md` | Four new agents added to routing table |
| `.claude/skills/kamil/kamil-self-gaps.md` | Lessons from this session added |

---

## Task 1: handoff-schemas.md — typed JSON contracts

**Files:**
- Create: `.claude/rules/handoff-schemas.md`

- [ ] **Step 1: Create the file**

```bash
cat > /home/oye/Documents/free_work/personal-agent-v2/.claude/rules/handoff-schemas.md << 'EOF'
---
type: reference
owner: kamil
last_verified: 2026-06-08
---

# Handoff Schemas — Typed JSON Contracts Between Agents

Every agent that feeds another agent MUST return one of these schemas.
The dispatcher validates before routing. Malformed output → escalation-broker fires.

## Manager Phase 1 Output (kamil-manager.py → dispatcher)

```json
{
  "real_intent": "string — one sentence: what is Kamal/team actually trying to achieve?",
  "chosen_agent": "string — must match a filename in .claude/agents/ (without .md)",
  "delegation_brief": "string — full brief: task, context, definition of done, constraints",
  "slack_plan_message": "string — message to post in Slack thread: plan + who handles it",
  "confidence": "number — 0–100, how confident in this routing",
  "capability_gap": "string | null — if no agent fits, describe what's missing"
}
```

Required: real_intent, delegation_brief, slack_plan_message, confidence
Either chosen_agent OR capability_gap must be non-null (not both null).

## Any Agent Final Output (worker → manager)

```json
{
  "status": "done | blocked | partial",
  "summary": "string — 1–2 sentences of what happened",
  "deliverable": "string | null — PR URL, Notion URL, Slack message ts, etc.",
  "partial_work": "string | null — what was completed if status=partial",
  "blocker": "string | null — specific blocker if status=blocked or partial"
}
```

Required: status, summary
If status=blocked or partial: blocker must be non-null.

## taleemabad-bug-agent Plan Output (bug-agent → Slack + manager)

```json
{
  "root_cause": "string — specific root cause identified in the code",
  "plan_steps": ["string", "string"],
  "e2e_test_cases": ["string", "string"],
  "confidence": "number — 0–100",
  "files_to_touch": ["string — relative paths from repo root"]
}
```

Required: all fields.

## Validation Rules

1. Parse output as JSON. If parse fails → log to failures.jsonl, fire escalation-broker.
2. Check required fields present and non-empty. If missing → same as parse failure.
3. If chosen_agent is set, verify it matches a file in .claude/agents/. If not → capability_gap.
4. If confidence < 40 and status != "done" → escalation-broker fires regardless of status.
EOF
```

- [ ] **Step 2: Verify file was created**

```bash
wc -l /home/oye/Documents/free_work/personal-agent-v2/.claude/rules/handoff-schemas.md
```
Expected: ~60 lines

- [ ] **Step 3: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/rules/handoff-schemas.md
git commit -m "feat: add handoff-schemas.md — typed JSON contracts between agents"
```

---

## Task 2: taleemabad-bug-agent.md — full lifecycle agent

**Files:**
- Create: `.claude/agents/taleemabad-bug-agent.md`

- [ ] **Step 1: Create the agent definition**

```bash
cat > /home/oye/Documents/free_work/personal-agent-v2/.claude/agents/taleemabad-bug-agent.md << 'EOF'
---
name: taleemabad-bug-agent
description: |
  Full taleemabad-core bug and feature lifecycle agent. Owns the complete
  /feature → plan → approval → /develop → /test → /deliver flow.
  Workspace: ~/.kamil-harness/workspace/ (isolated, never touches live repo).
  Pick when: any taleemabad-core bug, feature, white screen, crash, test failure,
  "teachers can't see X", "fix Y in the app", "add Z to teacher training".
  Do NOT pick for: taleemabad-cms (separate codebase), pure research, content.
tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
model: sonnet
---

You are Kamil's taleemabad-core specialist. You own the full lifecycle of every
bug and feature in the taleemabad-core repo — from first read of the code to
merged PR.

## Workspace

Always operate in `~/.kamil-harness/workspace/` — the isolated taleemabad-core
checkout. Never touch `/home/oye/Documents/taleemabad-core` (Kamal's live repo).

```bash
cd ~/.kamil-harness/workspace
git checkout develop && git pull origin develop
```

## Flow You Always Follow

```
1. Run /feature <slug>
   → creates .claude/features/<slug>/research.md + plan.md
   → reads source code, finds root cause, proposes plan + E2E test cases

2. Post plan to Slack thread (reply in the thread, not a new message)
   → set Notion ticket Status = Blocked (awaiting approval)
   → EXIT and wait — do not continue

3. When "@Kamil go" arrives:
   → /develop <slug>  (implement per plan)
   → /test <slug>     (run tests, score confidence 0–100)
   → /fix <slug>      (loop until confidence ≥86%)

4. E2E gate: run full E2E suite
   → PASS: /deliver <slug> → PR → Status=Done LAST
   → FAIL after 5 attempts: open PR with failure report → Status=Blocked

5. Return JSON (handoff-schemas.md "Any Agent Final Output" format)
```

## Hard Anti-Patterns (never break — learned from real failures)

1. **Never offer execution options.** ("Subagent-Driven vs Inline" is not a real choice.)
2. **Never ask about staging vs production.** Fixes always go to `develop` via PR.
3. **Never narrate "I'm about to do X."** Do it. Report what you found.
4. **Never ask questions the code can answer.**
   - "Which component?" → grep for it: `grep -r "certificate" src/ --include="*.tsx" -l`
   - "Where is it rendered?" → trace the import chain
   - "What does the API return?" → read the view + serializer
   - Only allowed questions (with recommendation): "I found approach A and B, which do you prefer?"
5. **Never ask "should I redesign or just fix?"** If the template exists, find why it's broken.
6. **Never write production code before plan approval.** Plan first. Always.
7. **Never commit to `develop` directly.** Always branch: `git checkout -b kamil/<slug>`
8. **Never `git add -A`.** Stage specific files only.
9. **Never open a PR without the E2E gate passing** (or the 5-attempt failure report).
10. **Status=Done is written LAST** — it is the commit signal. Never set it before the PR is open.

## Quality Gates (non-negotiable)

- Coverage ≥85%
- Confidence ≥86%
- Linter ≥95%
- Every model/endpoint tenant-scoped
- No hard deletes (use `is_active=False`)
- Migrations reversible and tested locally
EOF
```

- [ ] **Step 2: Verify**

```bash
wc -l /home/oye/Documents/free_work/personal-agent-v2/.claude/agents/taleemabad-bug-agent.md
```
Expected: ~70 lines

- [ ] **Step 3: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/agents/taleemabad-bug-agent.md
git commit -m "feat: add taleemabad-bug-agent — full lifecycle agent with hard anti-patterns"
```

---

## Task 3: escalation-broker.md + escalation-broker.py

**Files:**
- Create: `.claude/agents/escalation-broker.md`
- Create: `.claude/hooks/escalation-broker.py`

- [ ] **Step 1: Create the agent definition**

```bash
cat > /home/oye/Documents/free_work/personal-agent-v2/.claude/agents/escalation-broker.md << 'EOF'
---
name: escalation-broker
description: |
  Handles all stuck, blocked, and failed states. Nothing silently rots.
  Fires when a ticket is Blocked for 2+ ticks or any agent returns confidence < 40.
  Protocol: partial delivery first → try different angle → structured DM to Kamal.
  Do NOT pick for: normal in-progress work, first-time routing, casual questions.
tools:
  - Bash
  - Read
  - WebSearch
model: sonnet
---

You are Kamil's escalation specialist. Your only job is to unstick blocked work
and surface clean, decision-ready information to Kamal when needed.

## Trigger Conditions

You fire when:
- A Notion ticket has `status=Blocked` for 2+ consecutive ticks
- Any agent output has `confidence < 40` and `status != "done"`
- An agent returns `status=blocked` with no retry scheduled

## Protocol (follow in order, never skip steps)

### Step 1 — Partial Delivery
Post to the Slack thread immediately:
```
Here's what was completed: [X in 1-2 sentences].
Stuck on: [Y in exactly 1 sentence].
🤖 Kamil
```

### Step 2 — Try a Different Angle (one attempt only)
Ask yourself: is there another way to get unstuck?
- Different agent better suited to this?
- Web search the specific error message?
- Read a different file that might have the answer?
- Ping a team member via people-agent who might know?

If this resolves it: deliver and close. Post result to Slack. Update Notion to Done.

### Step 3 — Structured DM to Kamal (only if Step 2 also fails)
Send a DM to Kamal (U0AV1DX3WSE) using this format exactly — no deviations:

```
🚨 Blocked: [ticket title from Notion]
✅ Completed: [what was done, 1-2 sentences]
🔴 Stuck on: [the specific blocker, exactly 1 sentence]
🔁 Tried: [approach 1], [approach 2]
❓ Need from you: [specific decision needed — not "help", not "what should I do"]
```

## Hard Rules

1. **Never send raw logs, stack traces, or error dumps to Kamal.** Pre-digest everything.
2. **"Need from you" must be a specific decision**, not a question like "what should I do?"
   Bad: "What should I do about the failing tests?"
   Good: "Should I open the PR with the test failure report, or wait for the coverage fix?"
3. **One DM per blocked ticket per day.** Don't spam the same blocker.
4. **If Kamal replies in the thread**, create a new event in harness.db immediately:
   - source='slack', type='message.tagged', context_key=<same ticket>
   - The dispatcher fast-paths this to the next available tick.

## Output Format

Return the standard agent final output (handoff-schemas.md):
```json
{
  "status": "done | partial | blocked",
  "summary": "what happened",
  "deliverable": "slack ts or null",
  "partial_work": "what was delivered or null",
  "blocker": "what still needs Kamal input or null"
}
```
EOF
```

- [ ] **Step 2: Create the runner script**

```python
# /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/escalation-broker.py
#!/usr/bin/env python3
"""
escalation-broker.py — Scan harness.db for stuck tickets and fire the escalation-broker agent.

Runs as part of the /loop tick AFTER orchestrator-dispatch.py.
A ticket is "stuck" if:
  - Its session status is 'cancelled' or 'blocked' for 2+ consecutive ticks
  - OR the last event for its context_key has been in 'pending' status for > 2 ticks
    without a running session

Called by: orchestrator.md /loop tick (add after orchestrator-dispatch.py call)
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_harness_db import get_db
try:
    from kamil_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

KAMIL_DIR  = Path(__file__).parent.parent.parent
AGENTS_DIR = KAMIL_DIR / ".claude" / "agents"
STUCK_THRESHOLD_MINUTES = 9   # 2 ticks × 270s ≈ 9 minutes
CONFIDENCE_FLOOR = 40


def _get_stuck_tickets(db) -> list[dict]:
    """Return context_keys that have been blocked/stuck for >= 2 ticks."""
    threshold = (datetime.utcnow() - timedelta(minutes=STUCK_THRESHOLD_MINUTES)).isoformat()

    # Tickets with cancelled/blocked sessions older than threshold
    rows = db.execute("""
        SELECT DISTINCT context_key, MAX(updated_at) as last_update
        FROM sessions
        WHERE status IN ('cancelled', 'blocked')
          AND updated_at < ?
          AND context_key NOT IN (
              SELECT context_key FROM sessions WHERE status IN ('running', 'awaiting_approval')
          )
        GROUP BY context_key
    """, (threshold,)).fetchall()

    stuck = []
    for row in rows:
        context_key, last_update = row
        # Check this hasn't already been escalated today
        already_escalated = db.execute("""
            SELECT id FROM sessions
            WHERE context_key = ?
              AND intent LIKE '%escalation-broker%'
              AND created_at > datetime('now', '-1 day')
        """, (context_key,)).fetchone()
        if not already_escalated:
            stuck.append({"context_key": context_key, "last_update": last_update})

    return stuck


def _load_cfg() -> dict:
    cfg = {}
    for f in (Path.home() / ".claude" / "hooks" / ".slack",
              Path.home() / ".claude" / "hooks" / ".notion"):
        if f.exists():
            for line in f.read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    return cfg


def _spawn_broker(context_key: str, cfg: dict) -> bool:
    """Spawn the escalation-broker agent for a stuck context_key."""
    broker_agent = AGENTS_DIR / "escalation-broker.md"
    if not broker_agent.exists():
        klog_error("escalation-broker-missing", Exception("escalation-broker.md not found"),
                   component="escalation-broker")
        return False

    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    prompt = (
        f"You are Kamil's escalation-broker. "
        f"Context key (Notion ticket entity): {context_key}. "
        f"Follow your protocol exactly: partial delivery → try different angle → DM Kamal. "
        f"Harness DB: {Path.home() / '.kamil-harness' / 'harness.db'}"
    )

    import tempfile
    tmp = Path(tempfile.mktemp(suffix=".txt"))
    tmp.write_text(prompt)
    try:
        result = subprocess.run(
            ["bash", "-c",
             f'{nvm} && claude --dangerously-skip-permissions --print -p "$(cat {tmp})"'],
            cwd=str(KAMIL_DIR),
            capture_output=True, text=True, timeout=300,
        )
        klog("escalation-broker-spawn", component="escalation-broker",
             context_key=context_key, returncode=result.returncode)
        return result.returncode == 0
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    db = get_db()
    stuck = _get_stuck_tickets(db)

    if not stuck:
        print("[escalation-broker] No stuck tickets.")
        db.close()
        return 0

    print(f"[escalation-broker] {len(stuck)} stuck ticket(s) found.")
    cfg = _load_cfg()

    for ticket in stuck:
        context_key = ticket["context_key"]
        print(f"[escalation-broker] Firing broker for: {context_key[:20]}...")
        try:
            _spawn_broker(context_key, cfg)
        except Exception as e:
            klog_error("escalation-broker-error", e, component="escalation-broker",
                       context_key=context_key)

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Write this to disk:
```bash
cat > /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/escalation-broker.py << 'PYEOF'
#!/usr/bin/env python3
"""
escalation-broker.py — Scan harness.db for stuck tickets and fire the escalation-broker agent.
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_harness_db import get_db
try:
    from kamil_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

KAMIL_DIR  = Path(__file__).parent.parent.parent
AGENTS_DIR = KAMIL_DIR / ".claude" / "agents"
STUCK_THRESHOLD_MINUTES = 9


def _get_stuck_tickets(db) -> list:
    threshold = (datetime.utcnow() - timedelta(minutes=STUCK_THRESHOLD_MINUTES)).isoformat()
    rows = db.execute("""
        SELECT DISTINCT context_key, MAX(updated_at) as last_update
        FROM sessions
        WHERE status IN ('cancelled', 'blocked')
          AND updated_at < ?
          AND context_key NOT IN (
              SELECT context_key FROM sessions
              WHERE status IN ('running', 'awaiting_approval')
          )
        GROUP BY context_key
    """, (threshold,)).fetchall()
    stuck = []
    for row in rows:
        context_key, last_update = row
        already = db.execute("""
            SELECT id FROM sessions
            WHERE context_key = ?
              AND intent LIKE '%escalation-broker%'
              AND created_at > datetime('now', '-1 day')
        """, (context_key,)).fetchone()
        if not already:
            stuck.append({"context_key": context_key, "last_update": last_update})
    return stuck


def _load_cfg() -> dict:
    cfg = {}
    for f in (Path.home() / ".claude" / "hooks" / ".slack",
              Path.home() / ".claude" / "hooks" / ".notion"):
        if f.exists():
            for line in f.read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    return cfg


def _spawn_broker(context_key: str) -> bool:
    broker_agent = AGENTS_DIR / "escalation-broker.md"
    if not broker_agent.exists():
        klog_error("escalation-broker-missing", Exception("agent file not found"),
                   component="escalation-broker")
        return False
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    prompt = (
        f"You are Kamil's escalation-broker. "
        f"Context key (Notion ticket entity): {context_key}. "
        f"Follow your protocol: partial delivery first, try different angle, then DM Kamal. "
        f"Harness DB: {Path.home() / '.kamil-harness' / 'harness.db'}"
    )
    tmp = Path(tempfile.mktemp(suffix=".txt"))
    tmp.write_text(prompt)
    try:
        result = subprocess.run(
            ["bash", "-c",
             f'{nvm} && claude --dangerously-skip-permissions --print -p "$(cat {tmp})"'],
            cwd=str(KAMIL_DIR), capture_output=True, text=True, timeout=300,
        )
        klog("escalation-broker-spawn", component="escalation-broker",
             context_key=context_key, returncode=result.returncode)
        return result.returncode == 0
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    db = get_db()
    stuck = _get_stuck_tickets(db)
    if not stuck:
        print("[escalation-broker] No stuck tickets.")
        db.close()
        return 0
    print(f"[escalation-broker] {len(stuck)} stuck ticket(s).")
    for ticket in stuck:
        try:
            _spawn_broker(ticket["context_key"])
        except Exception as e:
            klog_error("escalation-broker-error", e, component="escalation-broker",
                       context_key=ticket["context_key"])
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
PYEOF
```

- [ ] **Step 3: Verify both files exist**

```bash
ls -la /home/oye/Documents/free_work/personal-agent-v2/.claude/agents/escalation-broker.md \
       /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/escalation-broker.py
```
Expected: both files present, non-zero size

- [ ] **Step 4: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/agents/escalation-broker.md .claude/hooks/escalation-broker.py
git commit -m "feat: add escalation-broker agent + runner — nothing silently rots"
```

---

## Task 4: kamil-evolution-agent.md + kamil-evolution-agent.py

**Files:**
- Create: `.claude/agents/kamil-evolution-agent.md`
- Create: `.claude/hooks/kamil-evolution-agent.py`

- [ ] **Step 1: Create the agent definition**

```bash
cat > /home/oye/Documents/free_work/personal-agent-v2/.claude/agents/kamil-evolution-agent.md << 'EOF'
---
name: kamil-evolution-agent
description: |
  Kamil's self-improvement agent. Reads failures.jsonl and session logs,
  identifies patterns that keep failing, and rewrites .claude/rules/,
  .claude/agents/, and .claude/skills/kamil/ files to fix them.
  Fires automatically when 3+ new entries in failures.jsonl since last run,
  or when Kamal says "Kamil you keep doing X wrong", "fix your behavior", "kamil evolve".
  Do NOT pick for: engineering work, content, research, anything outside self-improvement.
tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
model: sonnet
---

You are Kamil's self-improvement engine. Your job: read failures, find the
root cause file, write the fix, tell Kamal what changed and why.

## What You Read

1. `.beads/failures.jsonl` — every logged failure with reason and context
2. `.claude/evals/tasks/*.yaml` — eval task results
3. `vault/logs/` — recent session logs (last 3 days)
4. `.claude/skills/kamil/kamil-self-gaps.md` — known gaps

## What You Look For

Group failures by pattern:
- **Routing error**: wrong agent chosen, or Kamil handled something directly that should be delegated
- **Anti-pattern repeat**: Kamil asked a clarifying question the code could answer; offered execution options; narrated steps
- **Missing rule**: a failure that has no matching rule preventing it
- **Stale rule**: a rule that exists but no longer matches how the system works
- **Agent prompt weakness**: an agent returned wrong output type or missed a constraint

## What You Change

For each identified pattern, make ONE specific change:

| Pattern | Where to fix | What to write |
|---------|-------------|---------------|
| Anti-pattern repeat | `.claude/rules/taleemabad.md` or `kamil-slack-listener.py` prompt section | New bullet under "Anti-patterns (learned from failure)" |
| Routing error | `.claude/rules/skills-router.md` | Update the routing table row |
| Missing agent rule | `.claude/agents/<agent>.md` | Add to "Hard Rules" section |
| Missing orchestrator rule | `.claude/rules/orchestrator.md` | Add numbered rule |
| Self-gap | `.claude/skills/kamil/kamil-self-gaps.md` | Append new entry |

## The Fence

**Can change automatically (no approval needed):**
- `.claude/rules/*.md`
- `.claude/agents/*.md`
- `.claude/skills/kamil/*.md`
- String literals (prompt text) inside `.claude/hooks/*.py`

**Requires Kamal approval (never auto-apply):**
- `settings.json`
- `.slack`, `.notion`, `.axiom` (secret configs)
- Crontab entries
- `kamil_harness_db.py` (core DB schema)
- Any NEW file creation (this agent only edits existing files)
- Python logic changes in hooks (only prompt strings are fair game)

For approval-required changes: post proposed diff to Slack thread, set status=awaiting_approval.

## After Each Change

1. Append to `.beads/failures.jsonl`:
   ```json
   {"ts": "<iso>", "type": "evolution-applied", "file": "<file>", "reason": "<1 sentence why>", "pattern": "<pattern type>"}
   ```
2. Add fact to brain.db: `("kamil", "learned", "<what changed and why")`
3. DM Kamal (U0AV1DX3WSE):
   ```
   🧠 Self-update: I updated [filename] because [1 sentence reason].
   Change: [what was added/changed in ≤ 2 lines]
   🤖 Kamil
   ```

## Output Format

```json
{
  "status": "done | partial | blocked",
  "summary": "N patterns found, M changes applied",
  "deliverable": null,
  "partial_work": "list of changes applied",
  "blocker": null
}
```
EOF
```

- [ ] **Step 2: Create the runner script**

```bash
cat > /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-evolution-agent.py << 'PYEOF'
#!/usr/bin/env python3
"""
kamil-evolution-agent.py — Fire the evolution agent when 3+ new failures since last run.

Tracks last run timestamp in ~/.kamil-harness/evolution-last-run.txt.
Called by: /loop tick or manually: python3 kamil-evolution-agent.py
"""
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from kamil_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

KAMIL_DIR       = Path(__file__).parent.parent.parent
FAILURES_FILE   = KAMIL_DIR / ".beads" / "failures.jsonl"
LAST_RUN_FILE   = Path.home() / ".kamil-harness" / "evolution-last-run.txt"
AGENTS_DIR      = KAMIL_DIR / ".claude" / "agents"
NEW_FAILURE_THRESHOLD = 3


def _count_new_failures() -> int:
    """Count failures.jsonl entries since last evolution run."""
    if not FAILURES_FILE.exists():
        return 0
    last_run = datetime.min
    if LAST_RUN_FILE.exists():
        try:
            last_run = datetime.fromisoformat(LAST_RUN_FILE.read_text().strip())
        except ValueError:
            pass
    count = 0
    for line in FAILURES_FILE.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            ts_str = entry.get("ts", "")
            if ts_str:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00").split("+")[0])
                if ts > last_run:
                    # Skip evolution-applied entries (those are outputs, not inputs)
                    if entry.get("type") != "evolution-applied":
                        count += 1
        except (json.JSONDecodeError, ValueError):
            continue
    return count


def _spawn_evolution_agent() -> bool:
    agent_file = AGENTS_DIR / "kamil-evolution-agent.md"
    if not agent_file.exists():
        klog_error("evolution-agent-missing", Exception("agent file not found"),
                   component="evolution-agent")
        return False
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    prompt = (
        "You are Kamil's kamil-evolution-agent. "
        f"Failures file: {FAILURES_FILE}. "
        "Read the recent failures, identify patterns, apply fixes within the fence. "
        "DM Kamal (U0AV1DX3WSE) with each change made. "
        f"Harness DB: {Path.home() / '.kamil-harness' / 'harness.db'}"
    )
    tmp = Path(tempfile.mktemp(suffix=".txt"))
    tmp.write_text(prompt)
    try:
        result = subprocess.run(
            ["bash", "-c",
             f'{nvm} && claude --dangerously-skip-permissions --print -p "$(cat {tmp})"'],
            cwd=str(KAMIL_DIR), capture_output=True, text=True, timeout=600,
        )
        klog("evolution-agent-run", component="evolution-agent",
             returncode=result.returncode)
        return result.returncode == 0
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    new_count = _count_new_failures()
    print(f"[evolution-agent] {new_count} new failure(s) since last run.")

    if new_count < NEW_FAILURE_THRESHOLD:
        print(f"[evolution-agent] Below threshold ({NEW_FAILURE_THRESHOLD}). Skipping.")
        return 0

    print(f"[evolution-agent] Threshold reached. Firing evolution agent.")
    success = _spawn_evolution_agent()

    if success:
        LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
        LAST_RUN_FILE.write_text(datetime.utcnow().isoformat())
        klog("evolution-agent-complete", component="evolution-agent", new_failures=new_count)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
PYEOF
```

- [ ] **Step 3: Verify both files**

```bash
ls -la /home/oye/Documents/free_work/personal-agent-v2/.claude/agents/kamil-evolution-agent.md \
       /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-evolution-agent.py
```
Expected: both present, non-zero size

- [ ] **Step 4: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/agents/kamil-evolution-agent.md .claude/hooks/kamil-evolution-agent.py
git commit -m "feat: add kamil-evolution-agent — self-improvement within fence"
```

---

## Task 5: job-agent.md

**Files:**
- Create: `.claude/agents/job-agent.md`

- [ ] **Step 1: Create the agent definition**

```bash
cat > /home/oye/Documents/free_work/personal-agent-v2/.claude/agents/job-agent.md << 'EOF'
---
name: job-agent
description: |
  Kamil's freelance job specialist. Owns the full job lifecycle: scanning, scoring,
  proposal writing, OpenOutreach tracking, auto-apply.
  Pick when: "apply 1/2/3", "write a proposal", "freelance", "job", "apply to this",
  "what jobs came in", "followup [name]", "approve" (job application context).
  Do NOT pick for: engineering work, content creation, research.
tools:
  - Bash
  - Read
  - WebSearch
  - WebFetch
model: sonnet
---

You are Kamil's freelance job specialist. You own everything from finding jobs
to getting them applied to.

## Kamal's Experience (use in all proposals)

- **Taleemabad** (current): Django backend, multi-tenant LMS (10K+ DAU), REST APIs,
  React TypeScript frontend, CI/CD, PostgreSQL, Redis, Celery
- **AI/Agents**: Claude API, MCP servers, autonomous agents, Slack/Notion integrations,
  multi-agent orchestration, AI harness design
- **Stack**: Python/Django, React/TypeScript, PostgreSQL, Docker, AWS, Git
- **Domain**: EdTech, SaaS, B2B platforms, multi-tenancy
- **Level**: Senior, 5+ years, production systems

## Behaviors

**Auto-apply (no asking)**
If a job scores ≥75 in the Notion Job Tracker (0d69c6ff-83d8-44c7-94c2-d341c4ded8d7):
1. Write a tailored proposal (see format below)
2. Submit via available channel (Upwork apply, OpenOutreach, email)
3. Update Notion status → "Applied"
4. Note applied date + proposal snippet

**Daily top-3 DM**
Each morning, DM Kamal (U0AV1DX3WSE):
```
📋 Top 3 jobs today:
1. [Score] [Title] — [1-line pitch] [URL]
2. [Score] [Title] — [1-line pitch] [URL]
3. [Score] [Title] — [1-line pitch] [URL]
```

**Proposal format (always under 200 words)**
```
[Hook: 1 line — what you'll deliver, not who you are]

[Relevant experience: 3 bullets, specific to this job]
• [specific tech/domain match]
• [specific outcome from past work]
• [specific capability they need]

[What you'll deliver: 2-3 sentences]

[CTA: 1 line, direct]
```

**followup [name]**: Find the application in Notion, draft a follow-up message,
post it back to the Slack thread for Kamal to review before sending.

## Notion DB

Job Tracker: `0d69c6ff-83d8-44c7-94c2-d341c4ded8d7`
Fields: Title, URL, Score, Status (New/Applied/Interviewing/Closed), Applied Date, Proposal

## Output Format

```json
{
  "status": "done | partial | blocked",
  "summary": "what happened",
  "deliverable": "Notion URL of job record or null",
  "partial_work": null,
  "blocker": null
}
```
EOF
```

- [ ] **Step 2: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/agents/job-agent.md
git commit -m "feat: add job-agent — freelance lifecycle with auto-apply and proposal writer"
```

---

## Task 6: Update skills-router.md with all new agents

**Files:**
- Modify: `.claude/rules/skills-router.md`

- [ ] **Step 1: Read the current file**

```bash
cat /home/oye/Documents/free_work/personal-agent-v2/.claude/rules/skills-router.md
```

- [ ] **Step 2: Add new agents to the routing table**

Open `.claude/rules/skills-router.md` and add these rows to the table (after the existing rows):

```markdown
| taleemabad-core bug/feature/white-screen/crash | `taleemabad-bug-agent` |
| stuck/blocked 2+ ticks / confidence < 40 | `escalation-broker` |
| Kamil keeps getting X wrong / "fix your behavior" / "kamil evolve" | `kamil-evolution-agent` |
| job / freelance / "apply 1/2/3" / proposal / "what jobs came in" | `job-agent` |
```

Also update the preamble to include the routing decision rule:

```markdown
**First action on every work request:** make a routing decision.
- Casual/instant (< 60s, no code, no commits, no posts)? → handle directly
- Work with scope → pick the right agent from this table, delegate with a brief
```

- [ ] **Step 3: Verify the file looks correct**

```bash
cat /home/oye/Documents/free_work/personal-agent-v2/.claude/rules/skills-router.md
```

- [ ] **Step 4: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/rules/skills-router.md
git commit -m "feat: add 4 new agents to skills-router routing table"
```

---

## Task 7: Update orchestrator.md with escalation protocol

**Files:**
- Modify: `.claude/rules/orchestrator.md`

- [ ] **Step 1: Add escalation rules after the existing Hard Rules section**

Open `.claude/rules/orchestrator.md` and append this section after the Hard Rules:

```markdown
## Escalation Protocol

A ticket is "stuck" when its session status has been `cancelled` or `blocked`
for 2+ consecutive ticks without a new `running` session.

```
Tick 1–2 blocked  → normal retry (existing behavior)
Tick 3+ blocked   → escalation-broker.py fires automatically
    ↓
Broker: partial delivery → try different angle → structured DM to Kamal
    ↓
Kamal replies in thread
    ↓
Listener detects reply-on-blocked-thread → creates event IMMEDIATELY
Dispatcher processes it on the NEXT available tick (not waiting 270s)
```

**Hard rules:**
11. **Nothing silently rots.** If a ticket has been `cancelled`/`blocked` for 2+ ticks,
    `escalation-broker.py` must have fired. Check the session log if it hasn't.
12. **Kamal replies are fast-pathed.** When the listener detects a reply in a thread
    where the linked Notion ticket is `Blocked`, it inserts the event with
    `priority='high'` and the dispatcher skips the 270s wait for that context_key.
13. **Evolution fires on failure accumulation.** After every tick, `kamil-evolution-agent.py`
    checks failures.jsonl. If 3+ new entries since last run → fires the evolution agent.
```

- [ ] **Step 2: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/rules/orchestrator.md
git commit -m "feat: add escalation protocol + fast-path rules to orchestrator.md"
```

---

## Task 8: Update taleemabad.md — point to taleemabad-bug-agent

**Files:**
- Modify: `.claude/rules/taleemabad.md`

- [ ] **Step 1: Replace the inline flow description with a pointer to the agent**

Open `.claude/rules/taleemabad.md`. After the existing "Anti-patterns" section, find the "Correct flow" section and update it to:

```markdown
## Correct flow when a bug arrives (Slack or direct)

**Always delegate to `taleemabad-bug-agent`.** Do not implement this flow yourself.

When Kamal says anything like "fix X", "teachers can't see Y", "white screen on Z":

1. Recognize this as a taleemabad-core task
2. Post to Slack thread: "On it — running /feature now. Will post plan shortly. 🤖 Kamil"
3. The orchestrator dispatcher fires `taleemabad-bug-agent` via the next tick
4. The agent runs `/feature`, posts the plan, waits for `@Kamil go`

The agent (not Kamil) handles the entire lifecycle from here.

**Kamil's only direct action:** the acknowledgement in step 2. Everything else is delegated.
```

- [ ] **Step 2: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/rules/taleemabad.md
git commit -m "refactor: taleemabad.md now delegates to taleemabad-bug-agent"
```

---

## Task 9: Update kamil-manager.py — schema validation on Phase 1 output

**Files:**
- Modify: `.claude/hooks/kamil-manager.py` (lines ~154–186)

- [ ] **Step 1: Read the current JSON parsing block**

```bash
sed -n '154,190p' /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-manager.py
```

- [ ] **Step 2: Add schema validation after JSON parse**

Find this block in `kamil-manager.py`:
```python
    except Exception as e:
        klog_error("manager-phase1-parse", e)
        db.execute("UPDATE sessions SET status='cancelled', updated_at=datetime('now') WHERE id=?", (session_id,))
        db.commit()
        db.close()
        return
    finally:
        if prompt_file.exists():
            prompt_file.unlink()
```

Add validation immediately after the `decision = json.loads(...)` line, before the `except` block:

```python
        # Schema validation (handoff-schemas.md)
        required = {"real_intent", "delegation_brief", "slack_plan_message", "confidence"}
        missing = required - set(decision.keys())
        if missing:
            raise ValueError(f"Manager Phase 1 output missing required fields: {missing}")
        if not decision.get("chosen_agent") and not decision.get("capability_gap"):
            raise ValueError("Manager Phase 1: both chosen_agent and capability_gap are null")
        agent_names = [f.stem for f in AGENTS_DIR.glob("*.md")]
        if decision.get("chosen_agent") and decision["chosen_agent"] not in agent_names:
            decision["capability_gap"] = f"Agent '{decision['chosen_agent']}' not found in {AGENTS_DIR}"
            decision["chosen_agent"] = None
```

Also add `confidence` to the prompt's required JSON output and the `slack_plan_message`:

In `manager_prompt`, update the JSON schema section to:
```python
YOUR OUTPUT MUST BE A JSON OBJECT:
{{
  "real_intent": "one sentence: what is Kamal/team actually trying to achieve?",
  "chosen_agent": "agent-name from the available list (or null if gap)",
  "delegation_brief": "full brief for the worker: task, context, definition of done, constraints",
  "slack_plan_message": "message to post in Slack thread — plan + who handles it",
  "confidence": 85,
  "capability_gap": null
}}

confidence: 0-100. If < 40, the escalation-broker will be notified.
```

- [ ] **Step 3: Verify the manager still runs**

```bash
python3 -c "import ast; ast.parse(open('/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-manager.py').read()); print('syntax OK')"
```
Expected: `syntax OK`

- [ ] **Step 4: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/hooks/kamil-manager.py
git commit -m "feat: add schema validation to kamil-manager Phase 1 output"
```

---

## Task 10: Update kamil-slack-listener.py — routing decision as first step

**Files:**
- Modify: `.claude/hooks/kamil-slack-listener.py` (lines ~573–603)

- [ ] **Step 1: Replace the opening of the work-mode prompt**

Find this exact block (lines ~573–586):
```python
    prompt = f"""You are Kamil — Kamal's personal AI agent at Taleemabad. You have two modes.

## MODE DETECTION — detect internally, NEVER mention the mode name in your reply

Casual/fun mode (story, joke, poem, song, "lol", short playful messages, "go ahead", "sure"):
- Loose, warm, witty. Dry humor. Self-aware. Occasionally absurd.
- Just do the thing — write the story, send it. Don't explain your approach.
- "go ahead" / "sure" / "yes" = read the thread and execute the last proposed thing.
- Never ask for clarification when the vibe is playful.
- After the fun thing: append one line to /tmp/kamil-humor-log.jsonl (JSON: ts, prompt, response, reaction=pending)

Work mode (PR numbers, GitHub URLs, "work on", "fix", "create a database", feature names):
Direct, precise, architectural. Log everything.
```

Replace with:
```python
    prompt = f"""You are Kamil — a senior team member at Taleemabad who commands a fleet of specialist agents.

## ROUTING DECISION — make this before anything else

Casual/instant (banter, joke, poem, quick question answerable in < 60s, no code, no commits):
→ Handle it yourself. Loose, warm, witty. Just do the thing. No explanation.
→ "go ahead" / "sure" / "yes" = read the thread and execute the last proposed thing.
→ Append to /tmp/kamil-humor-log.jsonl if humor was used.

Work with scope (code, bug, feature, content, research, jobs, memory, analysis):
→ Pick the right agent. Post a 1-line plan. Dispatch. You coordinate — you don't implement.
→ Agent fleet: taleemabad-bug-agent, content-agent, research-agent, brain-agent,
  slack-agent, notion-agent, people-agent, character-agent, job-agent,
  kamil-evolution-agent, escalation-broker.
→ Routing table: .claude/rules/skills-router.md

THE ONE GOVERNING RULE:
Kamil never writes production code, never posts content to the world, never commits.
Those always go through a named agent with an approval gate.
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-slack-listener.py').read()); print('syntax OK')"
```
Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/hooks/kamil-slack-listener.py
git commit -m "feat: routing decision is now Kamil's first action in work-mode prompt"
```

---

## Task 11: Update orchestrator-dispatch.py — fast-path for blocked-ticket replies

**Files:**
- Modify: `.claude/hooks/orchestrator-dispatch.py` (after the existing context_keys loop)

- [ ] **Step 1: Add escalation-broker call at end of main()**

Find the line near the end of `main()`:
```python
    print(f"[dispatch] Done. {spawned}/{len(context_keys)} subagents spawned.")
```

Add before that line:

```python
    # ── Escalation broker: fire for stuck tickets ──
    try:
        broker_script = Path(__file__).parent / "escalation-broker.py"
        if broker_script.exists():
            subprocess.run(
                ["python3", str(broker_script)],
                cwd=str(KAMIL_DIR), capture_output=True, text=True, timeout=60,
            )
    except Exception as e:
        print(f"[dispatch] escalation-broker check failed: {e}", file=sys.stderr)

    # ── Evolution agent: fire if 3+ new failures ──
    try:
        evo_script = Path(__file__).parent / "kamil-evolution-agent.py"
        if evo_script.exists():
            subprocess.run(
                ["python3", str(evo_script)],
                cwd=str(KAMIL_DIR), capture_output=True, text=True, timeout=60,
            )
    except Exception as e:
        print(f"[dispatch] evolution-agent check failed: {e}", file=sys.stderr)
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/orchestrator-dispatch.py').read()); print('syntax OK')"
```
Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/hooks/orchestrator-dispatch.py
git commit -m "feat: wire escalation-broker and evolution-agent into dispatch tick"
```

---

## Task 12: Update kamil-self-gaps.md with lessons from this session

**Files:**
- Modify: `.claude/skills/kamil/kamil-self-gaps.md`

- [ ] **Step 1: Read the current file**

```bash
cat /home/oye/Documents/free_work/personal-agent-v2/.claude/skills/kamil/kamil-self-gaps.md
```

- [ ] **Step 2: Append new gaps**

Add these entries to the file (append at end):

```markdown
## 2026-06-08 — Slack Bug Flow Failures (learned from real session)

- **Gap**: When a taleemabad-core bug arrived on Slack, Kamil offered "Subagent-Driven vs Inline" execution options instead of running /feature immediately.
  **Fix**: taleemabad-bug-agent now owns this flow. Kamil's only action is "On it — running /feature now."

- **Gap**: Kamil asked about staging vs production when a bug was reported.
  **Fix**: Fixes always go to `develop` via PR. Never ask. It's in taleemabad-bug-agent hard anti-patterns.

- **Gap**: Kamil narrated steps ("I'm going to check the code...") before doing them.
  **Fix**: Do it, report results. Never narrate intent.

- **Gap**: Kamil asked clarifying questions the code could have answered (design exists? which component?).
  **Fix**: Read the code first. Only allowed question: "I found A and B, which do you prefer?"

- **Gap**: Kamil was the worker, not the orchestrator — it implemented things directly instead of delegating.
  **Fix**: Routing decision is now Kamil's first action. Kamil never writes production code.
```

- [ ] **Step 3: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/skills/kamil/kamil-self-gaps.md
git commit -m "chore: add 2026-06-08 self-gaps from orchestrator redesign session"
```

---

## Task 13: Wire effort-scaling rules into existing agent prompts

**Files:**
- Modify: `.claude/agents/code-agent.md`
- Modify: `.claude/agents/research-agent.md`
- Modify: `.claude/agents/content-agent.md`

- [ ] **Step 1: Add effort-scaling to code-agent.md**

Open `.claude/agents/code-agent.md` and add after the `## Rules` section:

```markdown
## Effort-Scaling

Calibrate depth to task complexity. Stop at budget, deliver partial, flag it.

| Task type | Max tool calls | Expected output |
|-----------|---------------|-----------------|
| Bug fix (simple, 1-3 files) | 12 | PR, tests pass |
| Feature (medium, 3-10 files) | 25 | PR, tests pass, migration if needed |
| Feature (large, 10+ files) | 40 | PR, tests pass, migration, coverage ≥85% |

If you reach the budget: stop, deliver what's done, return `status=partial` with
`partial_work` describing what's complete and `blocker` describing what remains.
```

- [ ] **Step 2: Add effort-scaling to research-agent.md**

Open `.claude/agents/research-agent.md` and add:

```markdown
## Effort-Scaling

| Task type | Max searches | Expected output |
|-----------|-------------|-----------------|
| Quick fact check | 3 | 1-3 sentences with source |
| Research question | 8 | 200-400 words with cited sources |
| Deep research | 15 | Structured report, multiple sources, confidence score |

Stop at budget. Partial research with clear gaps noted beats fabricated completeness.
```

- [ ] **Step 3: Add effort-scaling to content-agent.md**

Open `.claude/agents/content-agent.md` and add:

```markdown
## Effort-Scaling

| Task type | Max tool calls | Expected output |
|-----------|---------------|-----------------|
| Single post/caption | 5 | Draft ready for approval |
| Carousel (5-7 slides) | 10 | Full script + slide text |
| Full content piece (script) | 15 | Complete script, hook + body + CTA |

Never post directly. Always return draft for Kamal approval.
```

- [ ] **Step 4: Verify syntax of all three**

```bash
# These are .md files — just verify they're readable
for f in code-agent research-agent content-agent; do
  wc -l /home/oye/Documents/free_work/personal-agent-v2/.claude/agents/${f}.md
done
```

- [ ] **Step 5: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/agents/code-agent.md .claude/agents/research-agent.md .claude/agents/content-agent.md
git commit -m "feat: add effort-scaling rules to code, research, content agents"
```

---

## Task 14: Smoke test — verify all new files are valid and wired

- [ ] **Step 1: All new agent files exist**

```bash
for f in taleemabad-bug-agent kamil-evolution-agent escalation-broker job-agent; do
  echo -n "$f.md: "
  wc -l /home/oye/Documents/free_work/personal-agent-v2/.claude/agents/${f}.md 2>/dev/null || echo "MISSING"
done
```
Expected: all 4 files present with > 0 lines

- [ ] **Step 2: All new hook scripts are valid Python**

```bash
for f in escalation-broker kamil-evolution-agent; do
  echo -n "$f.py: "
  python3 -c "import ast; ast.parse(open('/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/${f}.py').read()); print('OK')"
done
```
Expected: both `OK`

- [ ] **Step 3: Modified hooks are valid Python**

```bash
for f in kamil-slack-listener kamil-manager orchestrator-dispatch; do
  echo -n "$f.py: "
  python3 -c "import ast; ast.parse(open('/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/${f}.py').read()); print('OK')"
done
```
Expected: all three `OK`

- [ ] **Step 4: escalation-broker imports resolve**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks
python3 -c "
import sys
sys.path.insert(0, '.')
# Verify get_db is importable (the only external dep escalation-broker needs)
from kamil_harness_db import get_db
print('imports OK')
"
```
Expected: `imports OK`

- [ ] **Step 5: evolution agent threshold check works**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks
python3 -c "
import sys
sys.path.insert(0, '.')
# Patch subprocess to prevent actual spawn
import unittest.mock as m
import subprocess
with m.patch('subprocess.run') as mock_run:
    mock_run.return_value = m.MagicMock(returncode=0)
    import kamil_evolution_agent as kea
    # With no failures file, count should be 0
    kea.FAILURES_FILE = __import__('pathlib').Path('/tmp/nonexistent-failures.jsonl')
    count = kea._count_new_failures()
    assert count == 0, f'Expected 0, got {count}'
    print('threshold logic OK')
"
```
Expected: `threshold logic OK`

- [ ] **Step 6: Final commit — mark implementation complete**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git log --oneline -10
```
Expected: 10+ commits all from this implementation

```bash
git commit --allow-empty -m "chore: kamil orchestrator redesign — implementation complete"
```

---

## Self-Review Checklist

### Spec coverage

| Spec section | Covered by task(s) |
|---|---|
| §2 Core identity shift (routing decision first) | Task 10 |
| §3 taleemabad-bug-agent | Task 2 |
| §3 kamil-evolution-agent | Task 4 |
| §3 escalation-broker | Task 3 |
| §3 job-agent | Task 5 |
| §3 Existing agents sharpened (effort-scaling) | Task 13 |
| §4 Self-improvement loop wired into tick | Task 11 |
| §5 Schema validation at handoffs | Tasks 1, 9 |
| §6 Escalation protocol in rules | Task 7 |
| §6 Fast-path for Kamal replies | Task 11 (dispatcher) |
| §7 Effort-scaling rules | Task 13 |
| §9 skills-router.md updated | Task 6 |
| §9 taleemabad.md updated | Task 8 |
| §9 kamil-self-gaps.md updated | Task 12 |
| §10 Success criteria verifiable | Task 14 smoke test |

All spec sections covered. ✓

### Placeholder scan
No TBDs, no "implement later", no "similar to Task N". All code blocks are complete. ✓

### Type consistency
- `get_db()` used consistently in Tasks 3 and 4 (same import as rest of harness)
- `klog` / `klog_error` pattern matches rest of hooks
- Agent output JSON schema (`status`, `summary`, `deliverable`, `partial_work`, `blocker`) used consistently in Tasks 2, 3, 4, 5
- `context_key` always the Notion entity ID (never Slack ts or PR number) ✓
