# Plan: Apply orchestration-harness-v2 Learnings + Evolve Kamil into Team Orchestrator

**Date:** 2026-06-03  
**Source research:** https://github.com/Orenda-Project/orchestration-harness-v2  
**Owner:** Kamil  
**Status:** Approved — ready to implement

---

## Why This Plan Exists

After reviewing orchestration-harness-v2, we found 8 concrete patterns the Kamil agent is either missing or doing incorrectly. More importantly, the harness-v2 architecture — Notion+Slack+GitHub unified into one orchestration loop — is exactly what Kamil needs to become a **team orchestrator**, not just Kamal's personal agent.

This plan has two layers:
1. **Foundation fixes** (Tasks 8–11): Apply harness-v2 learnings to existing Kamil hooks
2. **Team orchestrator** (Task 12): Evolve Kamil into a system that coordinates work across the whole taleemabad engineering team

---

## NotebookLM Usage Policy (Updated)

NotebookLM is a **content and research tool**, not a knowledge base for engineering patterns.

| Use NLM for | Do NOT use NLM for |
|---|---|
| Content creation (scripts, posts, carousels) | Engineering Q&A |
| Internet research on a topic (fitness, niches, trends) | Pattern lookups from code repos |
| Podcast/slides/mindmap generation | Answering Slack engineering questions |
| Pre-researched topic deep-dives for content | Storing architectural knowledge |

**When Kamil gets an engineering question:** Read the actual source — the repo, the code, the docs — directly. Use `gh repo clone`, `Read`, `Grep`, `WebFetch`. Live source is always more accurate than a stale notebook copy.

**Task 7 is removed.** Creating a NotebookLM notebook from harness-v2 would add indirection and create a stale copy of living code. The harness-v2 repo IS the source. Kamil reads it directly when needed.

---

## Layer 1: Foundation Fixes

### Task 8 — Tick Lock in `slack-poller.py`
**File:** `.claude/hooks/slack-poller.py`  
**Time:** 30 min

**Problem (exact):** `main()` at line 477 has no re-entrancy guard. The cron runs every 30min. If a run takes >30min (slow Slack API, large inbox), two instances overlap → duplicate inbox items → duplicate DMs to Kamal → corrupted state file.

**Current code (broken):**
```python
def main():
    slack_cfg = load_config(SLACK_CONFIG)
    token = slack_cfg.get("SLACK_TOKEN")
    ...
    # no lock — just runs
```

**Fix (harness-v2 pattern):** SQLite tick lock in `/tmp/kamil-poller.db`

**Exact implementation:**

```python
import sqlite3

POLLER_DB = Path("/tmp/kamil-poller.db")

def _init_poller_db():
    db = sqlite3.connect(str(POLLER_DB))
    db.execute("""
        CREATE TABLE IF NOT EXISTS tick_lock (
            id TEXT PRIMARY KEY,
            locked_at TEXT NOT NULL,
            locked_by TEXT NOT NULL
        )
    """)
    db.commit()
    return db

def _acquire_tick_lock(db: sqlite3.Connection) -> bool:
    """Clear stale lock (>30min), then attempt atomic acquire. Returns True if acquired."""
    db.execute(
        "DELETE FROM tick_lock WHERE id='global' "
        "AND (CAST(strftime('%s','now') AS INTEGER) - CAST(strftime('%s', locked_at) AS INTEGER)) > 1800"
    )
    db.commit()
    lock_id = f"poller-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
    db.execute(
        "INSERT OR IGNORE INTO tick_lock (id, locked_at, locked_by) "
        "VALUES ('global', datetime('now'), ?)", (lock_id,)
    )
    db.commit()
    rows = db.execute("SELECT changes()").fetchone()[0]
    return rows > 0

def _release_tick_lock(db: sqlite3.Connection):
    db.execute("DELETE FROM tick_lock WHERE id='global'")
    db.commit()
```

**Wire into `main()`:**
```python
def main():
    db = _init_poller_db()
    if not _acquire_tick_lock(db):
        log("Tick already running — skipping this cron run")
        return 0
    try:
        # ... existing logic unchanged ...
    finally:
        _release_tick_lock(db)
        db.close()
```

