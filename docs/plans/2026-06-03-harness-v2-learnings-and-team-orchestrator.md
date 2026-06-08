# Plan: Evolve Kamil into Team Orchestrator (harness-v2 model)

**Date:** 2026-06-03  
**Source:** https://github.com/Orenda-Project/orchestration-harness-v2  
**Owner:** Kamil  
**Status:** Revised after deep review — ready to implement  
**Reviewed against:** CLAUDE.md, CONTEXT.md, schema.sql, sync-state.md, dispatch.md, poll-notion.md, poll-slack.md, poll-github.md, entity-registry.md, e2e-test.md, design spec

---

## What Was Wrong in the Previous Plan

The previous plan was reviewed against the actual harness-v2 repo and found these problems:

| # | Problem | Impact |
|---|---|---|
| C1 | Proposed per-script SQLite locks — harness uses ONE unified DB with 6 tables | Architecture inversion — bolt-on won't work |
| C2 | Dispatcher missing Steps 4, 5, 7 (session record, mark-processing, failure revert) | Running-session guard never works; failed subagents leave events stuck |
| C3 | Event IDs not specified as deterministic — repo requires `source-channel-ts` format | Re-polling after failure creates duplicate events |
| C4 | `SLACK_USER_TOKEN` missing — `search.messages` API requires it, bot token alone fails | Slack poller cannot query channel history |
| C5 | GitHub poller described as "all PRs" — repo only tracks agent-opened PRs via entity DB | Would attempt to process PRs it has no context for |
| C6 | `Status` property name used inconsistently — skills use `Status`, design spec says `Agent Status` | Canonical: `Status` (what the skill files actually use) |
| M1 | Plan-first approval gate (Step A/B split) completely missing | Subagents would auto-code without human approval — defeats the design |
| M2 | E2E testing gate before PR missing | PRs would open without automated testing |
| M3 | Required Notion DB properties not listed | No setup step — harness silently fails on missing columns |
| M4 | Entity registry dedup logic missing | Naive SQL would produce duplicate entity records |
| M5 | Blocked-state resumption via @agent reply missing | Second Slack trigger case not handled |
| M6 | Workspace directory convention missing | Subagents don't know where to operate |
| M7 | Tick atomicity rule (abort if any poller fails) missing | Partial ticks corrupt sync state |
| M8 | Screenshot upload to Notion (E2E Phase 5) missing | No observability on E2E failures |

---

## NotebookLM Usage Policy

NLM is a **content and research tool** — not a knowledge store for engineering patterns.

| Use NLM for | Do NOT use NLM for |
|---|---|
| Content creation (scripts, posts, carousels, podcasts) | Engineering Q&A |
| Internet research on trends, fitness, niches | Pattern lookups from code repos |
| Pre-researched deep-dives for content generation | Answering Slack engineering questions |

For engineering questions: read the actual source directly (`gh repo clone`, `Read`, `Grep`, `WebFetch`). Live code is always more accurate than a notebook copy.

---

## Architecture Overview

```
/loop — fires every 270s exactly (never change without asking Kamal)
    ↓
sync-state: acquire tick lock → read last_sync_at
    │ (if lock held by another tick: exit immediately)
    ↓
[parallel pollers — if ANY fails: release lock, abort, do NOT update last_sync_at]
    ├─ poll-harness-notion.py  → Kamil Harness DB (Notion) — assigned tickets + @tagged comments
    ├─ poll-eng-slack.py       → #engineering-* channels — @Kamil mentions (SLACK_USER_TOKEN)
    └─ poll-taleemabad-github.py → taleemabad-core PRs opened by agent branches (entity-filtered)
    ↓
[all pollers write to unified harness.db — INSERT OR IGNORE on deterministic event IDs]
    ↓
dispatch: group pending events by context_key → spawn subagents (one per context_key)
    ↓
sync-state: update last_sync_at → release tick lock
    ↓
[subagents run independently, in worktree at harness/workspace/]
```

---

## Unified Database Schema

**One database. One file. All scripts share it.**

`~/.kamil-harness/harness.db`  (persistent across reboots — not /tmp)

