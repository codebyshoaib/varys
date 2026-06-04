"""
kamil_context.py — Canonical retrieval and write rules for the Kamil harness.
All scripts must import from here. Do NOT duplicate these rules elsewhere.
"""
import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import List, Optional

HARNESS_DB = os.path.expanduser("~/.kamil-harness/harness.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS health (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS entities (
    id           TEXT PRIMARY KEY,
    type         TEXT NOT NULL,
    external_id  TEXT,
    name         TEXT,
    aliases_text TEXT,
    meta         TEXT
);
CREATE TABLE IF NOT EXISTS relations (
    id         TEXT PRIMARY KEY,
    from_id    TEXT NOT NULL REFERENCES entities(id),
    to_id      TEXT NOT NULL REFERENCES entities(id),
    rel_type   TEXT NOT NULL,
    meta       TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS interactions (
    id            TEXT PRIMARY KEY,
    person_id     TEXT NOT NULL REFERENCES entities(id),
    source        TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    raw           TEXT,
    summary       TEXT,
    open_items    TEXT,
    synced_notion INTEGER DEFAULT 0,
    sync_retries  INTEGER DEFAULT 0,
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS nlm_notebooks (
    id           TEXT PRIMARY KEY,
    alias        TEXT,
    domain       TEXT,
    keywords     TEXT,
    last_queried INTEGER
);
CREATE INDEX IF NOT EXISTS idx_entities_type_extid ON entities(type, external_id);
CREATE INDEX IF NOT EXISTS idx_relations_from ON relations(from_id, rel_type);
CREATE INDEX IF NOT EXISTS idx_relations_to   ON relations(to_id,   rel_type);
CREATE INDEX IF NOT EXISTS idx_interactions_person ON interactions(person_id, created_at);
"""

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(HARNESS_DB)
    c.row_factory = sqlite3.Row
    return c

def init_schema() -> None:
    """Create tables if they don't exist. Safe to call multiple times."""
    with _conn() as c:
        for stmt in _SCHEMA.strip().split(';'):
            stmt = stmt.strip()
            if stmt:
                c.execute(stmt)
        existing = c.execute("SELECT version FROM schema_meta").fetchone()
        if not existing:
            c.execute("INSERT INTO schema_meta VALUES (1)")
