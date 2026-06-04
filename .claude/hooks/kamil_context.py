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
    """Return match score: 3=exact name/external_id, 2=alias list-membership, 1=partial. 0=no match."""
    name = (row["name"] or "").lower()
    term_l = term.lower()
    if name == term_l or (row["external_id"] or "").lower() == term_l:
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

# ── record_interaction ─────────────────────────────────────────────────────────

def record_interaction(
    person_id: str,
    source: str,
    external_id: str,
    raw: str,
    summary: str,
    open_items: str,
) -> str:
    """
    Log an interaction. Unit = thread (keyed on external_id).
    Same external_id → UPDATE (same thread got more replies).
    New external_id → INSERT.
    Caller MUST provide agent-distilled summary — do not pass raw text as summary.
    Returns the interaction id.
    """
    iid = hashlib.sha256(f"{source}:{external_id}".encode()).hexdigest()
    now = int(time.time())
    c = _conn()
    try:
        existing = c.execute("SELECT id FROM interactions WHERE id=?", (iid,)).fetchone()
        if existing:
            c.execute(
                "UPDATE interactions SET raw=?, summary=?, open_items=?, updated_at=? WHERE id=?",
                (raw, summary, open_items, now, iid)
            )
        else:
            c.execute(
                """INSERT INTO interactions
                   (id,person_id,source,external_id,raw,summary,open_items,
                    synced_notion,sync_retries,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,0,0,?,?)""",
                (iid, person_id, source, external_id, raw, summary, open_items, now, now)
            )
        c.commit()
    finally:
        c.close()
    return iid

# ── Sync loop ──────────────────────────────────────────────────────────────────

def _get_notion_page_id(entity_id: str) -> str:
    c = _conn()
    try:
        row = c.execute("SELECT meta FROM entities WHERE id=?", (entity_id,)).fetchone()
        return json.loads(row["meta"] or "{}").get("notion_page_id", "") if row else ""
    finally:
        c.close()

def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

def _upsert_slack_inbox(row) -> None:
    """Create a Slack Inbox page in Notion linked to the thread."""
    from kamil_notion import notion_request
    notion_request("POST", "/pages", {
        "parent": {"database_id": "6d14f1b6b8cd4ff68fd40efdfc3f304e"},
        "properties": {
            "Name": {"title": [{"text": {"content": row["external_id"]}}]},
            "Raw": {"rich_text": [{"text": {"content": (row["raw"] or "")[:2000]}}]},
        }
    })

def _log_dead_letter(row, error: str) -> None:
    try:
        from kamil_health import log_health_event
        log_health_event(
            event_type="sync_dead_letter",
            component="kamil_context",
            message=f"interaction {row['id']} dead-letter: {error}",
            severity="ERROR"
        )
    except Exception:
        pass

def _sync_one_row(row, c) -> bool:
    """Sync a single pending interaction to Notion. Returns True on success."""
    import sys
    try:
        from kamil_notion import notion_request
        meta_row = c.execute("SELECT meta FROM entities WHERE id=?", (row["person_id"],)).fetchone()
        page_id = json.loads(meta_row["meta"] or "{}").get("notion_page_id", "") if meta_row else ""
        if page_id:
            notion_request("PATCH", f"/pages/{page_id}", {
                "properties": {
                    "Open Items": {"rich_text": [{"text": {"content": row["open_items"] or ""}}]},
                    "Last Interaction": {"date": {"start": _iso_now()}},
                }
            })
        if row["source"] == "slack":
            _upsert_slack_inbox(row)
        c.execute("UPDATE interactions SET synced_notion=1 WHERE id=?", (row["id"],))
        return True
    except Exception as e:
        print(f"[sync] Failed {row['id']}: {e}", file=sys.stderr)
        new_retries = row["sync_retries"] + 1
        if new_retries >= 5:
            c.execute(
                "UPDATE interactions SET synced_notion=-1, sync_retries=? WHERE id=?",
                (new_retries, row["id"])
            )
            _log_dead_letter(row, str(e))
        else:
            c.execute(
                "UPDATE interactions SET sync_retries=? WHERE id=?",
                (new_retries, row["id"])
            )
        return False

def run_sync_loop(interval: int = 60) -> None:
    """Run the Notion sync loop forever. Call in a background thread."""
    import sys
    while True:
        try:
            c = _conn()
            try:
                rows = c.execute(
                    "SELECT * FROM interactions WHERE synced_notion=0 AND sync_retries < 5 "
                    "ORDER BY created_at ASC"
                ).fetchall()
                for row in rows:
                    _sync_one_row(row, c)
                c.execute(
                    "INSERT OR REPLACE INTO health(key,value,updated_at) VALUES(?,?,?)",
                    ("last_sync_at", _iso_now(), int(time.time()))
                )
                c.commit()
            finally:
                c.close()
        except Exception as e:
            print(f"[sync_loop] Error: {e}", file=sys.stderr)
        time.sleep(interval)
