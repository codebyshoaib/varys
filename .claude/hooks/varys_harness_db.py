#!/usr/bin/env python3
"""
varys_harness_db.py — Unified SQLite database for Varys's orchestrator harness.

Single file. All scripts share it. Located at ~/.varys-harness/harness.db
(persistent across reboots — not /tmp).

Tables (6):
  sync_state   — shared last_sync_at timestamp for all pollers
  tick_lock    — re-entrancy guard for the /loop orchestrator tick
  events       — deterministic-ID event queue (pending → processing → done)
  entities     — external objects: Notion tickets, Slack threads, GitHub PRs
  links        — cross-system relationships between entities
  sessions     — per-context_key agent session tracking

Usage:
    from varys_harness_db import get_db, acquire_tick_lock, release_tick_lock
    from varys_harness_db import get_last_sync_at, set_last_sync_at

Design rules (from orchestration-harness-v2):
  - context_key is ALWAYS a Notion ticket entity ID — never Slack thread or PR
  - Event IDs are deterministic: "notion-<page_id>", "slack-<ch>-<ts>",
    "github-<repo>-<pr_num>-<type>" — INSERT OR IGNORE is always safe
  - Tick lock stale threshold: 30 minutes (1800s)
  - Tick atomicity: if any poller fails, do NOT update last_sync_at
"""

import os
import shutil
import sqlite3
import subprocess
import threading
from datetime import datetime
from pathlib import Path

HARNESS_DIR = Path.home() / ".varys-harness"
HARNESS_DB  = HARNESS_DIR / "harness.db"
_BEADS_REPO = Path(__file__).resolve().parent.parent.parent  # varys repo root


def _bd(*args) -> str:
    """Run bd in the varys repo. Returns the bead ID line. Never raises."""
    bd_bin = shutil.which("bd") or str(Path.home() / ".local" / "bin" / "bd")
    try:
        r = subprocess.run(
            [bd_bin, *args],
            capture_output=True, text=True,
            cwd=str(_BEADS_REPO), timeout=10,
        )
        for line in r.stdout.splitlines():
            line = line.strip()
            if line and " " not in line and not line.startswith("Warning"):
                return line
        return ""
    except Exception:
        return ""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_state (
    id           TEXT PRIMARY KEY DEFAULT 'global',
    last_sync_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z'
);
INSERT OR IGNORE INTO sync_state (id) VALUES ('global');

