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
    os.makedirs(os.path.dirname(HARNESS_DB), exist_ok=True)
    c = sqlite3.connect(HARNESS_DB)
    c.row_factory = sqlite3.Row
    return c

def init_schema() -> None:
    """Create tables if they don't exist. Safe to call multiple times."""
    c = _conn()
    try:
        c.executescript(_SCHEMA)
        existing = c.execute("SELECT version FROM schema_meta").fetchone()
        if not existing:
            c.execute("INSERT INTO schema_meta VALUES (1)")
        c.commit()
    finally:
        c.close()

# ── Exceptions ────────────────────────────────────────────────────────────────

class PersonNotFound(Exception):
    pass

class PersonAmbiguous(Exception):
    def __init__(self, candidates):
        self.candidates = candidates
        super().__init__(f"Ambiguous person — candidates: {[c['name'] for c in candidates]}")

# ── PersonRecord ───────────────────────────────────────────────────────────────

@dataclass
class PersonRecord:
    entity_id: str
    slack_id: str
    notion_page_id: str
    name: str
    aliases: List[str]
    display_name: str

# ── Internal helpers ───────────────────────────────────────────────────────────

def _notion_fetch_person(name: str) -> Optional[dict]:
    """
    Query People Intelligence (Notion MCP) for a person by name.
    Returns dict with keys: name, slack_id, notion_page_id, aliases — or None.
    Monkeypatch this in tests.
    """
    try:
        from kamil_notion import notion_request
        results = notion_request(
            "POST",
            "/databases/c976d58ea4e34b0585f245529cdc4528/query",
            {"filter": {"property": "Name", "rich_text": {"contains": name}}}
        )
        if not results or not results.get("results"):
            return None
        page = results["results"][0]
        props = page.get("properties", {})
        def text_val(p):
            items = p.get("rich_text") or p.get("title") or []
            return "".join(i["plain_text"] for i in items) if items else ""
        return {
            "notion_page_id": page["id"],
            "name": text_val(props.get("Name", {})),
            "slack_id": text_val(props.get("Slack ID", {})),
            "aliases": [a.strip() for a in text_val(props.get("Aliases", {})).split(",") if a.strip()],
        }
    except Exception:
        return None

def _upsert_person_entity(person: dict) -> str:
    """Insert or update a person in SQLite entities. Returns entity_id."""
    import uuid as _uuid
    aliases_text = ",".join(person.get("aliases", []))
    meta = json.dumps({
        "aliases": person.get("aliases", []),
        "slack_id": person.get("slack_id", ""),
        "notion_page_id": person.get("notion_page_id", ""),
    })
    ext_id = person.get("slack_id") or person.get("notion_page_id", "")
    c = _conn()
    try:
        row = c.execute(
            "SELECT id FROM entities WHERE type='person' AND external_id=?", (ext_id,)
        ).fetchone()
        if row:
            entity_id = row["id"]
            c.execute(
                "UPDATE entities SET name=?, aliases_text=?, meta=? WHERE id=?",
                (person["name"], aliases_text, meta, entity_id)
            )
        else:
            entity_id = str(_uuid.uuid4())
            c.execute(
                "INSERT INTO entities(id,type,external_id,name,aliases_text,meta) VALUES(?,?,?,?,?,?)",
                (entity_id, 'person', ext_id, person["name"], aliases_text, meta)
            )
        c.commit()
    finally:
        c.close()
    return entity_id

def _score_match(row, term: str) -> int:
    """Return match score: 3=exact name, 2=alias exact, 1=partial. 0=no match."""
    name = (row["name"] or "").lower()
    term_l = term.lower()
    if name == term_l:
        return 3
    aliases = [a.strip().lower() for a in (row["aliases_text"] or "").split(",") if a.strip()]
    if term_l in aliases:
        return 2
    if term_l in name or any(term_l in a for a in aliases):
        return 1
    return 0

# ── resolve_person ─────────────────────────────────────────────────────────────

def resolve_person(name_or_id: str) -> PersonRecord:
    """
    Find a person by name, alias, Slack ID, or Notion page ID.
    Raises PersonNotFound if not found after Notion fetch.
    Raises PersonAmbiguous if multiple candidates tie on score.
    """
    import sys
    term = name_or_id.strip()
    c = _conn()
    try:
        rows = c.execute("SELECT * FROM entities WHERE type='person'").fetchall()
    finally:
        c.close()

    scored = [(r, _score_match(r, term)) for r in rows]
    scored = [(r, s) for r, s in scored if s > 0]

    if not scored:
        person = _notion_fetch_person(term)
        if not person:
            raise PersonNotFound(term)
        entity_id = _upsert_person_entity(person)
        return PersonRecord(
            entity_id=entity_id,
            slack_id=person.get("slack_id", ""),
            notion_page_id=person.get("notion_page_id", ""),
            name=person["name"],
            aliases=person.get("aliases", []),
            display_name=person["name"],
        )

    max_score = max(s for _, s in scored)
    top = [r for r, s in scored if s == max_score]

    if len(top) == 1:
        if max_score < 3:
            print(
                f"[resolve_person] Warning: '{term}' matched '{top[0]['name']}' (score={max_score}); "
                f"other candidates: {[r['name'] for r, _ in scored if r['id'] != top[0]['id']]}",
                file=sys.stderr
            )
        r = top[0]
        meta = json.loads(r["meta"] or "{}")
        return PersonRecord(
            entity_id=r["id"],
            slack_id=meta.get("slack_id", ""),
            notion_page_id=meta.get("notion_page_id", ""),
            name=r["name"],
            aliases=meta.get("aliases", []),
            display_name=r["name"],
        )

    raise PersonAmbiguous([{"entity_id": r["id"], "name": r["name"]} for r in top])