```sql
-- Tick coordination
CREATE TABLE IF NOT EXISTS sync_state (
    id TEXT PRIMARY KEY DEFAULT 'global',
    last_sync_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z'
);
INSERT OR IGNORE INTO sync_state (id) VALUES ('global');

CREATE TABLE IF NOT EXISTS tick_lock (
    id      TEXT PRIMARY KEY DEFAULT 'global',
    locked_at TEXT NOT NULL,
    locked_by TEXT NOT NULL  -- "poller-YYYYMMDDTHHMMSS-<pid>"
);

-- Event queue
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,   -- deterministic: "notion-<page_id>", "slack-<ch>-<ts>", "github-<repo>-<pr>-<type>"
    source      TEXT NOT NULL,      -- "notion" | "slack" | "github"
    type        TEXT NOT NULL,      -- see event type taxonomy below
    context_key TEXT NOT NULL,      -- ALWAYS a Notion ticket entity ID
    payload     TEXT NOT NULL,      -- raw JSON from source API
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | processing | done | ignored
    received_at TEXT NOT NULL,
    processed_at TEXT
);

-- Entity graph
CREATE TABLE IF NOT EXISTS entities (
    id          TEXT PRIMARY KEY,   -- internal UUID (uuidgen)
    source      TEXT NOT NULL,      -- "notion" | "slack" | "github"
    external_id TEXT NOT NULL,      -- Notion: page_id  Slack: channel/ts  GitHub: owner/repo#pr_num
    type        TEXT NOT NULL,      -- "ticket" | "thread" | "pr" | "comment"
    url         TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE(source, external_id)     -- prevents duplicate entity registration
);

CREATE TABLE IF NOT EXISTS links (
    entity_a     TEXT NOT NULL REFERENCES entities(id),
    entity_b     TEXT NOT NULL REFERENCES entities(id),
    relationship TEXT NOT NULL,     -- "originated_from" | "implements" | "discussed_in"
    created_at   TEXT NOT NULL,
    created_by   TEXT NOT NULL      -- session ID that created the link
);

-- Session tracking
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,   -- "session-<uuid>"
    context_key TEXT NOT NULL,      -- Notion ticket entity ID
    status      TEXT NOT NULL,      -- running | completed | cancelled
    intent      TEXT,               -- comma-separated event types that triggered this session
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
```

---

## Event Type Taxonomy

```
From Notion:
  ticket.created   → new ticket assigned to Kamil or matching filter
  comment.tagged   → comment on a Notion page containing @Kamil

From Slack:
  message.tagged   → @Kamil mention in an engineering channel

From GitHub:
  pr.review_commented  → review comment on an agent-opened PR
  pr.merged            → agent-opened PR was merged → set Notion ticket → Done
  pr.closed            → agent-opened PR was closed (not merged) → set ticket → Blocked
```

---

## Required Environment Variables

```
NOTION_API_KEY          — Notion integration token
NOTION_DATABASE_ID      — Kamil Harness DB page ID (see NOTION_HARNESS_DB_ID in ~/.agent-config.json)
NOTION_AGENT_USER_ID    — Kamil's Notion user ID (for assignee filter in poll-notion)
SLACK_BOT_TOKEN         — xoxb- token (for posting messages)
SLACK_USER_TOKEN        — xoxp- token (for search.messages API — bot token alone fails)
GITHUB_TOKEN            — Personal access token with repo scope
GITHUB_REPO             — "Orenda-Project/taleemabad-core"
GITHUB_AGENT_LOGIN      — GitHub username of the agent account
```

---

## Required Notion Database Properties

These columns must exist in the Kamil Harness Notion DB before the harness runs:

| Property | Type | Purpose |
|---|---|---|
| `Status` | Status | `Not started → In progress → Done / Blocked / In review / Cancelled` |
| `Agent Session ID` | Rich Text | Link back to session for debugging |
| `Last Agent Update` | Date | Human visibility of last agent action |
| `GitHub PR` | URL | Link to the PR opened for this ticket |
| `Slack Thread` | URL | Link to the originating Slack thread |

**Setup step:** Kamil verifies these exist before the first tick. If missing → post Slack DM to Kamal listing what to add → exit.

---

## Implementation Tasks (Correct Sequence)

