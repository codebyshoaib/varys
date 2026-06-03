#!/usr/bin/env python3
"""
kamil_harness_db.py — Unified SQLite database for Kamil's orchestrator harness.

Single file. All scripts share it. Located at ~/.kamil-harness/harness.db
(persistent across reboots — not /tmp).

Tables (6):
  sync_state   — shared last_sync_at timestamp for all pollers
  tick_lock    — re-entrancy guard for the /loop orchestrator tick
  events       — deterministic-ID event queue (pending → processing → done)
  entities     — external objects: Notion tickets, Slack threads, GitHub PRs
  links        — cross-system relationships between entities
  sessions     — per-context_key agent session tracking

Usage:
    from kamil_harness_db import get_db, acquire_tick_lock, release_tick_lock
    from kamil_harness_db import get_last_sync_at, set_last_sync_at

Design rules (from orchestration-harness-v2):
  - context_key is ALWAYS a Notion ticket entity ID — never Slack thread or PR
  - Event IDs are deterministic: "notion-<page_id>", "slack-<ch>-<ts>",
    "github-<repo>-<pr_num>-<type>" — INSERT OR IGNORE is always safe
  - Tick lock stale threshold: 30 minutes (1800s)
  - Tick atomicity: if any poller fails, do NOT update last_sync_at
"""

import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

HARNESS_DIR = Path.home() / ".kamil-harness"
HARNESS_DB  = HARNESS_DIR / "harness.db"

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
"""

_db_lock = threading.Lock()


def get_db() -> sqlite3.Connection:
    """Return a connection to harness.db, creating the file and schema if needed."""
    HARNESS_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(HARNESS_DB), check_same_thread=False)
    db.executescript(_SCHEMA)
    db.commit()
    return db


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
