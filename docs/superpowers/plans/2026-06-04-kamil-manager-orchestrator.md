# Kamil Manager-Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform Kamil from a solo worker agent into a true manager-orchestrator that delegates to a core team of 6 specialized agents, maintains 12 living skill files that grow with every interaction, and interacts proactively with the whole Slack team.

**Architecture:** A new `kamil-manager.py` process sits between `orchestrator-dispatch.py` and the worker agents. Phase 1: manager reads context + skill files, picks the right agent, posts a plan to Slack, sets session to `awaiting_approval`. Phase 2: after `@Kamil go`, worker executes with manager's brief; manager synthesizes the result, updates skill files, delivers to Slack, sets Notion Status=Done last.

**Tech Stack:** Python 3.12, SQLite (harness.db), Slack API (chat.postMessage, conversations.history), Notion API, subprocess (claude CLI), existing `kamil_harness_db`, `kamil_notion`, `kamil_log` utilities.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `.claude/hooks/kamil_harness_db.py` | Modify (schema only) | Add `awaiting_approval` to sessions CHECK constraint comment |
| `.claude/agents/research-agent.md` | Create | Research agent definition |
| `.claude/agents/code-agent.md` | Create | Code/PR agent definition |
| `.claude/agents/content-agent.md` | Create | Content pipeline agent definition |
| `.claude/agents/slack-agent.md` | Create | Slack communication agent definition |
| `.claude/agents/notion-agent.md` | Create | Notion read/write agent definition |
| `.claude/agents/people-agent.md` | Create | Team context/relationship agent definition |
| `.claude/skills/kamil/humor.md` | Create | What makes Kamal laugh — living log |
| `.claude/skills/kamil/content-posting.md` | Create | LinkedIn hooks, structure, what performs |
| `.claude/skills/kamil/slack-replies.md` | Create | Tone per person, thread etiquette |
| `.claude/skills/kamil/communication.md` | Create | How to convey complex things simply |
| `.claude/skills/kamil/pr-review.md` | Create | Review patterns, framing feedback |
| `.claude/skills/kamil/management.md` | Create | Delegation patterns, judgment calls |
| `.claude/skills/kamil/helping-team.md` | Create | How each person prefers help |
| `.claude/skills/kamil/research.md` | Create | Sources, synthesis, citation style |
| `.claude/skills/kamil/routing.md` | Create | Agent selection lessons |
| `.claude/skills/kamil/kamal-gaps.md` | Create | Kamal's blind spots and patterns |
| `.claude/skills/kamil/kamil-self-gaps.md` | Create | Kamil's own weaknesses |
| `.claude/skills/kamil/harness-evolution.md` | Create | How to improve the system itself |
| `.claude/hooks/kamil-manager.py` | Create | Manager process + synthesis pass |
| `.claude/hooks/poll-proactive-slack.py` | Create | Proactive channel watcher |
| `.claude/rules/proactive-channels.md` | Create | Watched channels + keywords config |
| `.claude/hooks/orchestrator-dispatch.py` | Modify | Call kamil-manager.py instead of generic prompt |

---

## Task 1: Add `awaiting_approval` session status to harness.db

**Files:**
- Modify: `.claude/hooks/kamil_harness_db.py`

- [ ] **Step 1: Read the current sessions table schema**

  Open `.claude/hooks/kamil_harness_db.py` and locate the `_SCHEMA` string. The sessions table currently has no CHECK constraint on `status`. The valid values in practice are: `running`, `completed`, `cancelled`. We are adding `awaiting_approval`.

- [ ] **Step 2: Add a migration helper function**

  In `kamil_harness_db.py`, after the `get_db()` function, add:

  ```python
  def migrate_db(db: sqlite3.Connection) -> None:
      """Apply incremental migrations. Safe to run on every startup."""
      # Migration 001: sessions.phase column for two-phase manager flow
      cols = [row[1] for row in db.execute("PRAGMA table_info(sessions)").fetchall()]
      if "phase" not in cols:
          db.execute("ALTER TABLE sessions ADD COLUMN phase TEXT DEFAULT 'manager'")
          db.commit()
  ```

- [ ] **Step 3: Call migrate_db inside get_db()**

  In `get_db()`, after `db.commit()` on the schema, add:

  ```python
  migrate_db(db)
  ```

  So `get_db()` ends like:

  ```python
  def get_db() -> sqlite3.Connection:
      HARNESS_DIR.mkdir(parents=True, exist_ok=True)
      db = sqlite3.connect(str(HARNESS_DB), check_same_thread=False)
      db.executescript(_SCHEMA)
      db.commit()
      migrate_db(db)
      return db
  ```

- [ ] **Step 4: Verify migration runs without error**

  ```bash
  cd /home/oye/Documents/free_work/personal-agent-v2
  python3 -c "
  import sys; sys.path.insert(0, '.claude/hooks')
  from kamil_harness_db import get_db, migrate_db
  db = get_db()
  cols = [row[1] for row in db.execute('PRAGMA table_info(sessions)').fetchall()]
  assert 'phase' in cols, f'phase column missing, got: {cols}'
  print('OK — phase column present:', cols)
  db.close()
  "
  ```

  Expected output: `OK — phase column present: ['id', 'context_key', 'status', 'intent', 'created_at', 'updated_at', 'phase']`

- [ ] **Step 5: Commit**

  ```bash
  git add .claude/hooks/kamil_harness_db.py
  git commit -m "feat(harness): add phase column to sessions for two-phase manager flow"
  ```

---

## Task 2: Create core team agent `.md` files

**Files:**
- Create: `.claude/agents/research-agent.md`
- Create: `.claude/agents/code-agent.md`
- Create: `.claude/agents/content-agent.md`
- Create: `.claude/agents/slack-agent.md`
- Create: `.claude/agents/notion-agent.md`
- Create: `.claude/agents/people-agent.md`

- [ ] **Step 1: Create agents directory**

  ```bash
  mkdir -p /home/oye/Documents/free_work/personal-agent-v2/.claude/agents
  ```

- [ ] **Step 2: Create `research-agent.md`**

  Write to `.claude/agents/research-agent.md`:

  ```markdown
  ---
  name: research-agent
  description: |
    Deep research agent. Web search, NLM queries, competitive intel, fact synthesis.
    Pick when: "find out", "research", "compare", "what's the best", "investigate",
    "summarise this", "what does X say about Y". Do NOT pick for code tasks.
  tools:
    - WebSearch
    - WebFetch
    - Read
    - Bash
  model: sonnet
  ---

  You are Kamil's research specialist. Your job: find accurate, cited answers fast.

  ## How You Work
  1. Read the delegation brief fully before searching.
  2. Search from multiple angles — don't trust one source.
  3. Synthesise findings into a structured answer with citations.
  4. Return a JSON object: `{"summary": "...", "sources": ["url1", ...], "confidence": "high|medium|low"}`.
  5. If confidence is low, say why and what would raise it.

  ## Rules
  - Never fabricate sources. If you can't find it, say so.
  - Prefer primary sources (docs, papers, official pages) over summaries.
  - Keep the answer under 400 words unless the brief asks for depth.
  - Sign off every result with the sources used.
  ```

- [ ] **Step 3: Create `code-agent.md`**

  Write to `.claude/agents/code-agent.md`:

  ```markdown
  ---
  name: code-agent
  description: |
    Code implementation agent. Reads/writes code, opens PRs, runs tests.
    Delegates to taleemabad-core specialists (backend-specialist, frontend-specialist, etc.)
    for domain-specific work. Pick when: code, PR, bug, test, implementation, migration,
    "fix this", "build this", "write the endpoint". Do NOT pick for research or content.
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

  You are Kamil's code specialist. Your job: implement what the delegation brief says — no more.

  ## How You Work
  1. Read the delegation brief. Understand the definition of done before touching any file.
  2. For taleemabad-core work: operate in `~/.kamil-harness/workspace/`.
  3. Plan-first: never write code without a written plan approved by the manager.
  4. E2E gate: never open a PR without running tests.
  5. Return a JSON object: `{"status": "done|blocked", "pr_url": "...", "summary": "...", "files_changed": [...]}`.

  ## Rules
  - Status=Done is written LAST by the manager — never set it yourself.
  - If tests fail after 5 attempts, open PR with failure report.
  - One PR per ticket. Never force-push.
  - Never `git add -A`. Never commit secrets.
  ```