### Task 8 — Shared kamil_notion.py Utility
**File:** `.claude/hooks/kamil_notion.py` (new)  
**Time:** 30 min  
**Do first** — Tasks 10 and 11 depend on it

**What:** Extract all direct Notion API calls (`urllib.request.urlopen`) into one shared utility with:
- 350ms inter-call delay (Notion = 3 req/sec; 350ms gives safety margin)
- Retry-once on 429 using `Retry-After` header
- Clean interface: `notion_request(req) → (status, body_bytes)`

```python
# ~/.claude/hooks/kamil_notion.py
import time, urllib.request, urllib.error

_last_call = 0.0

def notion_request(req: urllib.request.Request) -> tuple[int, bytes]:
    """Rate-limited (350ms) Notion request with one retry on 429."""
    global _last_call
    elapsed = time.time() - _last_call
    if elapsed < 0.35:
        time.sleep(0.35 - elapsed)
    _last_call = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(int(e.headers.get("Retry-After", "5")))
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, r.read()
        raise
```

**Wire into:** `stop-notion.py`, `beads-to-notion.py`, `notion-map-updater.py`, `kamil-notion-sink.py` — replace bare `urlopen(req)` calls with `notion_request(req)`.

**Verification:** `python3 -m py_compile kamil_notion.py` — no errors. Each consuming file imports cleanly.

---

### Task 9 — Unified Harness DB + Tick Lock
**File:** `.claude/hooks/kamil_harness_db.py` (new)  
**Time:** 30 min

**What:** One module that owns the unified harness.db. All other scripts import from it.

```python
# ~/.claude/hooks/kamil_harness_db.py
import sqlite3, os
from pathlib import Path

HARNESS_DB = Path.home() / ".kamil-harness" / "harness.db"

def get_db() -> sqlite3.Connection:
    HARNESS_DB.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(str(HARNESS_DB), check_same_thread=False)
    db.executescript(SCHEMA)  # idempotent CREATE IF NOT EXISTS
    return db

SCHEMA = """..."""  # full schema from above

def acquire_tick_lock(db: sqlite3.Connection, caller: str) -> bool:
    """Clear stale lock (>30min), attempt atomic acquire. Returns True if acquired."""
    db.execute(
        "DELETE FROM tick_lock WHERE id='global' "
        "AND (CAST(strftime('%s','now') AS INTEGER) "
        "   - CAST(strftime('%s', locked_at) AS INTEGER)) > 1800"
    )
    db.commit()
    lock_id = f"{caller}-{os.getpid()}"
    db.execute(
        "INSERT OR IGNORE INTO tick_lock (id, locked_at, locked_by) "
        "VALUES ('global', datetime('now'), ?)", (lock_id,)
    )
    db.commit()
    return db.execute("SELECT changes()").fetchone()[0] > 0

def release_tick_lock(db: sqlite3.Connection):
    db.execute("DELETE FROM tick_lock WHERE id='global'")
    db.commit()

def get_last_sync_at(db: sqlite3.Connection) -> str:
    return db.execute("SELECT last_sync_at FROM sync_state WHERE id='global'").fetchone()[0]

def set_last_sync_at(db: sqlite3.Connection, ts: str):
    db.execute("UPDATE sync_state SET last_sync_at=? WHERE id='global'", (ts,))
    db.commit()
```

**Wire into `slack-poller.py`:**
```python
from kamil_harness_db import get_db, acquire_tick_lock, release_tick_lock

def main():
    db = get_db()
    if not acquire_tick_lock(db, "slack-poller"):
        log("Tick already running — skipping")
        return 0
    try:
        ...  # existing logic unchanged
    finally:
        release_tick_lock(db)
        db.close()
```

**Verification:** Two simultaneous `slack-poller.py` runs → second exits "Tick already running". `ls ~/.kamil-harness/harness.db` → file exists with correct tables.

---

### Task 10 — Persistent Event Dedup in kamil-slack-listener.py
**File:** `.claude/hooks/kamil-slack-listener.py`  
**Time:** 30 min

**What:** Replace in-memory `_processed_event_ts = set()` with SQLite-backed dedup using the unified harness.db.

**Why deterministic key is `{channel}-{ts}`:** Slack `ts` is unique per channel but not globally. This matches harness-v2's `slack-CHANNEL-TS` format.

