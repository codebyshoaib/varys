#!/usr/bin/env python3
"""
varys_brain.py — Varys's knowledge graph layer.

Implements a lightweight version of three proven patterns:
  - MAGMA: four entity types (person, skill, project, fact)
  - Mem0: four-operation write protocol (ADD/UPDATE/DELETE/NOOP)
  - Graphiti: temporal validity windows (valid_from, valid_until)

DB location: ~/.varys-harness/brain.db
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

BRAIN_DIR = Path.home() / ".varys-harness"
BRAIN_DB  = BRAIN_DIR / "brain.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    name        TEXT NOT NULL,
    aliases     TEXT DEFAULT '[]',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);

CREATE TABLE IF NOT EXISTS facts (
    id          TEXT PRIMARY KEY,
    subject_id  TEXT NOT NULL REFERENCES entities(id),
    predicate   TEXT NOT NULL,
    object_id   TEXT,
    object_val  TEXT,
    source      TEXT NOT NULL,
    session_id  TEXT,
    valid_from  TEXT NOT NULL,
    valid_until TEXT,
    confidence  REAL DEFAULT 1.0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject_id);
CREATE INDEX IF NOT EXISTS idx_facts_predicate ON facts(predicate);
CREATE INDEX IF NOT EXISTS idx_facts_object ON facts(object_id);
CREATE INDEX IF NOT EXISTS idx_facts_valid ON facts(valid_from, valid_until);

CREATE TABLE IF NOT EXISTS links (
    id          TEXT PRIMARY KEY,
    entity_a    TEXT NOT NULL REFERENCES entities(id),
    entity_b    TEXT NOT NULL REFERENCES entities(id),
    relation    TEXT NOT NULL,
    weight      REAL DEFAULT 1.0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_links_a ON links(entity_a);
CREATE INDEX IF NOT EXISTS idx_links_b ON links(entity_b);

CREATE TABLE IF NOT EXISTS brain_log (
    id          TEXT PRIMARY KEY,
    operation   TEXT NOT NULL,
    entity_type TEXT,
    entity_id   TEXT,
    fact_id     TEXT,
    reason      TEXT,
    session_id  TEXT,
    created_at  TEXT NOT NULL
);
"""

_db_lock = threading.Lock()


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_brain_db():
    """Return connection to brain.db, creating schema if needed."""
    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(BRAIN_DB), check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(_SCHEMA)
    db.commit()
    return db


def upsert_entity(db, entity_id, entity_type, name, aliases=None):
    """ADD or UPDATE an entity. Returns entity_id."""
    with _db_lock:
        now = _now()
        existing = db.execute(
            "SELECT id FROM entities WHERE id=?", (entity_id,)
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE entities SET name=?, aliases=?, updated_at=? WHERE id=?",
                (name, json.dumps(aliases or []), now, entity_id)
            )
            _log_op(db, "UPDATE", entity_type=entity_type, entity_id=entity_id,
                    reason="entity upserted")
        else:
            db.execute(
                "INSERT INTO entities (id, type, name, aliases, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (entity_id, entity_type, name, json.dumps(aliases or []), now, now)
            )
            _log_op(db, "ADD", entity_type=entity_type, entity_id=entity_id,
                    reason="new entity")
        db.commit()
    return entity_id


def write_fact(db, fact_id, subject_id, predicate, object_id=None, object_val=None,
               source="session_log", session_id=None, valid_from=None, confidence=1.0):
    """
    Mem0 four-operation protocol:
    - No existing fact with same subject+predicate: ADD
    - Existing fact, value changed: UPDATE (invalidate old, insert new)
    - Existing fact, value same: NOOP
    Returns operation performed: ADD | UPDATE | NOOP
    """
    with _db_lock:
        now = _now()
        valid_from = valid_from or now

        existing = db.execute(
            "SELECT id, object_id, object_val FROM facts "
            "WHERE subject_id=? AND predicate=? AND valid_until IS NULL",
            (subject_id, predicate)
        ).fetchone()

        if existing:
            same_object = (existing["object_id"] == object_id and
                           existing["object_val"] == object_val)
            if same_object:
                _log_op(db, "NOOP", entity_id=subject_id, fact_id=existing["id"],
                        reason=f"fact unchanged: {predicate}", session_id=session_id)
                db.commit()
                return "NOOP"
            else:
                db.execute(
                    "UPDATE facts SET valid_until=? WHERE id=?",
                    (now, existing["id"])
                )
                _log_op(db, "UPDATE", entity_id=subject_id, fact_id=existing["id"],
                        reason=f"fact updated: {predicate}", session_id=session_id)
        else:
            _log_op(db, "ADD", entity_id=subject_id, fact_id=fact_id,
                    reason=f"new fact: {predicate}", session_id=session_id)

        db.execute(
            "INSERT INTO facts (id, subject_id, predicate, object_id, object_val, "
            "source, session_id, valid_from, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fact_id, subject_id, predicate, object_id, object_val,
             source, session_id, valid_from, confidence, now)
        )
        db.commit()
    return "ADD" if not existing else "UPDATE"


def write_link(db, entity_a, entity_b, relation, weight=1.0):
    """Create a link between two entities (idempotent)."""
    with _db_lock:
        import uuid
        now = _now()
        link_id = f"link-{uuid.uuid4().hex[:12]}"
        existing = db.execute(
            "SELECT id FROM links WHERE entity_a=? AND entity_b=? AND relation=?",
            (entity_a, entity_b, relation)
        ).fetchone()
        if not existing:
            db.execute(
                "INSERT INTO links (id, entity_a, entity_b, relation, weight, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (link_id, entity_a, entity_b, relation, weight, now)
            )
            db.commit()


def query_facts(db, subject_id=None, predicate=None, active_only=True):
    """Retrieve facts, optionally filtered by subject or predicate."""
    clauses, params = [], []
    if subject_id:
        clauses.append("subject_id=?")
        params.append(subject_id)
    if predicate:
        clauses.append("predicate=?")
        params.append(predicate)
    if active_only:
        clauses.append("valid_until IS NULL")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return db.execute(f"SELECT * FROM facts {where}", params).fetchall()


def find_entity(db, name):
    """Find entities by name or alias (case-insensitive)."""
    name_lower = name.lower()
    rows = db.execute(
        "SELECT * FROM entities WHERE LOWER(name)=? OR aliases LIKE ?",
        (name_lower, f'%"{name}"%')
    ).fetchall()
    return [dict(r) for r in rows]


def _log_op(db, operation, entity_type=None, entity_id=None, fact_id=None,
            reason=None, session_id=None):
    import uuid
    db.execute(
        "INSERT INTO brain_log (id, operation, entity_type, entity_id, fact_id, "
        "reason, session_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (f"log-{uuid.uuid4().hex[:12]}", operation, entity_type, entity_id,
         fact_id, reason, session_id, _now())
    )