**Verification:** Run two instances simultaneously → second exits immediately with "Tick already running"

---

### Task 9 — Persistent Event Dedup in `kamil-slack-listener.py`
**File:** `.claude/hooks/kamil-slack-listener.py`  
**Time:** 45 min

**Problem (exact):** Line 73: `_processed_event_ts = set()` — in-memory only. On restart (crash, deploy, manual kill), this set is empty. Any message that arrived in the 60s window before restart gets processed twice.

**Current code (broken):**
```python
_processed_event_ts = set()
...
if ts in _processed_event_ts:
    return
_processed_event_ts.add(ts)
if len(_processed_event_ts) > 1000:
    _processed_event_ts.clear()  # clears everything — risky
```

**Fix (harness-v2 deterministic ID pattern):** SQLite table in `/tmp/kamil-listener.db`

**Exact implementation:**

```python
LISTENER_DB = Path("/tmp/kamil-listener.db")

def _init_listener_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(LISTENER_DB), check_same_thread=False)
    db.execute("""
        CREATE TABLE IF NOT EXISTS processed_events (
            event_key TEXT PRIMARY KEY,        -- "{channel}-{ts}" deterministic
            processed_at TEXT NOT NULL
        )
    """)
    db.commit()
    return db

_listener_db: sqlite3.Connection | None = None
_listener_db_lock = threading.Lock()

def _is_already_processed(channel: str, ts: str) -> bool:
    """Returns True if this event was already handled. Inserts if not."""
    event_key = f"{channel}-{ts}"
    with _listener_db_lock:
        try:
            _listener_db.execute(
                "INSERT OR IGNORE INTO processed_events (event_key, processed_at) "
                "VALUES (?, datetime('now'))", (event_key,)
            )
            _listener_db.commit()
            rows = _listener_db.execute("SELECT changes()").fetchone()[0]
            # rows=0 means already existed → already processed
            if rows == 0:
                return True
            # Cap table at 2000 rows — delete oldest
            _listener_db.execute(
                "DELETE FROM processed_events WHERE event_key NOT IN "
                "(SELECT event_key FROM processed_events "
                " ORDER BY processed_at DESC LIMIT 2000)"
            )
            _listener_db.commit()
            return False
        except Exception:
            return False  # on db error, allow processing (safer than silent drop)
```

**Replace in `make_handler()`:**
```python
# OLD — remove these 4 lines:
if ts in _processed_event_ts:
    return
_processed_event_ts.add(ts)
if len(_processed_event_ts) > 1000:
    _processed_event_ts.clear()

# NEW — single call:
if _is_already_processed(channel, ts):
    return
```

**Init in `main()`** (before `SocketModeClient` is created):
```python
global _listener_db
_listener_db = _init_listener_db()
```

**Why deterministic key is `channel-ts`:** Slack `ts` is unique per channel but not globally. Combining channel+ts gives a globally unique event key — same pattern as harness-v2's `slack-CHANNEL-TS`.

**Verification:** Kill listener, send a message, restart listener → message processed exactly once, not twice. Check `/tmp/kamil-listener.db` shows the event_key row.

---

### Task 10 — Notion Commit-Point Ordering in `stop-notion.py`
**File:** `.claude/hooks/stop-notion.py`  
**Time:** 20 min

**Problem (exact):** `notion_create_page()` at line 41 sends all properties in one request. This is fine for CREATE (all-or-nothing). But the harness-v2 lesson applies to the broader pattern: if Kamil ever extends stop-notion to UPDATE existing pages, Status must be written LAST. Also: `notion_create_page()` currently has no retry on 429.

**Current code (missing retry):**
```python
def notion_create_page(api_key, db_id, properties, content=""):
    ...
    resp = urllib.request.urlopen(req)  # no retry on 429
```

**Fix — two changes:**

