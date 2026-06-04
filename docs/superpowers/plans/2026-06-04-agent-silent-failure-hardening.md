# Agent Silent Failure Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every task Kamil receives either visibly delivered or visibly failed — no silent drops, no invisible partial completions — by adding a job state machine, suppression event registry, full thread context enrichment, and multi-step milestone logging.

**Architecture:** Four layers wired into the existing harness: (1) `jobs` + `suppression_log` SQLite tables added to `kamil_context.py`; (2) `klog_suppression()` and `klog_milestone()` added to `kamil_log.py`; (3) `fetch_thread_context()` and `extract_pr_url()` added to `kamil_context.py` and wired into the Slack listener's dispatch path; (4) `tracked_thread()` wrapper replaces fire-and-forget daemon threads, milestone logging added to content pipeline and PR review handler.

**Tech Stack:** Python 3.10+, SQLite3 (stdlib), existing `kamil_log.py` (Axiom sink), existing `slack_sdk.WebClient`, existing `kamil_context.py` (harness DB).

**Spec:** `docs/superpowers/specs/2026-06-04-agent-silent-failure-hardening.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `.claude/hooks/kamil_context.py` | **Modify** | Add `jobs` table, `suppression_log` table, `klog_suppression()`, `klog_milestone()`, `fetch_thread_context()`, `extract_pr_url()`, `tracked_thread()`, `stale_job_checker()`, job state helpers |
| `.claude/hooks/kamil_log.py` | **Modify** | Add `klog_suppression()` and `klog_milestone()` event emitters |
| `.claude/hooks/kamil-slack-listener.py` | **Modify** | Wire job state machine into `dispatch()` and `handle_message()`; wire `fetch_thread_context()`; wire PR URL extraction; replace daemon thread with `tracked_thread()`; add milestone logs to content pipeline |
| `tests/test_silent_failure.py` | **Create** | Unit tests for all new functions |

---

## Task 1: Add jobs + suppression_log tables to SQLite schema

**Files:**
- Modify: `.claude/hooks/kamil_context.py`
- Modify: `tests/test_kamil_context.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_kamil_context.py`:

```python
def test_jobs_table_exists():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    import kamil_context as kc
    kc.HARNESS_DB = path
    kc.init_schema()
    import sqlite3
    conn = sqlite3.connect(path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert 'jobs' in tables
    assert 'suppression_log' in tables

def test_suppression_log_table_exists():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    import kamil_context as kc
    kc.HARNESS_DB = path
    kc.init_schema()
    import sqlite3
    conn = sqlite3.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(suppression_log)").fetchall()}
    conn.close()
    assert 'reason_code' in cols
    assert 'event_id' in cols
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m pytest tests/test_kamil_context.py::test_jobs_table_exists -v
```
Expected: `AssertionError: assert 'jobs' in {...}`

- [ ] **Step 3: Add tables to `_SCHEMA` in `kamil_context.py`**

Find the `_SCHEMA` string in `.claude/hooks/kamil_context.py` and append these two table definitions before the closing triple-quote:

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id             TEXT PRIMARY KEY,
    event_id       TEXT NOT NULL,
    source         TEXT NOT NULL,
    intent         TEXT,
    raw_text       TEXT,
    channel        TEXT,
    thread_ts      TEXT,
    sender_id      TEXT,
    status         TEXT NOT NULL DEFAULT 'received',
    failure_reason TEXT,
    steps_total    INTEGER DEFAULT 1,
    steps_done     INTEGER DEFAULT 0,
    created_at     INTEGER NOT NULL,
    updated_at     INTEGER NOT NULL,
    delivered_at   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_event  ON jobs(event_id);
CREATE TABLE IF NOT EXISTS suppression_log (
    id          TEXT PRIMARY KEY,
    event_id    TEXT,
    reason_code TEXT NOT NULL,
    raw_text    TEXT,
    channel     TEXT,
    sender_id   TEXT,
    job_id      TEXT,
    details     TEXT,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_suppression_event  ON suppression_log(event_id);
CREATE INDEX IF NOT EXISTS idx_suppression_reason ON suppression_log(reason_code, created_at);
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python3 -m pytest tests/test_kamil_context.py -v
```
Expected: all existing tests + 2 new ones pass.

- [ ] **Step 5: Apply schema to real DB**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "
import sys; sys.path.insert(0, '.claude/hooks')
import kamil_context as kc
kc.init_schema()
import sqlite3
conn = sqlite3.connect(kc.HARNESS_DB)
tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
print('Tables:', tables)
conn.close()
"
```
Expected: output includes `jobs` and `suppression_log`.

- [ ] **Step 6: Commit**

```bash
git add .claude/hooks/kamil_context.py tests/test_kamil_context.py
git commit -m "feat: add jobs and suppression_log tables to harness schema"
```

---

## Task 2: Job state helpers in `kamil_context.py`

**Files:**
- Modify: `.claude/hooks/kamil_context.py`
- Create: `tests/test_silent_failure.py`

- [ ] **Step 1: Create test file and write failing tests**

Create `tests/test_silent_failure.py`:

```python
import sqlite3, os, sys, tempfile, json, time, uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '.claude', 'hooks'))