```python
from kamil_harness_db import get_db
import threading

_listener_db = None
_listener_db_lock = threading.Lock()

def _init_listener_db():
    global _listener_db
    _listener_db = get_db()  # shared harness.db — same file as poller

def _is_already_processed(channel: str, ts: str) -> bool:
    event_key = f"slack-{channel}-{ts}"
    with _listener_db_lock:
        try:
            _listener_db.execute(
                "INSERT OR IGNORE INTO events "
                "(id, source, type, context_key, payload, status, received_at) "
                "VALUES (?, 'slack', 'dedup_sentinel', 'pending', '{}', 'done', datetime('now'))",
                (event_key,)
            )
            _listener_db.commit()
            return _listener_db.execute("SELECT changes()").fetchone()[0] == 0
        except Exception:
            return False  # on DB error, allow processing
```

**Replace in `make_handler()`:**
```python
# Remove: if ts in _processed_event_ts / _processed_event_ts.add(ts) / .clear()
# Add:
if _is_already_processed(channel, ts):
    return
```

**Init in `main()`** before SocketModeClient creation:
```python
_init_listener_db()
```

**Verification:** Kill listener mid-session, send message, restart → message processed once. Check harness.db events table for the dedup_sentinel row.

---

### Task 11 — Notion Commit-Point Rule in stop-notion.py
**File:** `.claude/hooks/stop-notion.py`  
**Time:** 20 min

**What:** Wire in `kamil_notion.notion_request()` (from Task 8). Add commit-point comment documenting the Status-last rule for future UPDATE flows.

```python
# COMMIT-POINT RULE (harness-v2):
# For UPDATE flows: always write Status LAST. A successful Status write = work complete.
# This file only does CREATE (all-or-nothing) — rule applies when extending to updates.

from kamil_notion import notion_request
# Replace urllib.request.urlopen(req) → notion_request(req)
```

**Verification:** Trigger stop hook → Work Log entry appears in Notion.

---

### Task 12 — Team Orchestrator
**This is the major build. Implement after Tasks 8–11 are all done and stable.**

#### 12a — Orchestrator CLAUDE.md entry
Add to `personal-agent-v2/CLAUDE.md`:
```
/loop → orchestrator tick (270s):
  1. kamil_harness_db: acquire tick lock → read last_sync_at
  2. poll-harness-notion.py (if fails: release lock, abort)
  3. poll-eng-slack.py (if fails: release lock, abort)
  4. poll-taleemabad-github.py (if fails: release lock, abort)
  5. orchestrator-dispatch.py
  6. kamil_harness_db: set last_sync_at=now → release tick lock
```

#### 12b — poll-harness-notion.py

**Notion filter:**
```python
filter = {
    "and": [
        {"timestamp": "last_edited_time", "last_edited_time": {"after": last_sync_at}},
        {"or": [
            {"property": "Assignee", "people": {"contains": NOTION_AGENT_USER_ID}},
            {"property": "Status", "status": {"is_not_empty": True}}
        ]}
    ]
}
```