**Change 1:** Add `_notion_request()` wrapper with 429 retry + 350ms inter-call delay:
```python
import time as _time_module

_last_notion_call = 0.0

def _notion_request(req: urllib.request.Request) -> tuple[int, bytes]:
    """Execute a Notion API request. Respects 350ms rate limit. Retries once on 429."""
    global _last_notion_call
    # Rate limit: 350ms between calls
    elapsed = _time_module.time() - _last_notion_call
    if elapsed < 0.35:
        _time_module.sleep(0.35 - elapsed)
    _last_notion_call = _time_module.time()

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            retry_after = int(e.headers.get("Retry-After", "5"))
            _time_module.sleep(retry_after)
            # Retry once
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, r.read()
        raise
```

**Change 2:** Document the commit-point rule as a comment above `main()`:
```python
# COMMIT-POINT RULE (from orchestration-harness-v2):
# When updating an existing Notion page, always write Status LAST.
# A successful Status write = work is complete. If it fails, state is still correct.
# For CREATE flows (this file), all-or-nothing is fine — rule applies on future UPDATE flows.
```

**Verification:** Trigger a stop hook → check Notion Work Log was created. Force a 429 by rapid-firing → verify retry-once works.

---

### Task 11 — Audit All Direct Notion API Calls for Rate Limiting
**Files:** `stop-notion.py`, `beads-to-notion.py`, `notion-map-updater.py`, `kamil-notion-sink.py`  
**Time:** 30 min

**Problem:** Any hook making multiple sequential Notion API calls can hit the 3 req/sec limit, get a 429, and silently fail with no retry.

**Fix:** In each file, replace bare `urllib.request.urlopen(req)` calls with the `_notion_request()` pattern (350ms delay + retry-once on 429). Shared utility: extract to a tiny `kamil_notion.py` module in hooks/ so all files import one function.

**Exact new file `.claude/hooks/kamil_notion.py`:**
```python
"""Shared Notion API utility for all Kamil hooks."""
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

Each hook: `from kamil_notion import notion_request` → replace `urlopen(req)` → `notion_request(req)`.

**Verification:** `python3 -c "import ast; ast.parse(open('kamil_notion.py').read()); print('OK')"` for each edited file.

---

## Layer 2: Team Orchestrator (Task 12)

**This is the big one. It has its own sub-plan.**

### What "Team Orchestrator" Means

Right now Kamil responds to Kamal's DMs and @mentions. He is reactive and personal.

The harness-v2 shows what Kamil could be: an **autonomous team coordinator** that:
- Watches Notion Harness DB for tickets assigned to or tagged for Kamil
- Watches `#engineering-learning`, `#engineering-deployments`, `#engineering-qa` for @Kamil mentions
- Watches GitHub for PRs opened by the team on taleemabad-core
- Groups all these signals by Notion ticket (context_key)
- Spawns focused Claude subagents with full context: ticket content + linked Slack thread + linked PR
- Subagents implement, test, and open PRs autonomously
- Updates Notion ticket Status LAST as the commit signal
- Posts results to Slack thread

### Architecture

```
/loop 270s (kamil personal-agent-v2 CLAUDE.md)
    ↓
poll-harness-notion.py    → Kamil Harness DB tickets (assigned=Kamil, status=In Dev)
poll-eng-slack.py         → #engineering-* channels, @Kamil mentions
poll-taleemabad-github.py → taleemabad-core PRs on agent branches
    ↓
SQLite event queue (/tmp/kamil-orchestrator.db)
    events(id, source, type, context_key, payload, status, received_at)
    entities(id, source, external_id, type, url)
    links(entity_a, entity_b, relationship, created_by)
    sessions(id, context_key, status, intent, created_at)
    ↓
dispatch.py
    → group pending events by context_key (Notion ticket entity ID)
    → skip if session already running for context_key
    → resolve rich context:
        * Notion ticket content + properties
        * Linked Slack thread (last 10 messages)
        * Linked GitHub PR (if any)
        * Available skills list
    → spawn Claude subagent with injected context
    ↓
Subagent (taleemabad-core worktree)
    → reads context, reasons freely
    → implements feature (if ticket is a task)
    → opens PR, updates Notion ticket Status=Done LAST
    → posts result to Slack thread
```

### New Files