def make_test_db():
    import kamil_context as kc
    f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    kc.HARNESS_DB = f.name
    kc.init_schema()
    return f.name

def test_create_job_returns_id():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    job_id = kc.create_job(
        event_id='evt_001',
        source='slack_mention',
        intent='pr_review',
        raw_text='review this PR',
        channel='C01',
        thread_ts='123.456',
        sender_id='U01',
    )
    assert job_id is not None
    assert len(job_id) == 64  # sha256 hex

def test_create_job_idempotent():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    id1 = kc.create_job(event_id='evt_002', source='slack_mention')
    id2 = kc.create_job(event_id='evt_002', source='slack_mention')
    assert id1 == id2

def test_mark_job_delivered():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    job_id = kc.create_job(event_id='evt_003', source='slack_mention')
    kc.mark_job_delivered(job_id)
    conn = sqlite3.connect(kc.HARNESS_DB)
    row = conn.execute("SELECT status, delivered_at FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    assert row[0] == 'delivered'
    assert row[1] is not None

def test_mark_job_failed():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    job_id = kc.create_job(event_id='evt_004', source='slack_mention')
    kc.mark_job_failed(job_id, 'no_url_in_context')
    conn = sqlite3.connect(kc.HARNESS_DB)
    row = conn.execute("SELECT status, failure_reason FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    assert row[0] == 'failed'
    assert row[1] == 'no_url_in_context'

def test_get_stale_jobs():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    job_id = kc.create_job(event_id='evt_005', source='slack_mention')
    # backdate created_at to simulate stale
    conn = sqlite3.connect(kc.HARNESS_DB)
    conn.execute("UPDATE jobs SET status='processing', created_at=? WHERE id=?",
                 (int(time.time()) - 400, job_id))
    conn.commit()
    conn.close()
    stale = kc.get_stale_jobs(threshold_seconds=300)
    assert any(j['id'] == job_id for j in stale)
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_silent_failure.py -v 2>&1 | head -20
```
Expected: `AttributeError: module 'kamil_context' has no attribute 'create_job'`

- [ ] **Step 3: Add job state helpers to `kamil_context.py`**

Append after `run_sync_loop`:

```python
# ── Job State Machine ──────────────────────────────────────────────────────────

def create_job(
    event_id: str,
    source: str,
    intent: str = None,
    raw_text: str = "",
    channel: str = "",
    thread_ts: str = "",
    sender_id: str = "",
    steps_total: int = 1,
) -> str:
    """
    Create a job row for an inbound event. Idempotent — same event_id returns same job_id.
    Returns job_id (sha256 of source:event_id).
    """
    job_id = hashlib.sha256(f"{source}:{event_id}".encode()).hexdigest()
    now = int(time.time())
    c = _conn()
    try:
        c.execute(
            """INSERT OR IGNORE INTO jobs
               (id, event_id, source, intent, raw_text, channel, thread_ts, sender_id,
                status, steps_total, steps_done, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,'received',?,0,?,?)""",
            (job_id, event_id, source, intent, raw_text, channel, thread_ts, sender_id,
             steps_total, now, now)
        )
        c.commit()
    finally:
        c.close()
    return job_id

def mark_job_processing(job_id: str) -> None:
    now = int(time.time())
    c = _conn()
    try:
        c.execute("UPDATE jobs SET status='processing', updated_at=? WHERE id=?", (now, job_id))
        c.commit()
    finally:
        c.close()

def mark_job_delivered(job_id: str) -> None:
    now = int(time.time())
    c = _conn()
    try:
        c.execute(
            "UPDATE jobs SET status='delivered', delivered_at=?, updated_at=? WHERE id=?",
            (now, now, job_id)
        )
        c.commit()
    finally:
        c.close()

def mark_job_failed(job_id: str, reason: str) -> None:
    now = int(time.time())
    c = _conn()
    try:
        c.execute(
            "UPDATE jobs SET status='failed', failure_reason=?, updated_at=? WHERE id=?",
            (reason, now, job_id)
        )
        c.commit()
    finally:
        c.close()

def get_stale_jobs(threshold_seconds: int = 300) -> list:
    """Return jobs stuck in 'processing' for longer than threshold_seconds."""
    cutoff = int(time.time()) - threshold_seconds
    c = _conn()
    try:
        rows = c.execute(
            "SELECT id, event_id, source, intent, raw_text, channel, thread_ts, created_at "
            "FROM jobs WHERE status='processing' AND created_at < ?",
            (cutoff,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python3 -m pytest tests/test_silent_failure.py -v
```
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks/kamil_context.py tests/test_silent_failure.py
git commit -m "feat: add job state machine helpers to kamil_context"
```

---

## Task 3: `klog_suppression()` and `klog_milestone()` in `kamil_log.py` + `kamil_context.py`

**Files:**
- Modify: `.claude/hooks/kamil_log.py`
- Modify: `.claude/hooks/kamil_context.py`
- Modify: `tests/test_silent_failure.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_silent_failure.py`:

```python
def test_log_suppression_writes_to_db():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    kc.log_suppression(
        event_id='evt_sup_001',
        reason_code='no_url_in_context',
        raw_text='review this PR',
        channel='C01',
        sender_id='U01',
    )
    conn = sqlite3.connect(kc.HARNESS_DB)
    row = conn.execute(
        "SELECT reason_code FROM suppression_log WHERE event_id='evt_sup_001'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 'no_url_in_context'

def test_log_milestone_updates_steps_done():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    job_id = kc.create_job(event_id='evt_ms_001', source='slack_mention', steps_total=3)
    kc.log_milestone(job_id, 'fetch_thread', 1, 3, 'completed')
    conn = sqlite3.connect(kc.HARNESS_DB)
    row = conn.execute("SELECT steps_done FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    assert row[0] == 1
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_silent_failure.py::test_log_suppression_writes_to_db -v
```
Expected: `AttributeError: module 'kamil_context' has no attribute 'log_suppression'`

- [ ] **Step 3: Add `klog_suppression` and `klog_milestone` to `kamil_log.py`**

Append before the final `def klog(event, **fields)` function:

```python
def klog_suppression(
    event_id: str,
    reason_code: str,
    raw_text: str = "",
    channel: str = "",
    sender_id: str = "",
    job_id: str = "",
    details: str = "",
) -> None:
    """Log a suppressed/dropped inbound message event."""
    klog(
        "suppression",
        component="listener",
        event_id=event_id,
        reason_code=reason_code,
        raw_text=raw_text[:200],
        channel=channel,
        sender_id=sender_id,
        job_id=job_id,
        details=details[:500],
        severity="WARNING",
    )

def klog_milestone(
    job_id: str,
    step_name: str,
    step_index: int,
    total_steps: int,
    status: str,
    details: str = "",
) -> None:
    """Log a step milestone for a multi-step job."""
    klog(
        "milestone",
        component="listener",
        job_id=job_id,
        step_name=step_name,
        step_index=step_index,
        total_steps=total_steps,
        status=status,
        details=details[:500],
        severity="INFO",
    )
```

- [ ] **Step 4: Add `log_suppression` and `log_milestone` to `kamil_context.py`**

Append after `get_stale_jobs`:

```python
# ── Suppression + Milestone logging ────────────────────────────────────────────

def log_suppression(
    event_id: str,
    reason_code: str,
    raw_text: str = "",
    channel: str = "",
    sender_id: str = "",
    job_id: str = "",
    details: str = "",
) -> None:
    """
    Record a suppressed/dropped inbound message.
    Writes to SQLite suppression_log + Axiom via kamil_log.
    Never raises.
    """
    import sys
    row_id = hashlib.sha256(f"{event_id}:{reason_code}:{int(time.time())}".encode()).hexdigest()
    now = int(time.time())
    try:
        c = _conn()
        try:
            c.execute(
                "INSERT OR IGNORE INTO suppression_log "
                "(id, event_id, reason_code, raw_text, channel, sender_id, job_id, details, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (row_id, event_id, reason_code, raw_text[:500], channel,
                 sender_id, job_id, details[:500], now)
            )
            c.commit()
        finally:
            c.close()
    except Exception as e:
        print(f"[log_suppression] DB write failed: {e}", file=sys.stderr)
    try:
        from kamil_log import klog_suppression as _klog_sup
        _klog_sup(
            event_id=event_id,
            reason_code=reason_code,
            raw_text=raw_text,
            channel=channel,
            sender_id=sender_id,
            job_id=job_id,
            details=details,
        )
    except Exception as e:
        print(f"[log_suppression] Axiom write failed: {e}", file=sys.stderr)

def log_milestone(
    job_id: str,
    step_name: str,
    step_index: int,
    total_steps: int,
    status: str,
    details: str = "",
) -> None:
    """
    Log a step milestone and update steps_done in the jobs table.
    Never raises.
    """
    import sys
    try:
        c = _conn()
        try:
            if status == 'completed':
                c.execute(
                    "UPDATE jobs SET steps_done=steps_done+1, updated_at=? WHERE id=?",
                    (int(time.time()), job_id)
                )
                c.commit()
        finally:
            c.close()
    except Exception as e:
        print(f"[log_milestone] DB write failed: {e}", file=sys.stderr)
    try:
        from kamil_log import klog_milestone as _klog_ms
        _klog_ms(job_id=job_id, step_name=step_name,
                 step_index=step_index, total_steps=total_steps,
                 status=status, details=details)
    except Exception as e:
        print(f"[log_milestone] Axiom write failed: {e}", file=sys.stderr)
```

- [ ] **Step 5: Run all tests**

```bash
python3 -m pytest tests/test_silent_failure.py tests/test_kamil_context.py -v
```
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add .claude/hooks/kamil_context.py .claude/hooks/kamil_log.py tests/test_silent_failure.py
git commit -m "feat: add log_suppression() and log_milestone() to kamil_context and kamil_log"
```

---

## Task 4: `fetch_thread_context()` and `extract_pr_url()` in `kamil_context.py`

**Files:**
- Modify: `.claude/hooks/kamil_context.py`
- Modify: `tests/test_silent_failure.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_silent_failure.py`:

```python
def test_extract_pr_url_from_trigger():
    import kamil_context as kc
    url = kc.extract_pr_url(
        trigger_text='please review https://github.com/Orenda-Project/taleemabad-core/pull/5151',
        thread_context=''
    )
    assert url == 'https://github.com/Orenda-Project/taleemabad-core/pull/5151'

def test_extract_pr_url_from_thread():
    import kamil_context as kc
    url = kc.extract_pr_url(
        trigger_text='@Kamil review this PR',
        thread_context='[123.456] <U01>: https://github.com/Orenda-Project/taleemabad-core/pull/5151\n@channel Please review.'
    )
    assert url == 'https://github.com/Orenda-Project/taleemabad-core/pull/5151'

def test_extract_pr_url_returns_none_when_missing():
    import kamil_context as kc
    url = kc.extract_pr_url(trigger_text='review this', thread_context='no url here')
    assert url is None

def test_fetch_thread_context_returns_empty_on_failure():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    # Pass a mock web client that raises
    class FakeWeb:
        def conversations_replies(self, **kwargs):
            raise Exception("Network error")
    result = kc.fetch_thread_context('C01', '123.456', FakeWeb(), event_id='evt_ft_001')
    assert result == ''  # never raises, returns empty string
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_silent_failure.py::test_extract_pr_url_from_trigger -v
```
Expected: `AttributeError: module 'kamil_context' has no attribute 'extract_pr_url'`

- [ ] **Step 3: Add functions to `kamil_context.py`**

Append after `log_milestone`:

```python
# ── Thread context enrichment ──────────────────────────────────────────────────

def fetch_thread_context(
    channel: str,
    thread_ts: str,
    web,                    # slack_sdk.WebClient
    event_id: str = "",
    sender_id: str = "",
) -> str:
    """
    Fetch the full Slack thread via conversations.replies.
    Returns a formatted string for injection into Claude prompts.
    On failure: logs suppression event and returns "" — never raises.
    """
    import sys
    try:
        resp = web.conversations_replies(channel=channel, ts=thread_ts, limit=50)
        messages = resp.get("messages", [])
        lines = []
        for m in messages:
            user = m.get("user", "unknown")
            text = m.get("text", "")
            ts   = m.get("ts", "")
            lines.append(f"[{ts}] <{user}>: {text}")
        return "\n".join(lines)
    except Exception as e:
        log_suppression(
            event_id=event_id or thread_ts,
            reason_code="thread_fetch_failed",
            raw_text="",
            channel=channel,
            sender_id=sender_id,
            details=str(e),
        )
        return ""

def extract_pr_url(trigger_text: str, thread_context: str) -> Optional[str]:
    """
    Search for a GitHub PR URL in trigger text first, then full thread.
    Returns the first match or None.
    """
    import re
    pattern = r'https://github\.com/[^\s>)"<]+'
    for text in [trigger_text, thread_context]:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python3 -m pytest tests/test_silent_failure.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks/kamil_context.py tests/test_silent_failure.py
git commit -m "feat: add fetch_thread_context() and extract_pr_url() to kamil_context"
```

---

## Task 5: `tracked_thread()` helper in `kamil_context.py`

**Files:**
- Modify: `.claude/hooks/kamil_context.py`
- Modify: `tests/test_silent_failure.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_silent_failure.py`:

```python
def test_tracked_thread_marks_delivered():
    import kamil_context as kc, time as _time
    kc.HARNESS_DB = make_test_db()
    job_id = kc.create_job(event_id='evt_tt_001', source='slack_mention')
    results = []
    def _work():
        results.append('done')
    t = kc.tracked_thread(job_id, _work)
    t.join(timeout=3)
    assert 'done' in results
    conn = sqlite3.connect(kc.HARNESS_DB)
    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    assert row[0] == 'delivered'

def test_tracked_thread_marks_failed_on_exception():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    job_id = kc.create_job(event_id='evt_tt_002', source='slack_mention')
    def _work():
        raise ValueError("boom")
    t = kc.tracked_thread(job_id, _work)
    t.join(timeout=3)
    conn = sqlite3.connect(kc.HARNESS_DB)
    row = conn.execute("SELECT status, failure_reason FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    assert row[0] == 'failed'
    assert 'boom' in row[1]
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_silent_failure.py::test_tracked_thread_marks_delivered -v
```
Expected: `AttributeError: module 'kamil_context' has no attribute 'tracked_thread'`

- [ ] **Step 3: Add `tracked_thread()` to `kamil_context.py`**

Append after `extract_pr_url`:

```python
# ── Tracked thread wrapper ─────────────────────────────────────────────────────

def tracked_thread(job_id: str, fn, *args, **kwargs):
    """
    Run fn(*args, **kwargs) in a daemon thread.
    On success: marks job delivered.
    On exception: marks job failed, logs error to Axiom.
    Returns the Thread object (already started).
    """
    import threading, sys

    def _run():
        try:
            fn(*args, **kwargs)
            mark_job_delivered(job_id)
        except Exception as e:
            mark_job_failed(job_id, str(e))
            try:
                from kamil_log import klog_error
                klog_error("tracked_thread", e, component="listener", severity="ERROR")
            except Exception:
                print(f"[tracked_thread] job={job_id} failed: {e}", file=sys.stderr)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t
```

- [ ] **Step 4: Run all tests**

```bash
python3 -m pytest tests/test_silent_failure.py tests/test_kamil_context.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks/kamil_context.py tests/test_silent_failure.py
git commit -m "feat: add tracked_thread() wrapper to kamil_context"
```

---

## Task 6: Wire job state machine + suppression into `dispatch()` in the Slack listener

**Files:**
- Modify: `.claude/hooks/kamil-slack-listener.py`

The `dispatch()` function is at approximately line 747. It currently logs receipt via `log(f"[{source}] {clean[:80]}")` and silently drops empty messages. We add: job creation on entry, suppression log for empty/filtered messages, `mark_job_processing()` before submitting to executor.

- [ ] **Step 1: Read the current dispatch() function**

```bash
sed -n '747,810p' /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-slack-listener.py
```

- [ ] **Step 2: Add import guard for new kamil_context functions**

Find the existing `try: from kamil_context import ...` block (around line 60) and add the new symbols:

```python
try:
    from kamil_context import (
        resolve_person, record_interaction, run_sync_loop,
        PersonNotFound, PersonAmbiguous,
        create_job, mark_job_processing, mark_job_delivered, mark_job_failed,
        log_suppression, log_milestone, fetch_thread_context, extract_pr_url,
        tracked_thread,
    )
    _context_available = True
except Exception:
    _context_available = False
```

- [ ] **Step 3: Wire job creation into `dispatch()`**

Find this block in `dispatch()`:

```python
    clean = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    if not clean:
        return
```

Replace with:

```python
    clean = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    if not clean:
        if _context_available:
            log_suppression(
                event_id=thread_ts or "",
                reason_code="empty_after_strip",
                raw_text=text[:200],
                channel=channel,
                sender_id=sender_id or "",
            )
        return

    # Create job row for this inbound event
    job_id = ""
    if _context_available:
        job_id = create_job(
            event_id=f"{channel}_{thread_ts}",
            source=source,
            raw_text=clean,
            channel=channel,
            thread_ts=thread_ts,
            sender_id=sender_id or "",
        )
```

- [ ] **Step 4: Wire `mark_job_processing` before executor submit**

Find the line:

```python
    _MSG_EXECUTOR.submit(
        handle_message,
        clean, thread_history, web, channel, thread_ts, source,
        sender_id, sender_name, is_third_party, is_dm,
    )
```

Replace with:

```python
    if _context_available and job_id:
        mark_job_processing(job_id)
    _MSG_EXECUTOR.submit(
        handle_message,
        clean, thread_history, web, channel, thread_ts, source,
        sender_id, sender_name, is_third_party, is_dm, job_id,
    )
```

- [ ] **Step 5: Wire `mark_job_delivered` after `chat_postMessage` in `handle_message()`**

`handle_message()` now receives `job_id` as a new last parameter. Find the function signature (around line 435):

```python
def handle_message(text: str, thread_history: str, web: WebClient, channel: str,
```

Add `job_id: str = ""` as the last parameter.

Then find the primary `web.chat_postMessage(**reply_kwargs)` call (around line 598) and add immediately after:

```python
    # Mark job delivered AFTER successful send — never before
    if _context_available and job_id:
        mark_job_delivered(job_id)
```

- [ ] **Step 6: Verify the listener imports without error**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "
import sys; sys.path.insert(0, '.claude/hooks')
from kamil_context import create_job, mark_job_processing, mark_job_delivered, mark_job_failed, log_suppression, log_milestone, fetch_thread_context, extract_pr_url, tracked_thread
print('all imports OK')
"
```

- [ ] **Step 7: Commit**

```bash
git add .claude/hooks/kamil-slack-listener.py
git commit -m "feat: wire job state machine and suppression logging into dispatch() and handle_message()"
```

---

## Task 7: Wire full thread context + PR URL extraction into `handle_message()`

**Files:**
- Modify: `.claude/hooks/kamil-slack-listener.py`

- [ ] **Step 1: Replace `thread_history` fetch with `fetch_thread_context()`**

In `dispatch()`, find:

```python
    thread_history = fetch_thread_history(web, channel, thread_ts, is_dm=is_dm, bot_token=bot_token)
```

Replace with:

```python
    if _context_available:
        thread_history = fetch_thread_context(
            channel=channel,
            thread_ts=thread_ts,
            web=web,
            event_id=f"{channel}_{thread_ts}",
            sender_id=sender_id or "",
        )
    else:
        thread_history = fetch_thread_history(web, channel, thread_ts, is_dm=is_dm, bot_token=bot_token)
```

- [ ] **Step 2: Add PR URL extraction to the PR review intent path**

In `handle_message()`, find the intent detection block (around line 480 where `mode` is set). After mode is detected as `pr_review` (search for `pr_review` or the PR review condition), add:

```python
    # For PR review intent: extract URL from trigger or full thread
    pr_url = None
    if mode == 'pr_review' and _context_available:
        pr_url = extract_pr_url(trigger_text=text, thread_context=thread_history or "")
        if pr_url is None:
            # Can't review without a URL — log suppression and ask user
            log_suppression(
                event_id=f"{channel}_{thread_ts}",
                reason_code="no_url_in_context",
                raw_text=text[:200],
                channel=channel,
                sender_id=sender_id or "",
                job_id=job_id,
                details="PR review requested but no GitHub URL found in trigger or thread",
            )
            reply_kwargs = {
                "channel": channel,
                "text": "I couldn't find a PR URL in this thread — can you share the link? 🤖 Kamil",
                "thread_ts": thread_ts,
            }
            web.chat_postMessage(**reply_kwargs)
            if _context_available and job_id:
                mark_job_failed(job_id, "no_url_in_context")
            return
```

- [ ] **Step 3: Inject thread history into Claude prompt**

The existing prompt already has `{thread_history or "(no prior messages)"}`. With `fetch_thread_context()` now providing full thread content (including the original thread messages), this section automatically gets richer context. No prompt change needed.

- [ ] **Step 4: Smoke test — simulate the exact failure scenario**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "
import sys; sys.path.insert(0, '.claude/hooks')
import kamil_context as kc
kc.HARNESS_DB = '/home/oye/.kamil-harness/harness.db'

# Simulate: trigger has no URL, thread has URL
url = kc.extract_pr_url(
    trigger_text='@Kamil review this PR',
    thread_context='[123.456] <U_hammad>: https://github.com/Orenda-Project/taleemabad-core/pull/5151\n@channel Please review.'
)
print('Extracted URL:', url)
assert url == 'https://github.com/Orenda-Project/taleemabad-core/pull/5151'
print('Test passed — PR URL correctly extracted from thread context')
"
```
Expected: `Extracted URL: https://github.com/Orenda-Project/taleemabad-core/pull/5151`

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks/kamil-slack-listener.py
git commit -m "feat: wire fetch_thread_context and extract_pr_url into dispatch and handle_message"
```

---

## Task 8: Replace NLM daemon thread with `tracked_thread()`

**Files:**
- Modify: `.claude/hooks/kamil-slack-listener.py`

- [ ] **Step 1: Find the NLM daemon thread in `dispatch()`**

```bash
grep -n "threading.Thread" /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-slack-listener.py
```

- [ ] **Step 2: Replace with `tracked_thread()`**

Find this block in `dispatch()`:

```python
        threading.Thread(
            target=nlm_handle,
            args=(clean, bot_token_cfg),
            daemon=True,
        ).start()
        return
```

Replace with:

```python
        if _context_available and job_id:
            tracked_thread(job_id, nlm_handle, clean, bot_token_cfg)
        else:
            threading.Thread(target=nlm_handle, args=(clean, bot_token_cfg), daemon=True).start()
        return
```

- [ ] **Step 3: Verify imports work**

```bash
python3 -c "
import sys; sys.path.insert(0, '.claude/hooks')
from kamil_context import tracked_thread
print('tracked_thread import OK')
"
```

- [ ] **Step 4: Commit**

```bash
git add .claude/hooks/kamil-slack-listener.py
git commit -m "feat: replace NLM fire-and-forget thread with tracked_thread()"
```

---

## Task 9: Add milestone logging to content pipeline

**Files:**
- Modify: `.claude/hooks/kamil-slack-listener.py`

The `_maybe_run_daily_content()` function currently logs only step 1 (spawn) and step 8 (LinkedIn). Steps 2–7 are invisible.

- [ ] **Step 1: Find the pipeline**

```bash
grep -n "_maybe_run_daily_content\|content pipeline\|LinkedIn auto-post" /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-slack-listener.py | head -20
```

- [ ] **Step 2: Read the full function**

```bash
sed -n '807,920p' /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-slack-listener.py
```

- [ ] **Step 3: Add a pipeline job_id and milestone logging**

At the top of `_maybe_run_daily_content()`, after confirming it hasn't run today, add:

```python
    pipeline_job_id = ""
    if _context_available:
        pipeline_job_id = create_job(
            event_id=f"daily_content_{datetime.datetime.now().strftime('%Y-%m-%d')}",
            source='cron',
            intent='content_pipeline',
            steps_total=8,
        )
        mark_job_processing(pipeline_job_id)
```

Then find each substantive step in the pipeline and add a `log_milestone()` call. For example, before the subprocess spawn for content generation:

```python
    if _context_available and pipeline_job_id:
        log_milestone(pipeline_job_id, 'spawn_content_process', 1, 8, 'completed')
```

After LinkedIn post succeeds:

```python
    if _context_available and pipeline_job_id:
        log_milestone(pipeline_job_id, 'linkedin_post', 8, 8, 'completed')
        mark_job_delivered(pipeline_job_id)
```

If the pipeline fails at any point, add in the exception handler:

```python
    if _context_available and pipeline_job_id:
        log_milestone(pipeline_job_id, step_name, step_index, 8, 'failed', details=str(e))
        mark_job_failed(pipeline_job_id, str(e))
```

- [ ] **Step 4: Verify the listener starts cleanly**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "
import sys; sys.path.insert(0, '.claude/hooks')
# Check all imports resolve without running the server
import ast
src = open('.claude/hooks/kamil-slack-listener.py').read()
ast.parse(src)
print('Syntax OK')
"
```
Expected: `Syntax OK`

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks/kamil-slack-listener.py
git commit -m "feat: add milestone logging to daily content pipeline"
```

---

## Task 10: Stale job checker — background thread

**Files:**
- Modify: `.claude/hooks/kamil-slack-listener.py`
- Modify: `tests/test_silent_failure.py`

- [ ] **Step 1: Write failing test for stale checker**

Append to `tests/test_silent_failure.py`:

```python
def test_stale_job_checker_marks_timed_out():
    import kamil_context as kc, time as _t, sqlite3
    kc.HARNESS_DB = make_test_db()
    job_id = kc.create_job(event_id='evt_stale_001', source='slack_mention')
    # Manually set to processing and backdate
    conn = sqlite3.connect(kc.HARNESS_DB)
    conn.execute("UPDATE jobs SET status='processing', created_at=? WHERE id=?",
                 (int(_t.time()) - 400, job_id))
    conn.commit()
    conn.close()
    count = kc.check_and_mark_stale_jobs(threshold_seconds=300)
    assert count >= 1
    conn = sqlite3.connect(kc.HARNESS_DB)
    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    assert row[0] == 'timed_out'
```

- [ ] **Step 2: Run test — verify it fails**

```bash
python3 -m pytest tests/test_silent_failure.py::test_stale_job_checker_marks_timed_out -v
```
Expected: `AttributeError: module 'kamil_context' has no attribute 'check_and_mark_stale_jobs'`

- [ ] **Step 3: Add `check_and_mark_stale_jobs()` to `kamil_context.py`**

Append after `get_stale_jobs`:

```python
def check_and_mark_stale_jobs(threshold_seconds: int = 300) -> int:
    """
    Mark stale processing jobs as timed_out.
    Returns count of jobs marked.
    """
    import sys
    stale = get_stale_jobs(threshold_seconds=threshold_seconds)
    count = 0
    for job in stale:
        try:
            now = int(time.time())
            c = _conn()
            try:
                c.execute(
                    "UPDATE jobs SET status='timed_out', failure_reason='stale', updated_at=? WHERE id=?",
                    (now, job['id'])
                )
                c.commit()
            finally:
                c.close()
            log_suppression(
                event_id=job.get('event_id', ''),
                reason_code='budget_exhausted',
                raw_text=job.get('raw_text', ''),
                channel=job.get('channel', ''),
                job_id=job['id'],
                details=f"Job stuck in processing for >{threshold_seconds}s",
            )
            count += 1
        except Exception as e:
            print(f"[check_and_mark_stale_jobs] error: {e}", file=sys.stderr)
    return count

def run_stale_job_checker(interval: int = 300) -> None:
    """Run stale job checker forever in a background thread."""
    import sys
    while True:
        try:
            count = check_and_mark_stale_jobs(threshold_seconds=300)
            if count > 0:
                try:
                    from kamil_log import klog
                    klog("stale_jobs_marked", component="listener",
                         count=count, severity="WARNING")
                except Exception:
                    pass
        except Exception as e:
            print(f"[run_stale_job_checker] error: {e}", file=sys.stderr)
        time.sleep(interval)
```

- [ ] **Step 4: Start stale checker thread in `kamil-slack-listener.py`**

Find the `if _context_available:` block in `if __name__ == "__main__":` where the sync loop is started (around line 1075). Add after it:

```python
    if _context_available:
        import threading as _threading
        from kamil_context import run_stale_job_checker
        _threading.Thread(target=run_stale_job_checker, args=(300,), daemon=True).start()
        log("[kamil_context] stale job checker started")
```

- [ ] **Step 5: Run all tests**

```bash
python3 -m pytest tests/test_silent_failure.py tests/test_kamil_context.py -v
```
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add .claude/hooks/kamil_context.py .claude/hooks/kamil-slack-listener.py tests/test_silent_failure.py
git commit -m "feat: add stale job checker — marks timed_out jobs, starts background thread"
```

---

## Self-Review

**Spec coverage:**
- ✅ Job state machine (`received → processing → delivered | failed | timed_out`) → Tasks 1, 2, 6
- ✅ `delivered` written last, after side effect confirmed → Task 6
- ✅ Idempotent job IDs (sha256) → Task 2
- ✅ Suppression event registry with reason codes → Tasks 3, 6, 7
- ✅ `log_suppression()` in `kamil_context.py` + `klog_suppression()` in `kamil_log.py` → Task 3
- ✅ `suppression_log` SQLite table → Task 1
- ✅ `fetch_thread_context()` — full thread before every action → Task 4, 7
- ✅ `extract_pr_url()` — checks trigger then thread → Task 4, 7
- ✅ PR review with no URL → suppression log + ask user → Task 7
- ✅ `tracked_thread()` replaces fire-and-forget → Tasks 5, 8
- ✅ Multi-step milestone logging (`log_milestone()`) → Tasks 3, 9
- ✅ Content pipeline milestone logs → Task 9
- ✅ Stale job checker → Task 10
- ✅ All new functions have unit tests → Tasks 1–5, 10

**Placeholder scan:** No TBDs, no "implement later", all code blocks complete.

**Type consistency:**
- `create_job()` returns `str` (job_id), used as `str` throughout ✅
- `log_suppression()` signature matches in `kamil_context.py` and `kamil_log.py` ✅
- `fetch_thread_context()` returns `str` (empty on failure) ✅
- `extract_pr_url()` returns `Optional[str]` ✅
- `tracked_thread()` returns `threading.Thread` ✅