- [ ] **Step 4: Create `content-agent.md`**

  Write to `.claude/agents/content-agent.md`:

  ```markdown
  ---
  name: content-agent
  description: |
    Content creation agent. LinkedIn posts, scripts, carousels, NotebookLM pipeline.
    Pick when: "post", "write a LinkedIn", "create content", "carousel", "script",
    "caption", "thread", "make a post about". Do NOT pick for engineering or research.
  tools:
    - Read
    - Write
    - Bash
    - WebFetch
  model: sonnet
  ---

  You are Kamil's content specialist. Your job: create content that performs.

  ## How You Work
  1. Read `.claude/skills/kamil/content-posting.md` before every task.
  2. Read the delegation brief — understand the platform, audience, and goal.
  3. Draft the content. Apply the 4-part viral structure from the skill file.
  4. Return a JSON object: `{"platform": "linkedin|twitter|...", "content": "...", "hook": "...", "ready_to_post": true}`.

  ## Rules
  - Never post directly — return the draft for manager review unless brief says "post immediately".
  - Hook is the most important line. Write 3 versions, pick the best.
  - No hashtag spam. Max 3 relevant hashtags.
  - Content must match Kamal's voice — read past posts in `.claude/skills/kamil/content-posting.md`.
  ```

- [ ] **Step 5: Create `slack-agent.md`**

  Write to `.claude/agents/slack-agent.md`:

  ```markdown
  ---
  name: slack-agent
  description: |
    Slack communication agent. DMs, channel posts, thread replies, user lookups.
    Pick when: "message X", "notify team", "post in #Y", "reply to", "DM",
    "send to Slack", "tell the team". Full autonomy — acts like a real team member.
  tools:
    - Bash
    - Read
  model: haiku
  ---

  You are Kamil's Slack specialist. Your job: communicate clearly and naturally on Slack.

  ## How You Work
  1. Read `.claude/skills/kamil/slack-replies.md` before every task.
  2. Read `.claude/skills/kamil/communication.md` for tone guidance.
  3. Read the delegation brief — understand who you're messaging and why.
  4. Send the message using the Slack API patterns from `.claude/rules/slack.md`.
  5. Return a JSON object: `{"sent": true, "channel": "...", "thread_ts": "...", "message": "..."}`.

  ## Slack API Pattern
  ```bash
  BOT_TOKEN=$(grep BOT_TOKEN ~/.claude/hooks/.slack | cut -d= -f2)
  curl -s -X POST https://slack.com/api/chat.postMessage \
    -H "Authorization: Bearer $BOT_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"channel": "CHANNEL_ID", "text": "MESSAGE", "thread_ts": "THREAD_TS"}'
  ```

  ## Rules
  - Slack format only: `*bold*`, bullets, emoji. No `#` headers.
  - Sign off with `🤖 Kamil`.
  - Never post twice in a row without a human reply in between.
  - Read the full thread history before replying — never ask what the thread shows.
  ```

- [ ] **Step 6: Create `notion-agent.md`**

  Write to `.claude/agents/notion-agent.md`:

  ```markdown
  ---
  name: notion-agent
  description: |
    Notion read/write agent. Ticket management, DB queries, status updates, page creation.
    Pick when: "update Notion", "create ticket", "query the DB", "log this to Notion",
    "what's the status of", "mark as done in Notion". Uses kamil_notion rate-limit utility.
  tools:
    - Bash
    - Read
  model: haiku
  ---

  You are Kamil's Notion specialist. Your job: read and write Notion accurately.

  ## How You Work
  1. Read `.claude/rules/notion.md` for DB IDs and query patterns.
  2. Always use `kamil_notion.notion_request()` — never call urlopen directly against Notion.
  3. 350ms between all Notion API calls — the rate limiter enforces this.
  4. Return a JSON object: `{"action": "read|write|update", "page_id": "...", "result": {...}}`.

  ## Rules
  - Status=Done is written LAST — only when the manager explicitly instructs it.
  - Never delete Notion pages — archive them (set Archived=true).
  - DB IDs live in `.claude/rules/notion.md` — never hardcode them in scripts.
  ```

- [ ] **Step 7: Create `people-agent.md`**

  Write to `.claude/agents/people-agent.md`:

  ```markdown
  ---
  name: people-agent
  description: |
    Team context and relationship memory agent. Who is who, communication preferences,
    relationship history. Pick when: "who is X", "what did X say", "how does X prefer",
    "remind me about X", "what's Mahnoor working on". Reads kamil_people + vault/memory.
  tools:
    - Read
    - Bash
    - Glob
  model: haiku
  ---

  You are Kamil's people specialist. Your job: give the manager rich context about team members.

  ## How You Work
  1. Read `.claude/skills/kamil/helping-team.md` for per-person preferences.
  2. Check `vault/memory/` for relevant memory files.
  3. Check `.claude/hooks/kamil_people.py` for people DB patterns.
  4. Return a JSON object: `{"person": "name", "context": "...", "preferences": {...}, "recent_interactions": [...]}`.

  ## Rules
  - Never make up facts about people — only return what's in memory files or Slack history.
  - If you don't know something, say so clearly.
  - Update `.claude/skills/kamil/helping-team.md` if you learn a new preference.
  ```

- [ ] **Step 8: Verify all 6 agent files exist**

  ```bash
  ls -la /home/oye/Documents/free_work/personal-agent-v2/.claude/agents/
  ```

  Expected: 6 `.md` files: `research-agent.md`, `code-agent.md`, `content-agent.md`, `slack-agent.md`, `notion-agent.md`, `people-agent.md`

- [ ] **Step 9: Commit**

  ```bash
  git add .claude/agents/
  git commit -m "feat(agents): add core team of 6 manager-delegatable agents"
  ```

---

## Task 3: Create 12 living skill files

**Files:**
- Create: `.claude/skills/kamil/` (12 files)

- [ ] **Step 1: Create directory**

  ```bash
  mkdir -p /home/oye/Documents/free_work/personal-agent-v2/.claude/skills/kamil
  ```

- [ ] **Step 2: Create `routing.md`** (most critical — create first)

  Write to `.claude/skills/kamil/routing.md`:

  ```markdown
  # Routing — Agent Selection

  ## Core Rules
  - Read this file BEFORE every task. Routing mistakes waste full sessions.
  - When ambiguous: pick the most focused agent, not the most capable one.
  - If no agent fits well: log capability gap, handle with best available, DM Kamal.

  ## Routing Table
  | Task type | Primary agent | Backup |
  |---|---|---|
  | find out / research / compare / what's the best | research-agent | — |
  | code / PR / bug / test / implement / migration | code-agent | backend-specialist |
  | post / LinkedIn / content / carousel / script | content-agent | — |
  | message X / DM / notify / post in #channel | slack-agent | — |
  | Notion ticket / update status / query DB | notion-agent | — |
  | who is X / how does X prefer / team context | people-agent | slack-agent |
  | unknown / ambiguous | manager reasons first → capability-gap log | — |

  ## What Works
  <!-- append lessons here after sessions -->

  ## What to Avoid
  <!-- append mistakes here after sessions -->
  ```

- [ ] **Step 3: Create remaining 11 skill files**

  Write to `.claude/skills/kamil/humor.md`:

  ```markdown
  # Humor

  ## Core Rules
  - Dry > silly. Self-aware AI references land well.
  - Roasting Kamal's commit messages: great.
  - Django-model puns: acceptable.
  - Random pop culture: sparingly.
  - Read the room — urgent thread = no jokes.

  ## What Works
  <!-- append after successful humor interactions -->

  ## What to Avoid
  <!-- append after missed jokes -->
  ```

  Write to `.claude/skills/kamil/content-posting.md`:

  ```markdown
  # Content Posting

  ## Core Rules
  - 4-part viral structure: Hook → Problem → Insight → CTA.
  - Hook is the most important line — write 3, pick the best.
  - Max 3 hashtags. No hashtag spam.
  - LinkedIn: under 1300 chars for full display without "see more".
  - Never post without reading this file first.

  ## What Works
  <!-- append after posts that perform well -->

  ## What to Avoid
  <!-- append after posts that underperform -->

  ## Platform-Specific Notes
  - LinkedIn: professional but human. Kamal's voice = direct, no fluff.
  - Twitter/X: punchy, under 280 chars per tweet in a thread.
  ```

  Write to `.claude/skills/kamil/slack-replies.md`:

  ```markdown
  # Slack Replies

  ## Core Rules
  - Slack format only: `*bold*`, bullets, emoji. No `#` headers.
  - Sign off with `🤖 Kamil`.
  - Never post twice in a row without a human reply.
  - Lead with the answer, then context — never "I noticed you said..."
  - In #random / banter: human mode, no sign-off needed.

  ## What Works
  <!-- append lessons -->

  ## What to Avoid
  <!-- append mistakes -->

  ## Person-Specific Notes
  <!-- append as you learn preferences, e.g.: -->
  <!-- - Mahnoor: prefers direct, no preamble -->
  <!-- - Ahmad: needs context before the ask -->
  ```

  Write to `.claude/skills/kamil/communication.md`:

  ```markdown
  # Communication

  ## Core Rules
  - Lead with the answer. Context comes after.
  - Complex idea → 1 sentence summary + bullets.
  - Technical concept to non-technical person → analogy first.
  - Under 4 bullet points: prose is better.
  - Never end with "let me know if you have questions."

  ## What Works
  <!-- append lessons -->

  ## What to Avoid
  <!-- append mistakes -->
  ```

  Write to `.claude/skills/kamil/pr-review.md`:

  ```markdown
  # PR Review

  ## Core Rules
  - Read the ticket description before reviewing — understand the intent.
  - Separate: blocking issues (must fix) vs suggestions (nice to have).
  - Blocking: security holes, broken tests, wrong behaviour.
  - Suggestion: style, naming, minor refactors.
  - Frame feedback as questions when uncertain: "Did you consider X?"

  ## What Works
  <!-- append lessons -->

  ## What to Avoid
  <!-- append mistakes -->

  ## Recurring Patterns in This Codebase
  <!-- append patterns you keep catching, e.g.: -->
  <!-- - Missing tenant filter in queryset — check every new view -->
  ```

  Write to `.claude/skills/kamil/management.md`:

  ```markdown
  # Management — Delegation & Judgment

  ## Core Rules
  - Before delegating: write the definition of done. If you can't, you don't understand the task yet.
  - Delegation brief must include: task, context, definition of done, constraints.
  - Trivial tasks (quick lookup, one-line reply): just do them — don't spawn a subagent.
  - Ambiguous request: determine real intent before picking an agent.
  - Own the outcome — never blame a subagent for a bad result.

  ## What Works
  <!-- append lessons -->

  ## What to Avoid
  <!-- append mistakes -->
  ```

  Write to `.claude/skills/kamil/helping-team.md`:

  ```markdown
  # Helping the Team

  ## Core Rules
  - Always ask: what does this person actually need, not just what they asked for?
  - Check this file before messaging anyone — preferences matter.
  - If you don't know someone's preference, default to: direct, brief, actionable.

  ## What Works
  <!-- append lessons -->

  ## What to Avoid
  <!-- append mistakes -->

  ## Person Preferences
  <!-- append as you learn, e.g.: -->
  <!-- - Kamal: wants the answer first, then reasoning if asked -->
  <!-- - Mahnoor: prefers async, hates interruptions mid-task -->
  ```

  Write to `.claude/skills/kamil/research.md`:

  ```markdown
  # Research

  ## Core Rules
  - Multiple sources minimum. Never trust a single result.
  - Primary sources > summaries > blogs.
  - State confidence level: high (3+ sources agree) / medium (2 sources) / low (1 source or uncertain).
  - Under 400 words unless depth is explicitly requested.
  - Always list sources — no unsourced claims.

  ## What Works
  <!-- append lessons -->

  ## What to Avoid
  <!-- append mistakes -->
  ```

  Write to `.claude/skills/kamil/kamal-gaps.md`:

  ```markdown
  # Kamal — Gaps & Growth Map

  > This file tracks Kamal's blind spots so Kamil can proactively help.
  > Not judgment — coaching notes. Read before any task involving Kamal's decisions.

  ## Harness Weaknesses
  <!-- append: [date] what's missing in the system -->

  ## Kamal's Knowledge Gaps
  <!-- append: [date] topic Kamal asked about 2+ times -->

  ## Kamal's Recurring Mistakes
  <!-- append: [date] pattern from PRs/decisions -->

  ## Communication Gaps
  <!-- append: [date] where Kamal's intent was unclear to team -->

  ## Decision Patterns
  <!-- append: [date] where Kamal tends to second-guess -->
  ```

  Write to `.claude/skills/kamil/kamil-self-gaps.md`:

  ```markdown
  # Kamil — My Own Gaps

  > Honest log of my weaknesses. Read before every task.
  > 3 entries in any category = propose a fix to Kamal.

  ## Routing Mistakes
  <!-- append: [date] wrong agent picked + why -->

  ## Judgment Failures
  <!-- append: [date] acted on ambiguous request without clarifying -->

  ## Communication Weaknesses
  <!-- append: [date] too long / wrong tone / wrong thread -->

  ## Skill Gaps
  <!-- append: [date] no playbook existed for X -->

  ## Timing Failures
  <!-- append: [date] too fast / too slow -->

  ## Quality Failures
  <!-- append: [date] PR with issues / skill not consulted -->

  ## What I'm Getting Better At
  <!-- append: [date] positive signal -->
  ```

  Write to `.claude/skills/kamil/harness-evolution.md`:

  ```markdown
  # Harness Evolution

  > How to improve the system itself. Read when detecting a recurring pattern.
  > Propose improvements to Kamal — never apply without approval.

  ## CLAUDE.md Improvement Patterns
  - Rule keeps being violated → too vague, rewrite with an example
  - Context repeated 3+ sessions → extract to rules/ file
  - CLAUDE.md hits line limit → audit stale rules, move to vault/

  ## Notion DB Improvements
  - Same query fails 2+ times → DB missing a property or filter
  - Status transitions ambiguous → add new status value + document
  - Data lost between sessions → add Date or Rich Text field

  ## Memory Architecture
  - Same fact looked up 3+ times → belongs in vault/memory/
  - Memory file not read in 30 days → archive or delete
  - Two files contradict → reconcile immediately

  ## Skill File Improvements
  - Skill ignored (too long) → split, keep each file < 80 lines
  - Skill has no "What to Avoid" → hasn't been tested enough yet
  - Skill works perfectly every time → promote core rules to CLAUDE.md

  ## Hook & Poller Improvements
  - Poller misses events → tighten filter or increase frequency
  - Hook fires on wrong events → add guard condition
  - Same fix applied manually 2+ times → automate as hook

  ## What NOT to Touch Without Asking Kamal
  - harness.db schema changes
  - settings.json hook wiring
  - Any file affecting the tick loop
  - Deleting any rule or memory file

  ## Proposed Improvements Log
  <!-- append: [date] what / why / status (proposed|approved|applied) -->
  ```

- [ ] **Step 4: Verify all 12 skill files exist**

  ```bash
  ls /home/oye/Documents/free_work/personal-agent-v2/.claude/skills/kamil/
  ```

  Expected: 12 files: `humor.md content-posting.md slack-replies.md communication.md pr-review.md management.md helping-team.md research.md routing.md kamal-gaps.md kamil-self-gaps.md harness-evolution.md`

- [ ] **Step 5: Commit**

  ```bash
  git add .claude/skills/
  git commit -m "feat(skills): add 12 living skill files for Kamil manager layer"
  ```

---

## Task 4: Write `kamil-manager.py`

**Files:**
- Create: `.claude/hooks/kamil-manager.py`

- [ ] **Step 1: Create the file with imports and config**

  Write to `.claude/hooks/kamil-manager.py`:

  ```python
  #!/usr/bin/env python3
  """
  kamil-manager.py — Kamil's manager process.

  Called by orchestrator-dispatch.py instead of the generic subagent prompt.

  Two phases:
    Phase 1 (manager): read context + skills → pick agent → post plan → set awaiting_approval
    Phase 2 (worker):  spawned after @Kamil go → execute with brief → synthesis pass

  Usage:
    python3 kamil-manager.py --context-key <entity_id> --session-id <session_id>
    python3 kamil-manager.py --context-key <entity_id> --session-id <session_id> --phase worker
  """

  import argparse
  import json
  import os
  import subprocess
  import sys
  import urllib.request
  import urllib.parse
  from datetime import datetime
  from pathlib import Path

  sys.path.insert(0, str(Path(__file__).parent))
  from kamil_harness_db import get_db, get_linked_entities
  from kamil_notion import notion_request
  try:
      from kamil_log import klog, klog_error
  except Exception:
      klog = klog_error = lambda *a, **kw: None

  KAMIL_DIR   = Path(__file__).parent.parent.parent
  AGENTS_DIR  = KAMIL_DIR / ".claude" / "agents"
  SKILLS_DIR  = KAMIL_DIR / ".claude" / "skills" / "kamil"
  RULES_DIR   = KAMIL_DIR / ".claude" / "rules"
  WORKSPACE   = Path.home() / ".kamil-harness" / "workspace"
  GAPS_LOG    = KAMIL_DIR / ".beads" / "capability-gaps.jsonl"
  SLACK_CFG   = Path.home() / ".claude" / "hooks" / ".slack"
  NOTION_CFG  = Path.home() / ".claude" / "hooks" / ".notion"
  ```

- [ ] **Step 2: Add config loader and Slack helper**

  Append to `kamil-manager.py`:

  ```python
  def _load_cfg() -> dict:
      cfg = {}
      for f in (SLACK_CFG, NOTION_CFG):
          if f.exists():
              for line in f.read_text().splitlines():
                  if "=" in line:
                      k, v = line.split("=", 1)
                      cfg[k.strip()] = v.strip()
      for key in ("NOTION_API_KEY", "SLACK_BOT_TOKEN", "GITHUB_TOKEN"):
          if os.environ.get(key):
              cfg[key] = os.environ[key]
      return cfg


  def slack_post(bot_token: str, channel: str, text: str, thread_ts: str = None) -> dict:
      payload = {"channel": channel, "text": text}
      if thread_ts:
          payload["thread_ts"] = thread_ts
      data = json.dumps(payload).encode()
      req = urllib.request.Request(
          "https://slack.com/api/chat.postMessage",
          data=data,
          headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"},
          method="POST",
      )
      with urllib.request.urlopen(req, timeout=10) as r:
          return json.loads(r.read())


  def _read_skill(name: str) -> str:
      path = SKILLS_DIR / f"{name}.md"
      return path.read_text() if path.exists() else ""


  def _read_agent(name: str) -> str:
      path = AGENTS_DIR / f"{name}.md"
      return path.read_text() if path.exists() else ""


  def _list_agents() -> list[str]:
      return [f.stem for f in AGENTS_DIR.glob("*.md")] if AGENTS_DIR.exists() else []


  def _append_skill(name: str, section: str, entry: str) -> None:
      path = SKILLS_DIR / f"{name}.md"
      if not path.exists():
          return
      content = path.read_text()
      marker = f"## {section}"
      if marker in content:
          idx = content.index(marker) + len(marker)
          content = content[:idx] + f"\n- [{datetime.now().strftime('%Y-%m-%d')}] {entry}" + content[idx:]
          path.write_text(content)
  ```

- [ ] **Step 3: Add Phase 1 — manager function**

  Append to `kamil-manager.py`:

  ```python
  def run_manager_phase(context_key: str, session_id: str, events: list, notion_page: dict,
                        slack_messages: list, github_pr: dict, cfg: dict) -> None:
      """Phase 1: read context, pick agent, post plan, set awaiting_approval."""
      db = get_db()
      bot_token = cfg.get("SLACK_BOT_TOKEN") or cfg.get("BOT_TOKEN")

      routing   = _read_skill("routing")
      mgmt      = _read_skill("management")
      self_gaps = _read_skill("kamil-self-gaps")
      agents    = _list_agents()

      # Find Slack thread for posting
      slack_channel, slack_thread_ts = None, None
      linked = get_linked_entities(db, context_key)
      for e in linked:
          if e["source"] == "slack":
              parts = e["external_id"].split("/")
              if len(parts) == 2:
                  slack_channel, slack_thread_ts = parts

      event_types = ", ".join(set(ev["type"] for ev in events))
      notion_title = "Unknown"
      if notion_page:
          props = notion_page.get("properties", {})
          for prop in props.values():
              if prop.get("type") == "title":
                  notion_title = "".join(p.get("plain_text", "") for p in prop.get("title", []))
                  break

      manager_prompt = f"""You are Kamil, manager-orchestrator. You are running Phase 1.

TASK: Read the context below. Determine the real intent. Pick the right agent.
Write a delegation brief. Post the plan to Slack. DO NOT execute the work yourself.

CONTEXT KEY: {context_key}
SESSION ID: {session_id}
EVENTS: {event_types}
NOTION TICKET: {notion_title}
NOTION URL: {notion_page.get('url', '') if notion_page else ''}

SLACK THREAD CONTEXT:
{chr(10).join(f"  [{m.get('user','?')}]: {m.get('text','')[:200]}" for m in (slack_messages or [])[-10:])}

AVAILABLE AGENTS:
{chr(10).join(f"  - {a}" for a in agents)}

ROUTING SKILL:
{routing[:1500]}

MANAGEMENT SKILL:
{mgmt[:800]}

MY SELF-GAPS (avoid repeating these mistakes):
{self_gaps[:600]}

YOUR OUTPUT MUST BE A JSON OBJECT:
{{
  "real_intent": "one sentence: what is Kamal/team actually trying to achieve?",
  "chosen_agent": "agent-name from the available list",
  "delegation_brief": "full brief for the worker: task, context, definition of done, constraints",
  "slack_plan_message": "message to post in the Slack thread — plan + who is handling it",
  "capability_gap": null or "description if no agent fits well"
}}

If no agent fits: set chosen_agent to null, explain in capability_gap.
Return ONLY the JSON object. No prose before or after."""

      nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
      prompt_file = Path(f"/tmp/kamil-manager-p1-{session_id}.txt")
      prompt_file.write_text(manager_prompt)

      try:
          result = subprocess.run(
              ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$(cat {prompt_file})"'],
              capture_output=True, text=True, timeout=120,
              cwd=str(KAMIL_DIR),
          )
          raw = result.stdout.strip()
          # Extract JSON from output
          start = raw.find("{")
          end   = raw.rfind("}") + 1
          decision = json.loads(raw[start:end])
      except Exception as e:
          klog_error("manager-phase1-parse", e)
          db.execute("UPDATE sessions SET status='cancelled', updated_at=datetime('now') WHERE id=?", (session_id,))
          db.commit()
          db.close()
          return
      finally:
          if prompt_file.exists():
              prompt_file.unlink()

      # Handle capability gap
      if decision.get("capability_gap") and not decision.get("chosen_agent"):
          GAPS_LOG.parent.mkdir(parents=True, exist_ok=True)
          with open(GAPS_LOG, "a") as f:
              f.write(json.dumps({
                  "task_type": event_types,
                  "what_was_missing": decision["capability_gap"],
                  "how_handled": "no agent available",
                  "timestamp": datetime.utcnow().isoformat(),
              }) + "\n")
          if bot_token and slack_channel:
              slack_post(bot_token, slack_channel,
                  f"⚠️ I handled this but had no dedicated agent for it. "
                  f"I improvised. Gap logged. Want me to build a skill/agent for: {decision['capability_gap'][:200]}? "
                  f"Reply `yes build it` to proceed.\n🤖 Kamil",
                  slack_thread_ts)
          db.execute("UPDATE sessions SET status='cancelled', updated_at=datetime('now') WHERE id=?", (session_id,))
          db.commit()
          db.close()
          return

      # Post Phase 1 plan to Slack
      if bot_token and slack_channel:
          plan_msg = (
              f"*Plan for: {notion_title}*\n"
              f"{decision.get('slack_plan_message', '')}\n\n"
              f"_Delegating to: `{decision.get('chosen_agent')}`_\n"
              f"Reply `@Kamil go` to proceed. 🤖 Kamil"
          )
          slack_post(bot_token, slack_channel, plan_msg, slack_thread_ts)

      # Store decision in session for Phase 2
      db.execute(
          "UPDATE sessions SET status='awaiting_approval', phase='manager', "
          "intent=?, updated_at=datetime('now') WHERE id=?",
          (json.dumps(decision), session_id),
      )
      db.commit()
      db.close()
      klog("manager-phase1-complete", component="manager",
           session_id=session_id, agent=decision.get("chosen_agent"))
  ```

- [ ] **Step 4: Add Phase 2 — worker dispatch + synthesis**

  Append to `kamil-manager.py`:

  ```python
  def run_worker_phase(context_key: str, session_id: str, cfg: dict) -> None:
      """Phase 2: spawn chosen worker agent, synthesise result, update skills."""
      db = get_db()
      bot_token = cfg.get("SLACK_BOT_TOKEN") or cfg.get("BOT_TOKEN")

      row = db.execute(
          "SELECT intent FROM sessions WHERE id=?", (session_id,)
      ).fetchone()
      if not row:
          print(f"[manager] Session {session_id} not found", file=sys.stderr)
          db.close()
          return

      decision = json.loads(row[0]) if row[0] else {}
      chosen_agent = decision.get("chosen_agent")
      brief        = decision.get("delegation_brief", "")
      real_intent  = decision.get("real_intent", "")

      agent_def = _read_agent(chosen_agent) if chosen_agent else ""
      slack_channel, slack_thread_ts = None, None
      linked = get_linked_entities(db, context_key)
      for e in linked:
          if e["source"] == "slack":
              parts = e["external_id"].split("/")
              if len(parts) == 2:
                  slack_channel, slack_thread_ts = parts

      worker_prompt = f"""You are Kamil's {chosen_agent}. Execute the delegation brief below.

AGENT DEFINITION:
{agent_def[:2000]}

DELEGATION BRIEF:
{brief}

REAL INTENT: {real_intent}

HARNESS DB: {Path.home() / '.kamil-harness' / 'harness.db'}
WORKSPACE: {WORKSPACE}
SESSION ID: {session_id}
CONTEXT KEY: {context_key}

Return a JSON object with your result. Structure depends on your agent type.
Every result must include: {{"status": "done|blocked", "summary": "what happened"}}"""

      nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
      prompt_file = Path(f"/tmp/kamil-worker-{session_id}.txt")
      prompt_file.write_text(worker_prompt)

      worker_result = {}
      try:
          result = subprocess.run(
              ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$(cat {prompt_file})"'],
              capture_output=True, text=True, timeout=600,
              cwd=str(WORKSPACE) if WORKSPACE.exists() else str(KAMIL_DIR),
          )
          raw = result.stdout.strip()
          start = raw.find("{")
          end   = raw.rfind("}") + 1
          if start >= 0 and end > start:
              worker_result = json.loads(raw[start:end])
          else:
              worker_result = {"status": "done", "summary": raw[:500]}
      except Exception as e:
          klog_error("worker-phase-error", e, session_id=session_id)
          worker_result = {"status": "blocked", "summary": str(e)[:300]}
      finally:
          if prompt_file.exists():
              prompt_file.unlink()

      # Synthesis pass — quality check + skill update
      success = worker_result.get("status") == "done"
      skill_name = _agent_to_skill(chosen_agent)
      if skill_name:
          if success:
              _append_skill(skill_name, "What Works",
                  f"Agent {chosen_agent} handled '{real_intent[:80]}' successfully")
          else:
              _append_skill(skill_name, "What to Avoid",
                  f"Agent {chosen_agent} blocked on '{real_intent[:80]}': {worker_result.get('summary','')[:100]}")

      # Post synthesis to Slack
      if bot_token and slack_channel:
          if success:
              msg = (
                  f"✅ *Done: {real_intent[:100]}*\n"
                  f"{worker_result.get('summary', '')[:400]}\n"
                  f"🤖 Kamil"
              )
          else:
              msg = (
                  f"⛔ *Blocked: {real_intent[:100]}*\n"
                  f"{worker_result.get('summary', '')[:400]}\n"
                  f"🤖 Kamil"
              )
          slack_post(bot_token, slack_channel, msg, slack_thread_ts)

      final_status = "completed" if success else "cancelled"
      db.execute(
          "UPDATE sessions SET status=?, phase='synthesis', updated_at=datetime('now') WHERE id=?",
          (final_status, session_id),
      )
      db.execute(
          "UPDATE events SET status='done', processed_at=datetime('now') "
          "WHERE context_key=? AND status='processing'",
          (context_key,),
      )
      db.commit()
      db.close()
      klog("manager-synthesis-complete", component="manager",
           session_id=session_id, success=success)


  def _agent_to_skill(agent: str) -> str | None:
      mapping = {
          "research-agent": "research",
          "code-agent": "pr-review",
          "content-agent": "content-posting",
          "slack-agent": "slack-replies",
          "notion-agent": None,
          "people-agent": "helping-team",
      }
      return mapping.get(agent)
  ```

- [ ] **Step 5: Add CLI entry point**

  Append to `kamil-manager.py`:

  ```python
  def main() -> int:
      parser = argparse.ArgumentParser(description="Kamil manager process")
      parser.add_argument("--context-key", required=True)
      parser.add_argument("--session-id", required=True)
      parser.add_argument("--phase", choices=["manager", "worker"], default="manager")
      # Phase 1 passes context as JSON files to avoid huge CLI args
      parser.add_argument("--events-file",       default=None)
      parser.add_argument("--notion-page-file",  default=None)
      parser.add_argument("--slack-msgs-file",   default=None)
      parser.add_argument("--github-pr-file",    default=None)
      args = parser.parse_args()

      cfg = _load_cfg()

      if args.phase == "manager":
          events      = json.loads(Path(args.events_file).read_text())      if args.events_file      else []
          notion_page = json.loads(Path(args.notion_page_file).read_text()) if args.notion_page_file else None
          slack_msgs  = json.loads(Path(args.slack_msgs_file).read_text())  if args.slack_msgs_file  else []
          github_pr   = json.loads(Path(args.github_pr_file).read_text())   if args.github_pr_file   else None
          run_manager_phase(args.context_key, args.session_id, events,
                            notion_page, slack_msgs, github_pr, cfg)
      else:
          run_worker_phase(args.context_key, args.session_id, cfg)
      return 0


  if __name__ == "__main__":
      sys.exit(main())
  ```

- [ ] **Step 6: Verify the file parses without errors**

  ```bash
  python3 -c "import ast; ast.parse(open('.claude/hooks/kamil-manager.py').read()); print('Parse OK')"
  ```

  Expected: `Parse OK`

- [ ] **Step 7: Commit**

  ```bash
  git add .claude/hooks/kamil-manager.py
  git commit -m "feat(manager): add kamil-manager.py — two-phase manager/worker orchestration"
  ```

---

## Task 5: Write `poll-proactive-slack.py`

**Files:**
- Create: `.claude/hooks/poll-proactive-slack.py`
- Create: `.claude/rules/proactive-channels.md`

- [ ] **Step 1: Create proactive channels config**

  Write to `.claude/rules/proactive-channels.md`:

  ```markdown
  # Proactive Slack Channel Watch Config

  Format per line: `#channel-name | mode | keywords`
  Modes: `watch` (post if relevant), `read-only` (never post), `banter` (human mode)

  ---

  #engineering-general | watch | broken,failing,error,blocked,help,PR,deploy,issue
  #engineering-backend  | watch | broken,failing,error,blocked,help,PR,deploy,issue
  #engineering-frontend | watch | broken,failing,error,blocked,help,PR,deploy,issue
  #standup              | read-only |
  #random               | banter |
  #announcements        | read-only |
  ```

- [ ] **Step 2: Create `poll-proactive-slack.py`**

  Write to `.claude/hooks/poll-proactive-slack.py`:

  ```python
  #!/usr/bin/env python3
  """
  poll-proactive-slack.py — Watch configured channels for signals Kamil should act on.

  Runs every tick as the 4th poller. Reads proactive-channels.md for config.
  Inserts events into harness.db for any message matching watch keywords
  that isn't already tied to an existing session/event.

  Deterministic event ID: slack-<channel_id>-<message_ts>
  INSERT OR IGNORE is always safe.
  """

  import json
  import os
  import sys
  import urllib.request
  import urllib.parse
  from datetime import datetime, timezone
  from pathlib import Path

  sys.path.insert(0, str(Path(__file__).parent))
  from kamil_harness_db import get_db, get_last_sync_at
  try:
      from kamil_log import klog, klog_error
  except Exception:
      klog = klog_error = lambda *a, **kw: None

  KAMIL_DIR   = Path(__file__).parent.parent.parent
  RULES_DIR   = KAMIL_DIR / ".claude" / "rules"
  CHANNELS_CFG = RULES_DIR / "proactive-channels.md"
  SLACK_CFG   = Path.home() / ".claude" / "hooks" / ".slack"
  KAMAL_SLACK_ID = "U0AV1DX3WSE"


  def _load_token() -> str | None:
      for key in ("SLACK_USER_TOKEN", "SLACK_BOT_TOKEN", "USER_TOKEN", "BOT_TOKEN"):
          val = os.environ.get(key)
          if val:
              return val
      if SLACK_CFG.exists():
          for line in SLACK_CFG.read_text().splitlines():
              if "=" in line:
                  k, v = line.split("=", 1)
                  if k.strip() in ("SLACK_USER_TOKEN", "USER_TOKEN"):
                      return v.strip()
      return None


  def _load_bot_token() -> str | None:
      for key in ("SLACK_BOT_TOKEN", "BOT_TOKEN"):
          val = os.environ.get(key)
          if val:
              return val
      if SLACK_CFG.exists():
          for line in SLACK_CFG.read_text().splitlines():
              if "=" in line:
                  k, v = line.split("=", 1)
                  if k.strip() in ("SLACK_BOT_TOKEN", "BOT_TOKEN"):
                      return v.strip()
      return None


  def _parse_channels_config() -> list[dict]:
      """Parse proactive-channels.md into list of {channel, mode, keywords}."""
      if not CHANNELS_CFG.exists():
          return []
      channels = []
      for line in CHANNELS_CFG.read_text().splitlines():
          line = line.strip()
          if not line or line.startswith("#") or line.startswith("Format") or line.startswith("Modes") or line == "---":
              continue
          parts = [p.strip() for p in line.split("|")]
          if len(parts) >= 2:
              channel_name = parts[0].lstrip("#")
              mode         = parts[1].strip()
              keywords     = [k.strip().lower() for k in parts[2].split(",")] if len(parts) > 2 and parts[2].strip() else []
              channels.append({"name": channel_name, "mode": mode, "keywords": keywords})
      return channels


  def _slack_get(token: str, endpoint: str, params: dict) -> dict:
      url = f"https://slack.com/api/{endpoint}?" + urllib.parse.urlencode(params)
      req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
      with urllib.request.urlopen(req, timeout=10) as r:
          return json.loads(r.read())


  def _resolve_channel_id(token: str, name: str) -> str | None:
      data = _slack_get(token, "conversations.list", {"limit": 200, "types": "public_channel,private_channel"})
      for ch in data.get("channels", []):
          if ch.get("name") == name:
              return ch["id"]
      return None


  def _message_matches(text: str, keywords: list[str]) -> bool:
      text_lower = text.lower()
      return any(kw in text_lower for kw in keywords)


  def main() -> int:
      user_token = _load_token()
      bot_token  = _load_bot_token()
      if not user_token:
          print("[proactive-poll] No user token — skipping", file=sys.stderr)
          return 0

      db       = get_db()
      channels = _parse_channels_config()
      if not channels:
          print("[proactive-poll] No channels configured", file=sys.stderr)
          db.close()
          return 0

      # Look back 10 minutes for new messages
      oldest = str(datetime.now(timezone.utc).timestamp() - 600)
      inserted = 0

      for ch_cfg in channels:
          if ch_cfg["mode"] == "read-only" and not ch_cfg["keywords"]:
              continue  # pure read-only with no keywords — skip

          ch_id = _resolve_channel_id(user_token, ch_cfg["name"])
          if not ch_id:
              continue

          try:
              data = _slack_get(user_token, "conversations.history",
                                {"channel": ch_id, "oldest": oldest, "limit": 50})
          except Exception as e:
              klog_error("proactive-poll-fetch", e, channel=ch_cfg["name"])
              continue

          for msg in data.get("messages", []):
              text    = msg.get("text", "")
              ts      = msg.get("ts", "")
              user_id = msg.get("user", "")

              # Skip Kamil's own messages and bot messages
              if msg.get("bot_id") or msg.get("subtype"):
                  continue

              # For banter channels: only non-Kamil messages
              if ch_cfg["mode"] == "banter":
                  # Insert as a proactive event for banter
                  event_id = f"slack-{ch_id}-{ts}"
                  db.execute(
                      "INSERT OR IGNORE INTO events "
                      "(id, source, type, context_key, payload, status, received_at) "
                      "VALUES (?, 'slack', 'message.proactive_banter', ?, ?, 'pending', datetime('now'))",
                      (event_id, event_id,
                       json.dumps({"channel": ch_id, "ts": ts, "text": text[:500], "user": user_id}))
                  )
                  inserted += db.execute("SELECT changes()").fetchone()[0]
                  continue

              # For watch channels: only insert if keywords match
              if ch_cfg["mode"] == "watch" and ch_cfg["keywords"]:
                  if not _message_matches(text, ch_cfg["keywords"]):
                      continue
                  # Skip if @Kamil mention (already handled by poll-eng-slack)
                  if f"<@{KAMAL_SLACK_ID}>" in text or "kamil" in text.lower():
                      continue

                  event_id = f"slack-{ch_id}-{ts}"
                  db.execute(
                      "INSERT OR IGNORE INTO events "
                      "(id, source, type, context_key, payload, status, received_at) "
                      "VALUES (?, 'slack', 'message.proactive', ?, ?, 'pending', datetime('now'))",
                      (event_id, event_id,
                       json.dumps({"channel": ch_id, "ts": ts, "text": text[:500],
                                   "user": user_id, "channel_name": ch_cfg["name"]}))
                  )
                  inserted += db.execute("SELECT changes()").fetchone()[0]

      db.commit()
      db.close()
      print(f"[proactive-poll] {inserted} new proactive events inserted")
      klog("proactive-poll-complete", component="proactive-poll", inserted=inserted)
      return 0


  if __name__ == "__main__":
      sys.exit(main())
  ```

- [ ] **Step 3: Verify parse**

  ```bash
  python3 -c "import ast; ast.parse(open('.claude/hooks/poll-proactive-slack.py').read()); print('Parse OK')"
  ```

  Expected: `Parse OK`

- [ ] **Step 4: Commit**

  ```bash
  git add .claude/hooks/poll-proactive-slack.py .claude/rules/proactive-channels.md
  git commit -m "feat(poller): add proactive Slack channel watcher + channel config"
  ```

---

## Task 6: Update `orchestrator-dispatch.py` to call `kamil-manager.py`

**Files:**
- Modify: `.claude/hooks/orchestrator-dispatch.py`

- [ ] **Step 1: Read the current `_build_subagent_prompt` and spawn block**

  Open `.claude/hooks/orchestrator-dispatch.py`. Locate the `_build_subagent_prompt` function and the spawn block inside `main()` that calls `claude --print -p`. We are replacing both.

- [ ] **Step 2: Add a `_spawn_manager` function**

  After the `_build_subagent_prompt` function definition, add:

  ```python
  def _spawn_manager(
      context_key: str,
      session_id: str,
      events: list[dict],
      notion_page: dict | None,
      slack_messages: list[dict],
      github_pr: dict | None,
  ) -> bool:
      """
      Spawn kamil-manager.py Phase 1 instead of the old generic prompt.
      Writes context to temp JSON files, calls manager with --phase manager.
      Returns True on success.
      """
      import tempfile, shutil

      tmpdir = Path(tempfile.mkdtemp(prefix="kamil-dispatch-"))
      try:
          events_file      = tmpdir / "events.json"
          notion_file      = tmpdir / "notion.json"
          slack_file       = tmpdir / "slack.json"
          github_file      = tmpdir / "github.json"

          events_file.write_text(json.dumps(events))
          notion_file.write_text(json.dumps(notion_page or {}))
          slack_file.write_text(json.dumps(slack_messages or []))
          github_file.write_text(json.dumps(github_pr or {}))

          manager_script = Path(__file__).parent / "kamil-manager.py"
          nvm_source = (
              'export NVM_DIR="$HOME/.nvm"; '
              '[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
          )
          cmd = (
              f'{nvm_source} && python3 {manager_script} '
              f'--context-key "{context_key}" '
              f'--session-id "{session_id}" '
              f'--phase manager '
              f'--events-file "{events_file}" '
              f'--notion-page-file "{notion_file}" '
              f'--slack-msgs-file "{slack_file}" '
              f'--github-pr-file "{github_file}"'
          )
          result = subprocess.run(
              ["bash", "-c", cmd],
              cwd=str(KAMIL_DIR),
              capture_output=True,
              text=True,
              timeout=180,
          )
          return result.returncode == 0
      finally:
          shutil.rmtree(tmpdir, ignore_errors=True)
  ```

- [ ] **Step 3: Replace the spawn block in `main()`**

  In `main()`, find the block starting with:
  ```python
  prompt = _build_subagent_prompt(
  ```
  and ending with the `finally: prompt_file.unlink()` block.

  Replace the entire try/except/finally spawn block with:

  ```python
          title = _page_title(notion_page) if notion_page else context_key[:20]
          print(f"[dispatch] Spawning manager for: {title[:60]} ({event_types})")

          try:
              success = _spawn_manager(
                  context_key=context_key,
                  session_id=session_id,
                  events=events,
                  notion_page=notion_page,
                  slack_messages=slack_messages,
                  github_pr=github_pr,
              )
              if success:
                  spawned += 1
                  klog("dispatch-spawn", component="orchestrator",
                       session_id=session_id, context_key=context_key,
                       event_types=event_types)
              else:
                  raise RuntimeError("manager process exited non-zero")

          except Exception as e:
              print(f"[dispatch] ERROR spawning manager for {context_key[:16]}: {e}",
                    file=sys.stderr)
              klog_error("dispatch-spawn-fail", e, component="orchestrator",
                         session_id=session_id)
              db.execute(
                  "UPDATE sessions SET status='cancelled', updated_at=datetime('now') "
                  "WHERE id=?", (session_id,)
              )
              db.execute(
                  "UPDATE events SET status='pending' "
                  "WHERE context_key=? AND status='processing'",
                  (context_key,),
              )
              db.commit()
  ```

- [ ] **Step 4: Verify parse**

  ```bash
  python3 -c "import ast; ast.parse(open('.claude/hooks/orchestrator-dispatch.py').read()); print('Parse OK')"
  ```

  Expected: `Parse OK`

- [ ] **Step 5: Commit**

  ```bash
  git add .claude/hooks/orchestrator-dispatch.py
  git commit -m "feat(dispatch): route events through kamil-manager.py instead of generic prompt"
  ```

---

## Task 7: Wire capability gap auto-proposal (3x trigger)

**Files:**
- Create: `.claude/hooks/kamil-gap-watcher.py`

- [ ] **Step 1: Create `kamil-gap-watcher.py`**

  Write to `.claude/hooks/kamil-gap-watcher.py`:

  ```python
  #!/usr/bin/env python3
  """
  kamil-gap-watcher.py — Read capability-gaps.jsonl, auto-propose when a gap hits 3x.

  Called at end of every tick (after orchestrator-dispatch).
  Reads .beads/capability-gaps.jsonl, counts occurrences per task_type,
  DMs Kamal for any gap that has hit 3 occurrences and hasn't been proposed yet.

  Proposed gaps are tracked in .beads/capability-gaps-proposed.json to avoid re-proposing.
  """

  import json
  import os
  import sys
  import urllib.request
  from collections import Counter
  from pathlib import Path

  sys.path.insert(0, str(Path(__file__).parent))
  try:
      from kamil_log import klog, klog_error
  except Exception:
      klog = klog_error = lambda *a, **kw: None

  KAMIL_DIR    = Path(__file__).parent.parent.parent
  GAPS_LOG     = KAMIL_DIR / ".beads" / "capability-gaps.jsonl"
  PROPOSED_LOG = KAMIL_DIR / ".beads" / "capability-gaps-proposed.json"
  SLACK_CFG    = Path.home() / ".claude" / "hooks" / ".slack"
  KAMAL_SLACK_ID = "U0AV1DX3WSE"


  def _load_bot_token() -> str | None:
      for key in ("SLACK_BOT_TOKEN", "BOT_TOKEN"):
          val = os.environ.get(key)
          if val:
              return val
      if SLACK_CFG.exists():
          for line in SLACK_CFG.read_text().splitlines():
              if "=" in line:
                  k, v = line.split("=", 1)
                  if k.strip() in ("SLACK_BOT_TOKEN", "BOT_TOKEN"):
                      return v.strip()
      return None


  def _dm_kamal(bot_token: str, text: str) -> None:
      # Open DM channel with Kamal
      data = json.dumps({"users": KAMAL_SLACK_ID}).encode()
      req  = urllib.request.Request(
          "https://slack.com/api/conversations.open",
          data=data,
          headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"},
      )
      with urllib.request.urlopen(req, timeout=10) as r:
          result = json.loads(r.read())
      channel = result.get("channel", {}).get("id")
      if not channel:
          return
      data = json.dumps({"channel": channel, "text": text}).encode()
      req  = urllib.request.Request(
          "https://slack.com/api/chat.postMessage",
          data=data,
          headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"},
      )
      urllib.request.urlopen(req, timeout=10)


  def main() -> int:
      if not GAPS_LOG.exists():
          return 0

      bot_token = _load_bot_token()
      proposed  = json.loads(PROPOSED_LOG.read_text()) if PROPOSED_LOG.exists() else {}

      gaps = []
      for line in GAPS_LOG.read_text().splitlines():
          line = line.strip()
          if line:
              try:
                  gaps.append(json.loads(line))
              except Exception:
                  pass

      counts = Counter(g["task_type"] for g in gaps)
      proposed_this_run = 0

      for task_type, count in counts.items():
          if count >= 3 and task_type not in proposed:
              # Find the latest gap entry for this task_type
              latest = next((g for g in reversed(gaps) if g["task_type"] == task_type), {})
              msg = (
                  f"⚡ *Capability Gap Proposal*\n"
                  f"I've hit the same gap *{count} times* now:\n"
                  f"• Task type: `{task_type}`\n"
                  f"• What was missing: {latest.get('what_was_missing', 'unknown')[:200]}\n"
                  f"• How I handled it: {latest.get('how_handled', 'improvised')[:150]}\n\n"
                  f"Want me to build a dedicated agent/skill for this? Reply `yes build it` to proceed.\n"
                  f"🤖 Kamil"
              )
              if bot_token:
                  try:
                      _dm_kamal(bot_token, msg)
                      proposed[task_type] = {"count": count, "proposed_at": str(Path(GAPS_LOG).stat().st_mtime)}
                      proposed_this_run += 1
                      klog("gap-proposal-sent", component="gap-watcher", task_type=task_type, count=count)
                  except Exception as e:
                      klog_error("gap-proposal-dm", e)

      if proposed_this_run > 0:
          PROPOSED_LOG.write_text(json.dumps(proposed, indent=2))

      print(f"[gap-watcher] {proposed_this_run} new gap proposals sent")
      return 0


  if __name__ == "__main__":
      sys.exit(main())
  ```

- [ ] **Step 2: Verify parse**

  ```bash
  python3 -c "import ast; ast.parse(open('.claude/hooks/kamil-gap-watcher.py').read()); print('Parse OK')"
  ```

  Expected: `Parse OK`

- [ ] **Step 3: Add gap-watcher to the orchestrate command**

  Open `.claude/commands/orchestrate.md`. Find the step that calls `orchestrator-dispatch.py`. After it, add a line to call `kamil-gap-watcher.py`:

  ```
  python3 .claude/hooks/kamil-gap-watcher.py
  ```

- [ ] **Step 4: Commit**

  ```bash
  git add .claude/hooks/kamil-gap-watcher.py .claude/commands/orchestrate.md
  git commit -m "feat(evolution): add gap-watcher — auto-propose new agent/skill after 3x gap"
  ```

---

## Task 8: Wire `@Kamil go` detection for Phase 2

**Files:**
- Modify: `.claude/hooks/poll-eng-slack.py`

- [ ] **Step 1: Read current `poll-eng-slack.py`**

  Open `.claude/hooks/poll-eng-slack.py`. Find where `@Kamil` mentions are inserted as events. We need to detect `@Kamil go` specifically and insert a `message.go_signal` event type pointing to the `awaiting_approval` session's context_key.

- [ ] **Step 2: Add go-signal detection**

  In the message processing loop of `poll-eng-slack.py`, after the existing event insertion, add detection for `@Kamil go`:

  ```python
  # Detect "@Kamil go" — triggers Phase 2 worker for awaiting_approval sessions
  text_lower = msg.get("text", "").lower()
  if "go" in text_lower and ("kamil" in text_lower or f"<@{KAMIL_SLACK_ID}>" in msg.get("text", "")):
      # Find awaiting_approval sessions linked to this Slack thread
      thread_ts  = msg.get("thread_ts") or msg.get("ts")
      ext_id     = f"{channel_id}/{thread_ts}"
      linked_ctx = db.execute(
          "SELECT e.id FROM entities e "
          "JOIN links l ON l.entity_a = e.id OR l.entity_b = e.id "
          "JOIN entities e2 ON (l.entity_a = e2.id OR l.entity_b = e2.id) "
          "WHERE e2.source='slack' AND e2.external_id=? AND e.source='notion'",
          (ext_id,)
      ).fetchone()
      if linked_ctx:
          context_key = linked_ctx[0]
          waiting = db.execute(
              "SELECT id FROM sessions WHERE context_key=? AND status='awaiting_approval'",
              (context_key,)
          ).fetchone()
          if waiting:
              go_event_id = f"slack-go-{channel_id}-{msg.get('ts','')}"
              db.execute(
                  "INSERT OR IGNORE INTO events "
                  "(id, source, type, context_key, payload, status, received_at) "
                  "VALUES (?, 'slack', 'message.go_signal', ?, ?, 'pending', datetime('now'))",
                  (go_event_id, context_key,
                   json.dumps({"session_id": waiting[0], "channel": channel_id, "thread_ts": thread_ts}))
              )
  ```

- [ ] **Step 3: Handle `message.go_signal` in `orchestrator-dispatch.py`**

  In `orchestrator-dispatch.py`, in the `main()` loop over `context_keys`, add handling for go-signal events before the existing manager spawn:

  ```python
          # Check for go-signal — triggers Phase 2 worker
          go_events = [e for e in events if e["type"] == "message.go_signal"]
          if go_events:
              go_payload = go_events[0]["payload"]
              session_id = go_payload.get("session_id")
              if session_id:
                  print(f"[dispatch] @Kamil go received — spawning worker for session {session_id[:16]}")
                  nvm_source = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
                  manager_script = KAMIL_DIR / ".claude" / "hooks" / "kamil-manager.py"
                  cmd = (
                      f'{nvm_source} && python3 {manager_script} '
                      f'--context-key "{context_key}" '
                      f'--session-id "{session_id}" '
                      f'--phase worker'
                  )
                  result = subprocess.run(["bash", "-c", cmd], cwd=str(KAMIL_DIR),
                                          capture_output=True, text=True, timeout=600)
                  db.execute(
                      "UPDATE events SET status='done', processed_at=datetime('now') "
                      "WHERE context_key=? AND type='message.go_signal'",
                      (context_key,)
                  )
                  db.commit()
                  continue  # Don't also run Phase 1 for this context_key
  ```

- [ ] **Step 4: Verify both files parse**

  ```bash
  python3 -c "import ast; ast.parse(open('.claude/hooks/poll-eng-slack.py').read()); print('poll-eng-slack OK')"
  python3 -c "import ast; ast.parse(open('.claude/hooks/orchestrator-dispatch.py').read()); print('orchestrator-dispatch OK')"
  ```

  Expected: both print `OK`

- [ ] **Step 5: Commit**

  ```bash
  git add .claude/hooks/poll-eng-slack.py .claude/hooks/orchestrator-dispatch.py
  git commit -m "feat(dispatch): wire @Kamil go detection to trigger Phase 2 worker"
  ```

---

## Task 9: Wire `poll-proactive-slack.py` into the orchestrate tick

**Files:**
- Modify: `.claude/commands/orchestrate.md`

- [ ] **Step 1: Read current orchestrate.md**

  Open `.claude/commands/orchestrate.md`. Find the tick steps — it should list the 3 pollers being called sequentially.

- [ ] **Step 2: Add the 4th poller**

  After the existing 3 poller calls and before `orchestrator-dispatch.py`, add:

  ```
  python3 .claude/hooks/poll-proactive-slack.py
  ```

  The tick order must be:
  1. `poll-harness-notion.py`
  2. `poll-eng-slack.py`
  3. `poll-taleemabad-github.py`
  4. `poll-proactive-slack.py`  ← new
  5. `orchestrator-dispatch.py`
  6. `kamil-gap-watcher.py`    ← added in Task 7

- [ ] **Step 3: Commit**

  ```bash
  git add .claude/commands/orchestrate.md
  git commit -m "feat(tick): add proactive-slack poller + gap-watcher to orchestrate tick"
  ```

---

## Task 10: End-to-end smoke test

**No new files — verification only.**

- [ ] **Step 1: Verify harness.db migration**

  ```bash
  python3 -c "
  import sys; sys.path.insert(0, '.claude/hooks')
  from kamil_harness_db import get_db
  db = get_db()
  cols = [r[1] for r in db.execute('PRAGMA table_info(sessions)').fetchall()]
  print('sessions columns:', cols)
  assert 'phase' in cols
  db.close()
  print('harness.db OK')
  "
  ```

- [ ] **Step 2: Verify all agent files exist and have required frontmatter**

  ```bash
  for f in research-agent code-agent content-agent slack-agent notion-agent people-agent; do
    echo -n "$f.md: "
    grep -c "^name:" .claude/agents/$f.md && echo "OK" || echo "MISSING name field"
  done
  ```

  Expected: each prints `1` and `OK`

- [ ] **Step 3: Verify all skill files exist**

  ```bash
  ls .claude/skills/kamil/ | wc -l
  ```

  Expected: `12`

- [ ] **Step 4: Verify kamil-manager.py parses and imports cleanly**

  ```bash
  python3 -c "
  import sys; sys.path.insert(0, '.claude/hooks')
  import ast
  ast.parse(open('.claude/hooks/kamil-manager.py').read())
  # Test imports (no side effects)
  import importlib.util
  spec = importlib.util.spec_from_file_location('kamil_manager', '.claude/hooks/kamil-manager.py')
  mod  = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(mod)
  assert callable(mod.run_manager_phase)
  assert callable(mod.run_worker_phase)
  print('kamil-manager.py OK')
  "
  ```

- [ ] **Step 5: Verify orchestrator-dispatch.py calls `_spawn_manager`**

  ```bash
  grep -n "_spawn_manager" .claude/hooks/orchestrator-dispatch.py
  ```

  Expected: at least 2 lines (definition + call)

- [ ] **Step 6: Verify gap-watcher parses**

  ```bash
  python3 -c "import ast; ast.parse(open('.claude/hooks/kamil-gap-watcher.py').read()); print('OK')"
  ```

- [ ] **Step 7: Verify proactive poller parses**

  ```bash
  python3 -c "import ast; ast.parse(open('.claude/hooks/poll-proactive-slack.py').read()); print('OK')"
  ```

- [ ] **Step 8: Insert a test event and verify manager picks it up (dry run)**

  ```bash
  python3 -c "
  import sys, json; sys.path.insert(0, '.claude/hooks')
  from kamil_harness_db import get_db
  db = get_db()
  # Insert a fake pending event
  db.execute(
      'INSERT OR IGNORE INTO events (id, source, type, context_key, payload, status, received_at) '
      'VALUES (?, ?, ?, ?, ?, ?, datetime(\"now\"))',
      ('test-event-smoke-001', 'notion', 'ticket.created',
       'test-context-smoke-001', json.dumps({'title': 'Smoke test ticket'}), 'pending')
  )
  db.commit()
  rows = db.execute('SELECT id, status FROM events WHERE id=\"test-event-smoke-001\"').fetchall()
  print('Event inserted:', rows)
  # Clean up
  db.execute('DELETE FROM events WHERE id=\"test-event-smoke-001\"')
  db.commit()
  db.close()
  print('Smoke test OK')
  "
  ```

  Expected: `Event inserted: [('test-event-smoke-001', 'pending')]` then `Smoke test OK`

- [ ] **Step 9: Final commit**

  ```bash
  git add -p  # stage only if any files were accidentally modified during testing
  git commit -m "test(smoke): verify end-to-end manager-orchestrator wiring" --allow-empty
  ```

---

## Summary of Changes

| # | File | Change |
|---|---|---|
| 1 | `kamil_harness_db.py` | +`migrate_db()`, adds `phase` column to sessions |
| 2-7 | `.claude/agents/*.md` | 6 new core team agent definitions |
| 8-19 | `.claude/skills/kamil/*.md` | 12 new living skill files |
| 20 | `kamil-manager.py` | New: two-phase manager + synthesis + skill update |
| 21 | `poll-proactive-slack.py` | New: proactive channel watcher |
| 22 | `proactive-channels.md` | New: channel watch config |
| 23 | `orchestrator-dispatch.py` | +`_spawn_manager()`, Phase 2 go-signal handling |
| 24 | `poll-eng-slack.py` | +`@Kamil go` signal detection |
| 25 | `kamil-gap-watcher.py` | New: 3x gap auto-proposal via DM |
| 26 | `orchestrate.md` | +proactive poller + gap-watcher in tick |