**For each page returned:**
1. `INSERT OR IGNORE` into entities `(source="notion", external_id=page_id, type="ticket")`
2. Fetch comments via `GET /comments?block_id=<page_id>` — filter `created_time > last_sync_at` AND text contains `@Kamil`
3. For each matching comment: `INSERT OR IGNORE INTO events (id="notion-comment-<comment_id>", type="comment.tagged", context_key=<notion_entity_id>)`
4. For new pages (entity didn't exist before): `INSERT OR IGNORE INTO events (id="notion-<page_id>", type="ticket.created", context_key=<notion_entity_id>)`
5. Add 350ms between all consecutive Notion API calls via `kamil_notion.notion_request()`

#### 12c — poll-eng-slack.py

**Requires:** `SLACK_USER_TOKEN` (not bot token) for `search.messages` API.

**Query:** `search.messages` with `query="@Kamil"`, `oldest=last_sync_at_as_ts`, channels filtered to engineering channels.

**For each message:**
1. Check if a Notion entity linked to this `channel/ts` already exists
   - **Yes (existing ticket):** `INSERT OR IGNORE INTO events (id="slack-<ch>-<ts>", type="message.tagged", context_key=<existing_notion_entity_id>)` — this is the Blocked-state resumption case
   - **No (new stub needed):** Create Notion stub ticket via `POST /pages` with title `"From Slack: <ISO timestamp>"`, Status=`Not started`, Slack Thread URL set. Then register Notion entity, Slack thread entity, link them with `originated_from`. Insert `message.tagged` event with the new Notion entity as context_key.

#### 12d — poll-taleemabad-github.py

**Only processes PRs that have an entity in harness.db.** Not all PRs — only agent-opened ones.

```python
# For each open PR on agent branches:
entity = db.execute(
    "SELECT id FROM entities WHERE source='github' AND external_id=?",
    (f"taleemabad-core#{pr_number}",)
).fetchone()
if not entity:
    continue  # not an agent-opened PR — skip
```

**Event types:**
- Review comment → `github-taleemabad-core-<pr>-comment-<comment_id>` / `pr.review_commented`
- Merged → `github-taleemabad-core-<pr>-merged` / `pr.merged`
- Closed (not merged) → `github-taleemabad-core-<pr>-closed` / `pr.closed`

#### 12e — orchestrator-dispatch.py (7 exact steps from harness-v2)

```
Step 1: SELECT DISTINCT context_key FROM events WHERE status='pending'
        Then: SELECT id, source, type, context_key, payload, received_at
              FROM events WHERE context_key=? AND status='pending'
        (NEVER GROUP_CONCAT — JSON payloads contain commas, breaks the concat)

Step 2: SELECT id FROM sessions WHERE context_key=? AND status='running'
        → if exists: skip this context_key

Step 3: Resolve rich context:
        a. Fetch Notion ticket: GET /pages/<external_id> via kamil_notion.notion_request()
        b. Fetch linked entities: SELECT e.* FROM entities e JOIN links l ON ...
           WHERE (l.entity_a=context_key OR l.entity_b=context_key) AND e.id != context_key
        c. If Slack entity linked: fetch last 10 messages from that thread
        d. If GitHub entity linked: fetch PR details + last 5 review comments
        e. Build available skills list from .claude/commands/ filenames

Step 4: INSERT INTO sessions (id, context_key, status, intent, created_at, updated_at)
        VALUES ('session-<uuid>', context_key, 'running', '<event_types>', now, now)

Step 5: UPDATE events SET status='processing'
        WHERE context_key=context_key AND status='pending'

Step 6: Spawn subagent via Agent tool with injected context prompt (see below)

Step 7: On subagent failure:
        UPDATE sessions SET status='cancelled', updated_at=now WHERE id=session_id
        UPDATE events SET status='pending'
        WHERE context_key=context_key AND status='processing'
```

**Subagent injected context:**
```
You are Kamil, Taleemabad's AI engineer. You have been spawned to handle work on:

NOTION TICKET:
<full ticket content and properties>

LINKED ENTITIES:
<Slack thread messages if any>
<GitHub PR details if any>

TRIGGERING EVENTS:
<list of event types that spawned this session>

AVAILABLE SKILLS:
<list of .claude/commands/ files>

WORKSPACE: harness/workspace/ (taleemabad-core checkout)

RULES:
1. For feature/implementation tasks: follow the plan-first flow (Step A then Step B)
2. Status=Done must be the LAST Notion update — it is the commit signal
3. Rate limit: 350ms between Notion API calls via kamil_notion.notion_request()
4. On completion: UPDATE sessions SET status='completed'; UPDATE events SET status='done'
```

#### 12f — Plan-first subagent flow (Step A / Step B)

This is non-negotiable. Subagents NEVER write code until a human approves a plan.

**Step A (triggered by ticket.created or message.tagged):**
1. Read source code in workspace to understand scope
2. Draft implementation plan + define E2E test cases
3. Post to Slack thread: "Here's my plan: [plan]. E2E tests I'll run: [cases]. Any questions? Reply `@Kamil go` to proceed."
4. Set Notion ticket Status → `Blocked`
5. `UPDATE sessions SET status='cancelled'` — session ends, waiting for human
6. `UPDATE events SET status='done'`

**Step B (triggered by `message.tagged` containing "go" in a Blocked ticket's thread):**
1. Read the plan from Slack thread history
2. Create branch: `agent/<ticket-slug>` in workspace
3. Implement per plan
4. Run E2E tests (see 12g)
5. If E2E passes: open PR → set Status=`Done` LAST
6. If E2E fails after 5 attempts: open PR with failing test report body → set Status=`Blocked` LAST → post Slack with screenshots

#### 12g — E2E Testing Gate (before any PR)

Adapted from harness-v2 `e2e-test.md`:

**Phase 1:** Start dev server in workspace (`make runserver` or `npm run dev`)
**Phase 2:** Run test cases defined in Step A plan via Chrome DevTools MCP (puppeteer tools)
**Phase 3:** Fix loop — up to 5 attempts. Each failure: diagnose, patch, re-run
**Phase 4:** Teardown dev server
**Phase 5:** Upload all screenshots (pass + fail) to Notion ticket as image blocks

**Outcome:**
- All pass → `gh pr create` → Status=`Done` LAST
- Still failing after 5 → `gh pr create --body "E2E FAILED: <cases>"` → Status=`Blocked` LAST → DM Kamal with screenshots

#### 12h — orchestrator.md Rule File

`.claude/rules/orchestrator.md` — loaded every session:
- Context key is ALWAYS a Notion ticket entity ID
- Status written LAST — it is the commit signal
- 350ms between Notion API calls (kamil_notion.notion_request)
- Deterministic event IDs — never invent random IDs
- Two-query pattern for events — never GROUP_CONCAT JSON
- Tick atomicity — if any poller fails, abort entire tick, do not update last_sync_at
- Plan-first for all implementation — Step A approval before Step B code
- E2E gate — no PR without running e2e tests

#### 12i — Workspace Setup

`harness/workspace/` = local checkout of taleemabad-core. Not committed to personal-agent-v2 repo. Subagents operate here. Setup step verifies it exists and is on `develop`.

---

## Implementation Sequence

```
Task 8  (30 min) → kamil_notion.py shared utility (all other tasks depend on this)
Task 9  (30 min) → kamil_harness_db.py unified schema + tick lock wired into slack-poller.py
Task 10 (30 min) → kamil-slack-listener.py persistent dedup using harness.db
Task 11 (20 min) → stop-notion.py: wire kamil_notion + commit-point comment
─── foundation stable ───
Task 12a (1 hr)  → Orchestrator CLAUDE.md + workspace setup
Task 12b (2 hr)  → poll-harness-notion.py
Task 12c (2 hr)  → poll-eng-slack.py (SLACK_USER_TOKEN required)
Task 12d (1 hr)  → poll-taleemabad-github.py (entity-filtered)
Task 12e (3 hr)  → orchestrator-dispatch.py (all 7 steps)
Task 12f (1 hr)  → Plan-first subagent flow (Step A/B)
Task 12g (2 hr)  → E2E testing gate
Task 12h (30min) → orchestrator.md rule file
Task 12i (1 hr)  → End-to-end test
```

**Foundation total:** ~2 hours  
**Orchestrator total:** ~1 full day

---

## Success Criteria

**Foundation done when:**
- [ ] `slack-poller.py`: two simultaneous runs → second exits "Tick already running"
- [ ] `kamil-slack-listener.py`: kill + restart → no duplicate processing (check harness.db)
- [ ] `stop-notion.py`: force 429 → retries once, Work Log still created
- [ ] All 4 Notion-calling hooks import and use `kamil_notion.notion_request()`

**Orchestrator done when:**
- [ ] Create Notion Harness ticket assigned to Kamil → Step A plan posted to Slack within 270s
- [ ] Reply `@Kamil go` → Step B implementation starts, branch created in workspace
- [ ] Subagent passes E2E → PR opened → Notion ticket Status = Done (last write)
- [ ] Subagent fails E2E → PR opened with failure report → Status = Blocked → Kamal DM'd
- [ ] @Kamil in #engineering-learning with no ticket → stub Notion ticket created → Step A posted
- [ ] Two simultaneous tickets → two separate sessions, no conflicts
- [ ] Any poller failure → tick aborts, last_sync_at unchanged, retries next tick