| File | Purpose |
|---|---|
| `.claude/hooks/kamil-orchestrator-db.py` | Init + helpers for orchestrator SQLite DB |
| `.claude/hooks/poll-harness-notion.py` | Poll Kamil Harness Notion DB for new/updated tickets |
| `.claude/hooks/poll-eng-slack.py` | Poll engineering Slack channels for @Kamil mentions |
| `.claude/hooks/poll-taleemabad-github.py` | Poll taleemabad-core GitHub PRs on agent branches |
| `.claude/hooks/orchestrator-dispatch.py` | Group events, spawn subagents with rich context |
| `.claude/rules/orchestrator.md` | Kamil orchestrator rules: context_key discipline, Status-last commit, 350ms Notion rate limit, deterministic event IDs |

### Key Design Decisions (from harness-v2 learnings)

1. **Context key is always Notion ticket entity ID** — never Slack thread or PR number
2. **Deterministic event IDs:** `notion-<page_id>`, `slack-<channel>-<ts>`, `github-taleemabad-core-<pr_num>`
3. **INSERT OR IGNORE** on events table → re-polling is always safe
4. **Two-query pattern:** never GROUP_CONCAT payloads → SELECT DISTINCT context_keys, then SELECT full rows per key
5. **Status written LAST** — successful Status=Done write is the commit signal
6. **Tick lock** — same pattern as Task 8, prevents re-entrant orchestrator runs
7. **Session = one per context_key at a time** — skip if `status='running'` session exists
8. **Slack creates stubs** — @Kamil mention in Slack with no Notion ticket → create stub ticket (`From Slack: <timestamp>`), agent enriches title as first action
9. **350ms Notion delay** — enforced via `kamil_notion.py` (from Task 11)
10. **Blocked state** — if subagent can't proceed, sets Status=Blocked, posts Slack explanation, cancels session. Next @Kamil reply restarts

### Sub-tasks for Task 12

```
12a — Create orchestrator SQLite DB schema + init script
12b — Write poll-harness-notion.py (Notion Harness DB poller)
12c — Write poll-eng-slack.py (engineering channel poller)
12d — Write poll-taleemabad-github.py (GitHub PR poller)
12e — Write orchestrator-dispatch.py (dispatcher + subagent spawner)
12f — Write orchestrator.md rule file
12g — Wire /loop in personal-agent-v2 CLAUDE.md
12h — End-to-end test: create Notion ticket → verify subagent spawns → verify Status updated
```

### What Changes for the Team

| Before | After |
|---|---|
| Team creates Notion ticket, manually assigns to a dev | Team creates ticket, assigns to Kamil → Kamil picks it up automatically |
| @Kamil on Slack → Kamal has to notice and tell Kamil | @Kamil on Slack → Kamil responds in thread automatically with research/code/answer |
| PR opened → sits until reviewed | Kamil watches for PR reviews on agent branches, resumes work if changes requested |
| Kamil is Kamal's personal tool | Kamil is the team's AI engineer |

---

## Implementation Sequence

```
Task 8  (30 min)  → Tick lock in slack-poller.py
Task 9  (45 min)  → Persistent dedup in kamil-slack-listener.py
Task 11 (30 min)  → kamil_notion.py shared utility + audit all hooks
Task 10 (20 min)  → Commit-point comment + retry in stop-notion.py (uses Task 11's utility)
Task 12 (separate session) → Full team orchestrator build
```

**Total for foundation fixes:** ~2 hours  
**Total for team orchestrator:** ~1 full day (planned separately)

---

## Success Criteria

**Foundation fixes done when:**
- [ ] `slack-poller.py`: two simultaneous runs → second exits "Tick already running"
- [ ] `kamil-slack-listener.py`: kill + restart → no duplicate message processing
- [ ] `stop-notion.py`: force 429 → retries once, succeeds
- [ ] `kamil_notion.py`: all 4 hook files import and use it

**Team orchestrator done when:**
- [ ] Create Notion Harness ticket assigned to Kamil → subagent spawns within 270s
- [ ] @Kamil in #engineering-learning → Kamil replies in thread automatically
- [ ] Subagent opens PR → Notion ticket Status = Done
- [ ] Two simultaneous tickets → two separate subagents, no conflicts