CREATE TABLE IF NOT EXISTS tick_lock (
    id        TEXT PRIMARY KEY DEFAULT 'global',
    locked_at TEXT NOT NULL,
    locked_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id           TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    type         TEXT NOT NULL,
    context_key  TEXT NOT NULL,
    payload      TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'pending',
    received_at  TEXT NOT NULL,
    processed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_status_ctx ON events(status, context_key);

CREATE TABLE IF NOT EXISTS entities (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    external_id TEXT NOT NULL,
    type        TEXT NOT NULL,
    url         TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS links (
    entity_a     TEXT NOT NULL REFERENCES entities(id),
    entity_b     TEXT NOT NULL REFERENCES entities(id),
    relationship TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    created_by   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    context_key TEXT NOT NULL,
    status      TEXT NOT NULL,
    intent      TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_ctx_status ON sessions(context_key, status);

CREATE TABLE IF NOT EXISTS capability_gaps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    gap_type      TEXT NOT NULL,
    request_text  TEXT,
    failed_step   TEXT,
    fallback_used TEXT,
    reaction      TEXT DEFAULT 'pending',
    ts            TEXT NOT NULL DEFAULT (datetime('now')),
    session_id    TEXT
);
CREATE INDEX IF NOT EXISTS idx_gaps_type_ts ON capability_gaps(gap_type, ts);

CREATE TABLE IF NOT EXISTS slack_queue (
    id             TEXT PRIMARY KEY,
    source         TEXT NOT NULL,
    channel        TEXT NOT NULL,
    thread_ts      TEXT NOT NULL,
    sender_id      TEXT NOT NULL DEFAULT '',
    sender_name    TEXT NOT NULL DEFAULT '',
    text           TEXT NOT NULL,
    thread_history TEXT NOT NULL DEFAULT '',
    is_dm          INTEGER NOT NULL DEFAULT 0,
    is_third_party INTEGER NOT NULL DEFAULT 0,
    job_id         TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'pending',
    retry_count    INTEGER NOT NULL DEFAULT 0,
    enqueued_at    TEXT NOT NULL DEFAULT (datetime('now')),
    processed_at   TEXT,
    priority        INTEGER NOT NULL DEFAULT 0,
    failure_context TEXT,
    bead_id         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_slack_queue_status_enq ON slack_queue(status, enqueued_at);
"""

_db_lock = threading.Lock()


def get_db() -> sqlite3.Connection:
    """Return a connection to harness.db, creating the file and schema if needed."""
    HARNESS_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(HARNESS_DB), check_same_thread=False)
    db.executescript(_SCHEMA)
    db.commit()
    migrate_db(db)
    return db


def migrate_db(db: sqlite3.Connection) -> None:
    """Apply incremental migrations. Safe to run on every startup."""
    with _db_lock:
        cols = [row[1] for row in db.execute("PRAGMA table_info(sessions)").fetchall()]
        # Migration 001: sessions.phase column for two-phase manager flow
        if "phase" not in cols:
            db.execute("ALTER TABLE sessions ADD COLUMN phase TEXT DEFAULT 'manager'")
        # Migration 002: session completion tracking (pr_url, completed_at)
        if "completed_at" not in cols:
            db.execute("ALTER TABLE sessions ADD COLUMN completed_at TEXT")
        if "pr_url" not in cols:
            db.execute("ALTER TABLE sessions ADD COLUMN pr_url TEXT")
        # Migration 004: priority + failure_context + lease/ack columns for slack_queue
        sq_cols = [row[1] for row in db.execute("PRAGMA table_info(slack_queue)").fetchall()]
        if "priority" not in sq_cols:
            db.execute("ALTER TABLE slack_queue ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
        if "failure_context" not in sq_cols:
            db.execute("ALTER TABLE slack_queue ADD COLUMN failure_context TEXT")
        if "bead_id" not in sq_cols:
            db.execute("ALTER TABLE slack_queue ADD COLUMN bead_id TEXT NOT NULL DEFAULT ''")
        # lease_expires_at: real visibility timeout, set when a worker claims the job.
        # ack_posted: idempotency flag so the "On it" ack is posted at most once, ever.
        if "lease_expires_at" not in sq_cols:
            db.execute("ALTER TABLE slack_queue ADD COLUMN lease_expires_at TEXT")
        if "ack_posted" not in sq_cols:
            db.execute("ALTER TABLE slack_queue ADD COLUMN ack_posted INTEGER NOT NULL DEFAULT 0")

        # Migration 003: reclaim jobs whose LEASE has expired (a genuinely crashed/hung
        # worker) — NOT on a clock counted from enqueue. A job in flight holds a live
        # lease (renewed to now+SLACK_LEASE_SECONDS when claimed), so a slow-but-alive
        # review is never re-dispatched under itself — retries fire only when needed.
        # Each reclaim counts as a retry; after 3 the job dead-letters to 'failed' so a
        # job that never succeeds can't loop forever (that was the infinite-ack bug).
        db.execute(
            "UPDATE slack_queue SET status='failed', processed_at=datetime('now') "
            "WHERE status='processing' AND retry_count >= 3 "
            "AND lease_expires_at IS NOT NULL AND lease_expires_at < datetime('now')"
        )
        db.execute(
            "UPDATE slack_queue SET status='pending', retry_count=retry_count+1, lease_expires_at=NULL "
            "WHERE status='processing' "
            "AND lease_expires_at IS NOT NULL AND lease_expires_at < datetime('now')"
        )
        db.commit()


# ── Tick lock ─────────────────────────────────────────────────────────────────

def acquire_tick_lock(db: sqlite3.Connection, caller: str) -> bool:
    """
    Clear stale lock (>30 min), then attempt atomic acquire.
    Returns True if this caller now holds the lock, False if another tick is running.
    """
    with _db_lock:
        # Clear stale lock older than 30 minutes
        db.execute(
            "DELETE FROM tick_lock WHERE id='global' "
            "AND (CAST(strftime('%s','now') AS INTEGER) "
            "   - CAST(strftime('%s', locked_at) AS INTEGER)) > 1800"
        )
        db.commit()

        lock_id = f"{caller}-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
        db.execute(
            "INSERT OR IGNORE INTO tick_lock (id, locked_at, locked_by) "
            "VALUES ('global', datetime('now'), ?)",
            (lock_id,),
        )
        db.commit()
        acquired = db.execute("SELECT changes()").fetchone()[0] > 0
        return acquired


def release_tick_lock(db: sqlite3.Connection) -> None:
    with _db_lock:
        db.execute("DELETE FROM tick_lock WHERE id='global'")
        db.commit()


# ── Sync state ────────────────────────────────────────────────────────────────

def get_last_sync_at(db: sqlite3.Connection) -> str:
    """Return the last_sync_at ISO timestamp. Defaults to epoch if never set."""
    row = db.execute(
        "SELECT last_sync_at FROM sync_state WHERE id='global'"
    ).fetchone()
    return row[0] if row else "1970-01-01T00:00:00Z"


def set_last_sync_at(db: sqlite3.Connection, ts: str) -> None:
    """Update last_sync_at. Only called on SUCCESSFUL tick completion."""
    with _db_lock:
        db.execute(
            "UPDATE sync_state SET last_sync_at=? WHERE id='global'", (ts,)
        )
        db.commit()


# ── Entity registry ───────────────────────────────────────────────────────────

def register_entity(
    db: sqlite3.Connection,
    source: str,
    external_id: str,
    entity_type: str,
    url: str = "",
) -> str:
    """
    Register an external object. Returns the internal entity UUID.
    Safe to call repeatedly — UNIQUE(source, external_id) prevents duplicates.
    """
    import uuid as _uuid
    with _db_lock:
        existing = db.execute(
            "SELECT id FROM entities WHERE source=? AND external_id=?",
            (source, external_id),
        ).fetchone()
        if existing:
            return existing[0]
        entity_id = str(_uuid.uuid4())
        db.execute(
            "INSERT OR IGNORE INTO entities (id, source, external_id, type, url, created_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (entity_id, source, external_id, entity_type, url or ""),
        )
        db.commit()
        return entity_id


def link_entities(
    db: sqlite3.Connection,
    entity_a: str,
    entity_b: str,
    relationship: str,
    session_id: str = "system",
) -> None:
    """Create a directional link between two entities."""
    with _db_lock:
        db.execute(
            "INSERT OR IGNORE INTO links (entity_a, entity_b, relationship, created_at, created_by) "
            "VALUES (?, ?, ?, datetime('now'), ?)",
            (entity_a, entity_b, relationship, session_id),
        )
        db.commit()


def get_linked_entities(db: sqlite3.Connection, entity_id: str) -> list[dict]:
    """
    Return all entities linked to entity_id (both directions).
    Excludes entity_id itself.
    """
    rows = db.execute(
        """
        SELECT e.id, e.source, e.external_id, e.type, e.url
        FROM entities e
        JOIN links l ON (l.entity_a = e.id OR l.entity_b = e.id)
        WHERE (l.entity_a = ? OR l.entity_b = ?)
          AND e.id != ?
        """,
        (entity_id, entity_id, entity_id),
    ).fetchall()
    return [
        {"id": r[0], "source": r[1], "external_id": r[2], "type": r[3], "url": r[4]}
        for r in rows
    ]


# ── Capability gap tracking ───────────────────────────────────────────────────

def log_capability_gap(
    db: sqlite3.Connection,
    gap_type: str,
    request_text: str = "",
    failed_step: str = "",
    fallback_used: str = "",
    session_id: str = "",
) -> None:
    """Record one capability gap occurrence."""
    with _db_lock:
        db.execute(
            "INSERT INTO capability_gaps "
            "(gap_type, request_text, failed_step, fallback_used, session_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (gap_type, request_text[:300], failed_step, fallback_used, session_id),
        )
        db.commit()


def get_capability_gaps(
    db: sqlite3.Connection,
    days: int = 7,
    min_count: int = 1,
) -> list[dict]:
    """
    Return aggregated gap counts for the last N days.
    Each dict: {gap_type, count, rejected_count, sample_requests, last_seen}
    """
    with _db_lock:
        rows = db.execute(
            """
            SELECT
                gap_type,
                COUNT(*) as count,
                SUM(CASE WHEN reaction='rejected' THEN 1 ELSE 0 END) as rejected_count,
                MAX(ts) as last_seen,
                GROUP_CONCAT(request_text, '|||') as samples
            FROM capability_gaps
            WHERE ts >= datetime('now', ?)
            GROUP BY gap_type
            HAVING COUNT(*) >= ?
            ORDER BY count DESC
            """,
            (f"-{days} days", min_count),
        ).fetchall()
    return [
        {
            "gap_type":        r[0],
            "count":           r[1],
            "rejected_count":  r[2] or 0,
            "last_seen":       r[3],
            "sample_requests": [s.strip() for s in (r[4] or "").split("|||") if s.strip()][:3],
        }
        for r in rows
    ]


def update_gap_reaction(
    db: sqlite3.Connection,
    gap_type: str,
    reaction: str,
) -> None:
    """Mark the most recent gap entry for this type with a reaction."""
    with _db_lock:
        db.execute(
            "UPDATE capability_gaps SET reaction=? "
            "WHERE gap_type=? AND id=("
            "  SELECT id FROM capability_gaps WHERE gap_type=? ORDER BY id DESC LIMIT 1"
            ")",
            (reaction, gap_type, gap_type),
        )
        db.commit()


# ── Slack mention queue ───────────────────────────────────────────────────────

def enqueue_slack_mention(
    db: sqlite3.Connection,
    row_id: str,
    source: str,
    channel: str,
    thread_ts: str,
    sender_id: str,
    sender_name: str,
    text: str,
    thread_history: str,
    is_dm: bool,
    is_third_party: bool,
    job_id: str = "",
    priority: int = 0,
) -> bool:
    """Insert a mention into the queue. Returns True if new, False if already queued (dedup)."""
    with _db_lock:
        db.execute(
            "INSERT OR IGNORE INTO slack_queue "
            "(id, source, channel, thread_ts, sender_id, sender_name, text, "
            " thread_history, is_dm, is_third_party, job_id, priority) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row_id, source, channel, thread_ts, sender_id or "", sender_name or "",
             text, thread_history or "", int(is_dm), int(is_third_party), job_id or "",
             priority),
        )
        db.commit()
        is_new = db.execute("SELECT changes()").fetchone()[0] > 0
    if is_new:
        title = f"Slack: {sender_name or sender_id or 'unknown'}: {text[:60]}"
        bead_id = _bd("q", title, "-t", "task")
        if bead_id:
            with _db_lock:
                db.execute("UPDATE slack_queue SET bead_id=? WHERE id=?", (bead_id, row_id))
                db.commit()
    return is_new


def dequeue_pending_slack(db: sqlite3.Connection, limit: int = 50) -> list:
    """Return pending rows ordered by priority DESC, FIFO within same priority. Does NOT mark them processing."""
    return db.execute(
        "SELECT id, source, channel, thread_ts, sender_id, sender_name, text, "
        "thread_history, is_dm, is_third_party, job_id, retry_count, priority, failure_context "
        "FROM slack_queue WHERE status='pending' ORDER BY priority DESC, enqueued_at ASC LIMIT ?",
        (limit,),
    ).fetchall()


# Visibility timeout: how long a claimed job is considered alive before the reclaim
# may re-queue it. MUST exceed the worker's longest run (900s PR-review backstop in
# slack-worker.py) plus drain overhead, or a live review gets re-dispatched under itself.
SLACK_LEASE_SECONDS = 1000


def mark_slack_processing(db: sqlite3.Connection, row_id: str) -> None:
    with _db_lock:
        db.execute(
            "UPDATE slack_queue SET status='processing', "
            "lease_expires_at=datetime('now', ?) WHERE id=?",
            (f"+{SLACK_LEASE_SECONDS} seconds", row_id),
        )
        db.commit()
        bead_id = db.execute("SELECT bead_id FROM slack_queue WHERE id=?", (row_id,)).fetchone()
    if bead_id and bead_id[0]:
        _bd("update", bead_id[0], "--claim")


def slack_try_ack(db: sqlite3.Connection, row_id: str) -> bool:
    """Atomically claim the right to post the one-time 'On it' ack for this job.
    Returns True exactly once per job — any retry/re-run gets False, so the ack is
    never duplicated even if the job is dispatched more than once."""
    with _db_lock:
        db.execute(
            "UPDATE slack_queue SET ack_posted=1 WHERE id=? AND ack_posted=0", (row_id,)
        )
        db.commit()
        return db.execute("SELECT changes()").fetchone()[0] > 0


def mark_slack_done(db: sqlite3.Connection, row_id: str) -> None:
    with _db_lock:
        db.execute(
            "UPDATE slack_queue SET status='done', processed_at=datetime('now'), "
            "lease_expires_at=NULL WHERE id=?",
            (row_id,),
        )
        db.commit()
        bead_id = db.execute("SELECT bead_id FROM slack_queue WHERE id=?", (row_id,)).fetchone()
    if bead_id and bead_id[0]:
        _bd("close", bead_id[0])


def mark_slack_retry(
    db: sqlite3.Connection, row_id: str, max_retries: int = 3, failure_context: str = None
) -> None:
    """On error: store failure context, retry up to max_retries, then mark failed."""
    with _db_lock:
        row = db.execute(
            "SELECT retry_count, bead_id FROM slack_queue WHERE id=?", (row_id,)
        ).fetchone()
        exhausted = row and row[0] >= max_retries
        if exhausted:
            db.execute(
                "UPDATE slack_queue SET status='failed', processed_at=datetime('now'), "
                "failure_context=? WHERE id=?",
                (failure_context, row_id),
            )
        else:
            db.execute(
                "UPDATE slack_queue SET status='pending', retry_count=retry_count+1, "
                "failure_context=?, lease_expires_at=NULL WHERE id=?",
                (failure_context, row_id),
            )
        db.commit()
        bead_id = row[1] if row else ""
    if bead_id:
        note = f"Failed (retry): {failure_context[:200]}" if not exhausted else f"Failed (exhausted): {failure_context[:200]}"
        _bd("note", bead_id, note)
        if exhausted:
            _bd("label", bead_id, "add", "status:failed")


if __name__ == "__main__":
    # Self-test
    db = get_db()
    print(f"harness.db ready at: {HARNESS_DB}")
    print(f"last_sync_at: {get_last_sync_at(db)}")
    print(f"acquire lock: {acquire_tick_lock(db, 'self-test')}")
    print(f"acquire again (should be False): {acquire_tick_lock(db, 'self-test-2')}")
    release_tick_lock(db)
    print(f"after release, acquire: {acquire_tick_lock(db, 'self-test-3')}")
    release_tick_lock(db)
    db.close()
    print("OK")
