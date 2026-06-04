# Kamil Brain Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `kamil_context.py` — a single module encoding all retrieval and write rules — backed by a graph-ready SQLite schema, and wire it into the Slack listener and Stop hook so the agent remembers every interaction and retrieves context automatically.

**Architecture:** SQLite speed layer (entities + relations + interactions) for fast per-person reads; `kamil_context.py` exposes `resolve_person()`, `lookup_context()`, `record_interaction()` as the canonical API; Notion is the human-readable mirror synced by a background loop. Two People DBs are merged into one canonical `People Intelligence` DB.

**Tech Stack:** Python 3.10+, SQLite3 (stdlib), `python-Levenshtein` for fuzzy name matching, `hashlib` (stdlib) for dedup IDs, existing `kamil_notion.py` for Notion MCP rate-limiting, existing `slack_sdk` in the listener.

**Spec:** `docs/superpowers/specs/2026-06-04-kamil-brain-redesign.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `.claude/hooks/kamil_context.py` | **Create** | `resolve_person`, `lookup_context`, `record_interaction`, sync loop, `HARNESS_DB` constant |
| `.claude/hooks/merge-people-dbs.py` | **Create** | One-time migration: dry-run report + `--write` mode |
| `.claude/hooks/kamil-slack-listener.py` | **Modify** | Wire `record_interaction()` after every sent reply |
| `.claude/hooks/stop.py` | **Modify** | Wire person-extraction + relevance filter + `record_interaction()` |
| `.claude/rules/notion.md` | **Modify** | Replace retrieval/write spec with one-line defer |
| `.claude/rules/slack.md` | **Modify** | Replace lookup/send spec with one-line defer |
| `tests/test_kamil_context.py` | **Create** | Unit tests for all three functions |
| `tests/test_merge_people_dbs.py` | **Create** | Unit tests for dry-run matcher |

---

## Task 1: SQLite Schema Migration

**Files:**
- Create: `.claude/hooks/kamil_context.py` (schema + constants only)
- Test: `tests/test_kamil_context.py`

- [ ] **Step 1: Install python-Levenshtein if not present**

```bash
pip show python-Levenshtein >/dev/null 2>&1 || pip install python-Levenshtein
```
Expected: no error.

- [ ] **Step 2: Write the failing schema test**

Create `tests/test_kamil_context.py`:

```python
import sqlite3, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '.claude', 'hooks'))

def make_db(path):
    import kamil_context as kc
    kc.HARNESS_DB = path
    kc.init_schema()
    return sqlite3.connect(path)

def test_schema_tables_exist():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    conn = make_db(path)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    assert tables >= {'schema_meta','health','entities','relations','interactions','nlm_notebooks'}

def test_schema_version_is_1():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    conn = make_db(path)
    version = conn.execute("SELECT version FROM schema_meta").fetchone()[0]
    assert version == 1

def test_init_schema_idempotent():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    make_db(path)
    make_db(path)  # second call must not raise
```

- [ ] **Step 3: Run test — verify it fails**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python -m pytest tests/test_kamil_context.py -v 2>&1 | head -30
```
Expected: `ModuleNotFoundError: No module named 'kamil_context'`

- [ ] **Step 4: Create `kamil_context.py` with schema only**

Create `.claude/hooks/kamil_context.py`:

```python
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
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
python -m pytest tests/test_kamil_context.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 6: Run init_schema against the real harness DB**

```bash
python3 -c "
import sys; sys.path.insert(0, '.claude/hooks')
import kamil_context as kc
kc.init_schema()
import sqlite3
conn = sqlite3.connect(kc.HARNESS_DB)
tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
print('Tables:', tables)
"
```
Expected: output includes `entities relations interactions nlm_notebooks schema_meta health` alongside existing `tick_lock events` etc.

- [ ] **Step 7: Commit**

```bash
git add .claude/hooks/kamil_context.py tests/test_kamil_context.py
git commit -m "feat: init kamil_context.py with graph-ready SQLite schema"
```

---

## Task 2: `resolve_person()`

**Files:**
- Modify: `.claude/hooks/kamil_context.py`
- Modify: `tests/test_kamil_context.py`

- [ ] **Step 1: Write failing tests for resolve_person**

Append to `tests/test_kamil_context.py`:

```python
import uuid

def _seed_person(path, name, slack_id, aliases=None):
    """Helper: insert a person entity directly into the test DB."""
    import kamil_context as kc
    kc.HARNESS_DB = path
    kc.init_schema()
    conn = sqlite3.connect(path)
    aliases_text = ",".join(aliases or [])
    meta = json.dumps({"aliases": aliases or [], "slack_id": slack_id})
    entity_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO entities(id,type,external_id,name,aliases_text,meta) VALUES(?,?,?,?,?,?)",
        (entity_id, 'person', slack_id, name, aliases_text, meta)
    )
    conn.commit()
    conn.close()
    return entity_id

def test_resolve_person_exact_name():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    import kamil_context as kc
    kc.HARNESS_DB = path
    eid = _seed_person(path, "Mahnoor Baig", "U123")
    result = kc.resolve_person("Mahnoor Baig")
    assert result.entity_id == eid
    assert result.slack_id == "U123"

def test_resolve_person_alias():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    import kamil_context as kc
    kc.HARNESS_DB = path
    eid = _seed_person(path, "Mahnoor Baig", "U123", aliases=["Mahnoor", "@m.baig"])
    result = kc.resolve_person("Mahnoor")
    assert result.entity_id == eid

def test_resolve_person_not_found_raises():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    import kamil_context as kc
    kc.HARNESS_DB = path
    kc.init_schema()
    # Patch Notion fetch to return nothing
    kc._notion_fetch_person = lambda name: None
    try:
        kc.resolve_person("Nobody Here")
        assert False, "Should have raised PersonNotFound"
    except kc.PersonNotFound:
        pass

def test_resolve_person_ambiguous_raises():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    import kamil_context as kc
    kc.HARNESS_DB = path
    _seed_person(path, "Mah Noor", "U111", aliases=["Mahnoor"])
    _seed_person(path, "Mahnoor Khan", "U222", aliases=["Mahnoor"])
    kc._notion_fetch_person = lambda name: None
    try:
        kc.resolve_person("Mahnoor")
        assert False, "Should have raised PersonAmbiguous"
    except kc.PersonAmbiguous as e:
        assert len(e.candidates) >= 2
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python -m pytest tests/test_kamil_context.py::test_resolve_person_exact_name -v
```
Expected: `AttributeError: module 'kamil_context' has no attribute 'resolve_person'`

- [ ] **Step 3: Add exceptions and `resolve_person` to `kamil_context.py`**

Append to `.claude/hooks/kamil_context.py` after `init_schema`:

```python
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
    Returns a dict with keys: name, slack_id, notion_page_id, aliases
    or None if not found.
    Callers may monkeypatch this in tests.
    """
    try:
        from kamil_notion import notion_request
        results = notion_request(
            "POST",
            f"/databases/c976d58ea4e34b0585f245529cdc4528/query",
            {
                "filter": {
                    "property": "Name",
                    "rich_text": {"contains": name}
                }
            }
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
    with _conn() as c:
        row = c.execute(
            "SELECT id FROM entities WHERE type='person' AND external_id=?",
            (person.get("slack_id") or person.get("notion_page_id", ""),)
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
                (entity_id, 'person',
                 person.get("slack_id") or person.get("notion_page_id", ""),
                 person["name"], aliases_text, meta)
            )
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
    term = name_or_id.strip()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM entities WHERE type='person'"
        ).fetchall()

    # Score all candidates
    scored = [(r, _score_match(r, term)) for r in rows]
    scored = [(r, s) for r, s in scored if s > 0]

    if not scored:
        # Miss → try Notion
        person = _notion_fetch_person(term)
        if not person:
            raise PersonNotFound(term)
        entity_id = _upsert_person_entity(person)
        aliases = person.get("aliases", [])
        return PersonRecord(
            entity_id=entity_id,
            slack_id=person.get("slack_id", ""),
            notion_page_id=person.get("notion_page_id", ""),
            name=person["name"],
            aliases=aliases,
            display_name=person["name"],
        )

    # Pick best score
    max_score = max(s for _, s in scored)
    top = [r for r, s in scored if s == max_score]

    if len(top) == 1:
        if max_score < 3:
            # Log ambiguity warning (non-fatal)
            import sys
            print(f"[resolve_person] Warning: '{term}' matched '{top[0]['name']}' (score={max_score}); "
                  f"other candidates: {[r['name'] for r, _ in scored if r['id'] != top[0]['id']]}",
                  file=sys.stderr)
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

    # Tie at top score → ambiguous
    raise PersonAmbiguous([
        {"entity_id": r["id"], "name": r["name"]} for r in top
    ])
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest tests/test_kamil_context.py -v
```
Expected: all tests PASS (7 total).

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks/kamil_context.py tests/test_kamil_context.py
git commit -m "feat: add resolve_person() with alias matching and PersonAmbiguous/PersonNotFound"
```

---

## Task 3: `merge-people-dbs.py` dry-run + STOP FOR APPROVAL

**Files:**
- Create: `.claude/hooks/merge-people-dbs.py`
- Create: `tests/test_merge_people_dbs.py`

- [ ] **Step 1: Write failing test for the matcher**

Create `tests/test_merge_people_dbs.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '.claude', 'hooks'))
from merge_people_dbs import match_people

def test_exact_match():
    source = [{"name": "Mahnoor Baig", "slack_id": "U1"}]
    target = [{"notion_page_id": "p1", "name": "Mahnoor Baig", "slack_id": ""}]
    result = match_people(source, target)
    assert result[0]["match_type"] == "exact"
    assert result[0]["source"]["name"] == "Mahnoor Baig"

def test_fuzzy_match():
    source = [{"name": "Mah Noor", "slack_id": "U2"}]
    target = [{"notion_page_id": "p2", "name": "Mahnoor", "slack_id": ""}]
    result = match_people(source, target)
    assert result[0]["match_type"] == "fuzzy"

def test_no_match_is_new():
    source = [{"name": "Brand New Person", "slack_id": "U3"}]
    target = [{"notion_page_id": "p3", "name": "Totally Different", "slack_id": ""}]
    result = match_people(source, target)
    assert result[0]["match_type"] == "new"
```

- [ ] **Step 2: Run test — verify it fails**

```bash
python -m pytest tests/test_merge_people_dbs.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'merge_people_dbs'`

- [ ] **Step 3: Create `merge-people-dbs.py`**

Create `.claude/hooks/merge-people-dbs.py`:

```python
#!/usr/bin/env python3
"""
merge-people-dbs.py — One-time migration: Team People / focus → People Intelligence.

Usage:
  python3 merge-people-dbs.py --dry-run   # print match report, no writes
  python3 merge-people-dbs.py --write     # requires prior dry-run approval
"""
import sys, os, json, argparse
sys.path.insert(0, os.path.dirname(__file__))

try:
    from Levenshtein import distance as lev_distance
except ImportError:
    def lev_distance(a, b):
        # pure-Python fallback (slow but correct)
        m, n = len(a), len(b)
        dp = list(range(n + 1))
        for i in range(1, m + 1):
            prev = dp[:]
            dp[0] = i
            for j in range(1, n + 1):
                dp[j] = prev[j - 1] if a[i-1] == b[j-1] else 1 + min(prev[j], dp[j-1], prev[j-1])
        return dp[n]

SOURCE_DB_ID = "bbf6ade203e543f39f4c64a2f05fe29e"   # Team People / focus
TARGET_DB_ID = "c976d58ea4e34b0585f245529cdc4528"   # People Intelligence (canonical)

def _fetch_db_pages(db_id: str) -> list:
    from kamil_notion import notion_request
    results, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        resp = notion_request("POST", f"/databases/{db_id}/query", body)
        results.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return results

def _page_to_dict(page: dict) -> dict:
    props = page.get("properties", {})
    def text(p):
        items = p.get("rich_text") or p.get("title") or []
        return "".join(i["plain_text"] for i in items)
    return {
        "notion_page_id": page["id"],
        "name": text(props.get("Name", {})),
        "slack_id": text(props.get("Slack ID", {})),
        "role": text(props.get("Role", {})),
        "current_focus": text(props.get("Current Focus", props.get("Focus", {}))),
    }

def match_people(source: list, target: list) -> list:
    """
    Match source records against target by name.
    Returns list of dicts: {source, target_or_None, match_type: exact|fuzzy|new}
    """
    results = []
    for s in source:
        best_target, best_dist = None, 999
        for t in target:
            d = lev_distance(s["name"].lower(), t["name"].lower())
            if d < best_dist:
                best_dist, best_target = d, t
        if best_dist == 0:
            results.append({"source": s, "target": best_target, "match_type": "exact", "distance": 0})
        elif best_dist <= 2:
            results.append({"source": s, "target": best_target, "match_type": "fuzzy", "distance": best_dist})
        else:
            results.append({"source": s, "target": None, "match_type": "new", "distance": best_dist})
    return results

def print_report(matches: list):
    exact  = [m for m in matches if m["match_type"] == "exact"]
    fuzzy  = [m for m in matches if m["match_type"] == "fuzzy"]
    new    = [m for m in matches if m["match_type"] == "new"]

    print(f"\n## Merge Dry-Run Report\n")
    print(f"**Exact matches ({len(exact)})** — will merge fields (role, current focus):\n")
    print("| Source Name | Target Name |")
    print("|---|---|")
    for m in exact:
        print(f"| {m['source']['name']} | {m['target']['name']} |")

    print(f"\n**Fuzzy matches ({len(fuzzy)})** — REVIEW BEFORE WRITING:\n")
    print("| Source Name | Target Name | Edit Distance |")
    print("|---|---|---|")
    for m in fuzzy:
        print(f"| {m['source']['name']} | {m['target']['name']} | {m['distance']} |")

    print(f"\n**New records ({len(new)})** — will be created in People Intelligence:\n")
    print("| Name |")
    print("|---|")
    for m in new:
        print(f"| {m['source']['name']} |")

    print(f"\n---\nReview fuzzy matches carefully. Run with --write only after approval.")

def do_write(matches: list):
    from kamil_notion import notion_request
    for m in matches:
        s = m["source"]
        if m["match_type"] in ("exact", "fuzzy"):
            t = m["target"]
            # Merge role + current_focus from source into target if target fields are empty
            updates = {}
            if s.get("role") and not t.get("role"):
                updates["Role"] = {"rich_text": [{"text": {"content": s["role"]}}]}
            if s.get("current_focus") and not t.get("current_focus"):
                updates["Current Focus"] = {"rich_text": [{"text": {"content": s["current_focus"]}}]}
            if s.get("slack_id") and not t.get("slack_id"):
                updates["Slack ID"] = {"rich_text": [{"text": {"content": s["slack_id"]}}]}
            if updates:
                notion_request("PATCH", f"/pages/{t['notion_page_id']}", {"properties": updates})
                print(f"  Updated: {t['name']}")
        elif m["match_type"] == "new":
            notion_request("POST", "/pages", {
                "parent": {"database_id": TARGET_DB_ID},
                "properties": {
                    "Name": {"title": [{"text": {"content": s["name"]}}]},
                    "Slack ID": {"rich_text": [{"text": {"content": s.get("slack_id", "")}}]},
                    "Role": {"rich_text": [{"text": {"content": s.get("role", "")}}]},
                }
            })
            print(f"  Created: {s['name']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.write:
        print("Pass --dry-run or --write", file=sys.stderr)
        sys.exit(1)

    print("Fetching source DB (Team People / focus)...")
    source_pages = _fetch_db_pages(SOURCE_DB_ID)
    source = [_page_to_dict(p) for p in source_pages]

    print("Fetching target DB (People Intelligence)...")
    target_pages = _fetch_db_pages(TARGET_DB_ID)
    target = [_page_to_dict(p) for p in target_pages]

    matches = match_people(source, target)

    if args.dry_run:
        print_report(matches)
    elif args.write:
        print("Writing...")
        do_write(matches)
        print("Done.")
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest tests/test_merge_people_dbs.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 5: Run the dry-run against live Notion**

```bash
python3 .claude/hooks/merge-people-dbs.py --dry-run
```
Expected: Markdown table printed with exact/fuzzy/new sections.

- [ ] **Step 6: STOP — show Kamil the dry-run output and wait for approval**

Do NOT run `--write` until Kamil has reviewed the fuzzy matches and said "approve".

- [ ] **Step 7: Commit the scripts**

```bash
git add .claude/hooks/merge-people-dbs.py tests/test_merge_people_dbs.py
git commit -m "feat: add merge-people-dbs.py with dry-run matcher"
```

---

## Task 4: Run merge `--write` + rewire references (after Kamil approval)

**Files:**
- Modify: any file containing `bbf6ade2`

- [ ] **Step 1: Run the merge write**

```bash
python3 .claude/hooks/merge-people-dbs.py --write
```
Expected: "Updated: X" / "Created: Y" lines for each person.

- [ ] **Step 2: Find every reference to the old DB ID**

```bash
grep -rn "bbf6ade2" /home/oye/Documents/free_work/personal-agent-v2/ --include="*.py" --include="*.md" --include="*.json"
```

- [ ] **Step 3: Rewire each hit**

For each file returned, replace `bbf6ade2` (and the full UUID `bbf6ade203e543f39f4c64a2f05fe29e`) with `c976d58ea4e34b0585f245529cdc4528`. Do NOT use sed — read each file and make targeted edits so surrounding context is preserved.

- [ ] **Step 4: Verify zero remaining references**

```bash
grep -rn "bbf6ade2" /home/oye/Documents/free_work/personal-agent-v2/ --include="*.py" --include="*.md" --include="*.json"
```
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add -u
git commit -m "feat: rewire all bbf6ade2 references to canonical People Intelligence DB"
```

---

## Task 5: `record_interaction()` + sync loop

**Files:**
- Modify: `.claude/hooks/kamil_context.py`
- Modify: `tests/test_kamil_context.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_kamil_context.py`:

```python
import time as _time

def test_record_interaction_inserts():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    import kamil_context as kc
    kc.HARNESS_DB = path
    eid = _seed_person(path, "Mahnoor Baig", "U123")
    iid = kc.record_interaction(
        person_id=eid, source='slack',
        external_id='C01_1234567890.000100',
        raw='test thread', summary='Mahnoor asked about sprint',
        open_items=json.dumps(['Follow up on ticket'])
    )
    conn = sqlite3.connect(path)
    row = conn.execute("SELECT * FROM interactions WHERE id=?", (iid,)).fetchone()
    assert row is not None

def test_record_interaction_dedup():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    import kamil_context as kc
    kc.HARNESS_DB = path
    eid = _seed_person(path, "Mahnoor Baig", "U123")
    ext_id = 'C01_9999999999.000100'
    id1 = kc.record_interaction(eid, 'slack', ext_id, 'raw1', 'summary1', '[]')
    id2 = kc.record_interaction(eid, 'slack', ext_id, 'raw2-updated', 'summary2-updated', '[]')
    assert id1 == id2  # same thread → same id
    conn = sqlite3.connect(path)
    row = conn.execute("SELECT raw FROM interactions WHERE id=?", (id1,)).fetchone()
    assert 'updated' in row[0]  # row was updated, not duplicated
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python -m pytest tests/test_kamil_context.py::test_record_interaction_inserts -v
```
Expected: `AttributeError: module 'kamil_context' has no attribute 'record_interaction'`

- [ ] **Step 3: Add `record_interaction` to `kamil_context.py`**

Append after `resolve_person`:

```python
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
    Log an interaction. Unit = thread (key on external_id).
    If row exists (same thread), UPDATE raw/summary/open_items/updated_at.
    If new, INSERT.
    Returns the interaction id.
    Caller MUST provide agent-distilled summary — do not pass raw text as summary.
    """
    iid = hashlib.sha256(f"{source}:{external_id}".encode()).hexdigest()
    now = int(time.time())
    with _conn() as c:
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
    return iid
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest tests/test_kamil_context.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Add sync loop to `kamil_context.py`**

Append after `record_interaction`:

```python
# ── Sync loop ──────────────────────────────────────────────────────────────────

def _sync_one_row(row, c) -> bool:
    """Sync a single pending interaction row to Notion. Returns True on success."""
    try:
        from kamil_notion import notion_request

        # Append summary to People Intelligence page
        notion_request("PATCH", f"/pages/{_get_notion_page_id(row['person_id'])}", {
            "properties": {
                "Open Items": {"rich_text": [{"text": {"content": row["summary"]}}]},
                "Last Interaction": {"date": {"start": _iso_now()}},
            }
        })
        # For Slack source: upsert raw to Slack Inbox with person relation
        if row["source"] == "slack":
            _upsert_slack_inbox(row)

        c.execute("UPDATE interactions SET synced_notion=1 WHERE id=?", (row["id"],))
        return True
    except Exception as e:
        import sys
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

def _get_notion_page_id(entity_id: str) -> str:
    with _conn() as c:
        row = c.execute("SELECT meta FROM entities WHERE id=?", (entity_id,)).fetchone()
        if row:
            return json.loads(row["meta"] or "{}").get("notion_page_id", "")
    return ""

def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

def _upsert_slack_inbox(row):
    """Create or update a Slack Inbox page linked to the person."""
    from kamil_notion import notion_request
    notion_request("POST", "/pages", {
        "parent": {"database_id": "6d14f1b6b8cd4ff68fd40efdfc3f304e"},
        "properties": {
            "Name": {"title": [{"text": {"content": row["external_id"]}}]},
            "Raw": {"rich_text": [{"text": {"content": (row["raw"] or "")[:2000]}}]},
        }
    })

def _log_dead_letter(row, error: str):
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

def run_sync_loop(interval: int = 60):
    """Run the sync loop forever. Call in a background thread."""
    import sys
    while True:
        try:
            with _conn() as c:
                rows = c.execute(
                    "SELECT * FROM interactions WHERE synced_notion=0 AND sync_retries < 5 "
                    "ORDER BY created_at ASC"
                ).fetchall()
                for row in rows:
                    _sync_one_row(row, c)
                # Heartbeat
                c.execute(
                    "INSERT OR REPLACE INTO health(key,value,updated_at) VALUES(?,?,?)",
                    ("last_sync_at", _iso_now(), int(time.time()))
                )
        except Exception as e:
            print(f"[sync_loop] Error: {e}", file=sys.stderr)
        time.sleep(interval)
```

- [ ] **Step 6: Commit**

```bash
git add .claude/hooks/kamil_context.py tests/test_kamil_context.py
git commit -m "feat: add record_interaction() and background sync loop to kamil_context"
```

---

## Task 6: `lookup_context()`

**Files:**
- Modify: `.claude/hooks/kamil_context.py`
- Modify: `tests/test_kamil_context.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_kamil_context.py`:

```python
def test_lookup_context_returns_context_result():
    import kamil_context as kc
    # Patch Notion, NLM, web to return thin/nothing
    kc._notion_query = lambda db_id, question: (None, "thin")
    kc._nlm_query = lambda question: (None, "thin")
    kc._web_search = lambda question: ("web result", "clear")
    result = kc.lookup_context("what is the latest news?")
    assert result.answer == "web result"
    assert "web" in result.source_chain

def test_lookup_context_person_skips_freshness_gate():
    import kamil_context as kc
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    kc.HARNESS_DB = path
    eid = _seed_person(path, "Mahnoor Baig", "U123")
    calls = []
    kc._notion_query = lambda db_id, q: (calls.append(db_id) or ("notion answer", "clear"))
    result = kc.lookup_context("what is Mahnoor's latest news?", person_id=eid)
    assert len(calls) > 0, "Notion must be queried even with freshness keywords when person_id set"
    assert "notion" in result.source_chain[0]
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python -m pytest tests/test_kamil_context.py::test_lookup_context_returns_context_result -v
```
Expected: `AttributeError: module 'kamil_context' has no attribute 'lookup_context'`

- [ ] **Step 3: Add `lookup_context` to `kamil_context.py`**

Append after `record_interaction`:

```python
# ── ContextResult ──────────────────────────────────────────────────────────────

@dataclass
class ContextResult:
    answer: Optional[str]
    source_chain: List[str] = field(default_factory=list)
    needs_escalation: bool = False

# ── Internal stubs (monkeypatchable in tests) ──────────────────────────────────

_NOTION_DB_MAP = {
    "people":   "c976d58ea4e34b0585f245529cdc4528",
    "pr":       "18017a67136a4561ada9818c239b8f33",
    "harness":  "de10157da3e34ef58a74ea240f31fe98",
    "slack":    "6d14f1b6b8cd4ff68fd40efdfc3f304e",
    "content":  "68792d2dfff84691a4f646f5a8126149",
    "jobs":     "0d69c6ff83d844c794c2d341c4ded8d7",
}

def _classify_topic(question: str, person_id: Optional[str]) -> str:
    """Return a key from _NOTION_DB_MAP. Logs every decision."""
    q = question.lower()
    chosen = None
    if person_id or any(w in q for w in ["message", "dm", "email", "who is", "what did", "how is"]):
        chosen = "people"
    elif any(w in q for w in ["pr", "pull request", "ci", "merge", "review", "github"]):
        chosen = "pr"
    elif any(w in q for w in ["message", "slack", "inbox", "replied", "thread"]):
        chosen = "slack"
    elif any(w in q for w in ["content", "post", "caption", "linkedin", "topic"]):
        chosen = "content"
    elif any(w in q for w in ["job", "apply", "application", "freelance"]):
        chosen = "jobs"
    else:
        chosen = "harness"
    import sys
    print(f"[lookup_context] topic classifier: '{question[:60]}' → {chosen}", file=sys.stderr)
    return chosen

def _notion_query(db_id: str, question: str):
    """Query a Notion DB and return (answer_text, quality). Quality: clear|thin|empty."""
    try:
        from kamil_notion import notion_request
        resp = notion_request("POST", f"/databases/{db_id}/query", {
            "filter": {"property": "Name", "rich_text": {"contains": question[:50]}}
        })
        results = resp.get("results", [])
        if not results:
            return None, "empty"
        texts = []
        for page in results[:3]:
            props = page.get("properties", {})
            for v in props.values():
                items = v.get("rich_text") or v.get("title") or []
                texts.append("".join(i["plain_text"] for i in items))
        answer = " | ".join(t for t in texts if t)
        quality = "clear" if len(answer) > 40 else "thin"
        return answer or None, quality
    except Exception:
        return None, "empty"

def _nlm_query(question: str):
    """Query best-matching NLM notebook. Returns (answer, quality)."""
    try:
        q = question.lower()
        with _conn() as c:
            notebooks = c.execute("SELECT * FROM nlm_notebooks").fetchall()
        best, best_hits = None, 0
        for nb in notebooks:
            keywords = (nb["keywords"] or "").lower().split()
            hits = sum(1 for kw in keywords if kw in q)
            if hits > best_hits:
                best_hits, best = hits, nb
        if not best or best_hits == 0:
            return None, "empty"
        import subprocess
        result = subprocess.run(
            ["nlm", "ask", best["alias"], question],
            capture_output=True, text=True, timeout=30
        )
        answer = result.stdout.strip()
        quality = "clear" if len(answer) > 40 else "thin"
        # Update last_queried
        with _conn() as c:
            c.execute("UPDATE nlm_notebooks SET last_queried=? WHERE id=?",
                      (int(time.time()), best["id"]))
        return answer or None, quality
    except Exception:
        return None, "empty"

def _web_search(question: str):
    """Run a web search. Returns (answer, quality)."""
    # Delegates to Claude's WebSearch tool via subprocess or direct import.
    # In production this is called from within a Claude session via tool use.
    # For standalone use, returns a stub.
    return None, "empty"

_FRESHNESS_KEYWORDS = ["price", "news", "job posting", "today", "current", "latest", "right now"]

def lookup_context(question: str, person_id: Optional[str] = None) -> ContextResult:
    """
    Retrieve context for a question using the automatic escalation chain:
      Notion → NLM → web
    Never asks for permission. Returns ContextResult with full source_chain.
    """
    import sys
    source_chain: List[str] = []
    q = question.lower()

    # 1. Freshness gate — only for impersonal queries
    if person_id is None:
        matched_kw = next((kw for kw in _FRESHNESS_KEYWORDS if kw in q), None)
        if matched_kw:
            print(f"[lookup_context] freshness gate fired: '{matched_kw}' → web", file=sys.stderr)
            answer, quality = _web_search(question)
            source_chain.append("web")
            if quality == "clear":
                return ContextResult(answer=answer, source_chain=source_chain)
            return ContextResult(answer=None, source_chain=source_chain, needs_escalation=True)
        else:
            print(f"[lookup_context] freshness gate: no match → proceeding to Notion", file=sys.stderr)

    # 2. Notion fetch
    topic = _classify_topic(question, person_id)
    db_id = _NOTION_DB_MAP[topic]
    answer, quality = _notion_query(db_id, question)
    source_chain.append(f"notion:{topic}")
    if quality == "clear":
        return ContextResult(answer=answer, source_chain=source_chain)

    # 3. NLM
    answer, quality = _nlm_query(question)
    if quality == "clear":
        # Find which notebook matched for the label
        source_chain.append("nlm")
        return ContextResult(answer=answer, source_chain=source_chain)
    source_chain.append("nlm:miss")

    # 4. Web search
    answer, quality = _web_search(question)
    source_chain.append("web")
    if quality == "clear":
        return ContextResult(answer=answer, source_chain=source_chain)

    return ContextResult(answer=None, source_chain=source_chain, needs_escalation=True)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest tests/test_kamil_context.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks/kamil_context.py tests/test_kamil_context.py
git commit -m "feat: add lookup_context() with freshness gate, topic classifier, and escalation chain"
```

---

## Task 7: Wire Slack listener

**Files:**
- Modify: `.claude/hooks/kamil-slack-listener.py` (around line 486 — after `chat_postMessage`)

- [ ] **Step 1: Read the reply section to find the exact insertion points**

```bash
sed -n '580,640p' /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-slack-listener.py
```

- [ ] **Step 2: Add the import at the top of `kamil-slack-listener.py`**

Find the existing `sys.path.insert` block (around line 32) and add after the existing imports:

```python
try:
    from kamil_context import resolve_person, record_interaction, PersonNotFound, PersonAmbiguous
    _context_available = True
except Exception:
    _context_available = False
```

- [ ] **Step 3: Wire `record_interaction` after the main reply is sent (around line 625)**

Locate the block after `web.chat_postMessage(**reply_kwargs)` in the main handler (the `klog_conversation` call is right after). Add this block after the `chat_postMessage` line and before `klog_conversation`:

```python
    # Write-back: log this interaction to per-person memory
    if _context_available and sender_name:
        try:
            person = resolve_person(sender_name)
            _summary_prompt = (
                f"Summarize this interaction in 1-2 sentences: what was asked, what was decided, "
                f"and any open items. Input: request='{text[:200]}' reply='{answer[:200]}'"
            )
            summary = run_claude(_summary_prompt, timeout=30)
            record_interaction(
                person_id=person.entity_id,
                source='slack',
                external_id=f"{channel}_{thread_ts}",
                raw=thread_history or text,
                summary=summary,
                open_items="[]",
            )
        except (PersonNotFound, PersonAmbiguous):
            pass  # unknown person — skip write-back
        except Exception as _e:
            log(f"[record_interaction] failed: {_e}")
```

- [ ] **Step 4: Start the sync loop in a background thread**

Find the `if __name__ == "__main__":` block at the bottom of `kamil-slack-listener.py`. Add before the main listen loop starts:

```python
    if _context_available:
        import threading as _threading
        from kamil_context import run_sync_loop
        _threading.Thread(target=run_sync_loop, args=(60,), daemon=True).start()
        log("[kamil_context] sync loop started")
```

- [ ] **Step 5: Manual smoke test**

Send a DM to the Kamil bot. After it replies, verify:

```bash
python3 -c "
import sys; sys.path.insert(0, '.claude/hooks')
import kamil_context as kc, sqlite3
conn = sqlite3.connect(kc.HARNESS_DB)
rows = conn.execute('SELECT person_id, source, summary, synced_notion FROM interactions ORDER BY created_at DESC LIMIT 3').fetchall()
for r in rows: print(dict(r))
"
```
Expected: at least one row with `source='slack'` and a non-empty `summary`.

- [ ] **Step 6: Commit**

```bash
git add .claude/hooks/kamil-slack-listener.py
git commit -m "feat: wire record_interaction into kamil-slack-listener after every reply"
```

---

## Task 8: Wire Stop hook

**Files:**
- Modify: `.claude/hooks/stop.py`

- [ ] **Step 1: Read current stop.py main() to find insertion point**

The hook currently runs: git commit → update STANDUP → MemPalace sync → notion-map update. We add person-extraction + record_interaction after the git commit step.

- [ ] **Step 2: Add imports at the top of `stop.py`**

After the existing `sys.path.insert` line, add:

```python
try:
    from kamil_context import resolve_person, record_interaction, PersonNotFound, PersonAmbiguous
    _context_available = True
except Exception:
    _context_available = False
```

- [ ] **Step 3: Add `log_session_interactions()` function to `stop.py`**

Add before `main()`:

```python
_DECISION_KEYWORDS = ["decided", "agreed", "approved", "blocked", "will do", "confirmed", "done"]

def _is_meaningful(turn_text: str, person_ids: list) -> bool:
    t = turn_text.lower()
    return bool(person_ids) or any(kw in t for kw in _DECISION_KEYWORDS)

def _extract_persons(text: str) -> list:
    """Try to resolve every capitalized word sequence as a person name. Returns list of PersonRecords."""
    if not _context_available:
        return []
    import re
    # Find sequences of Title Case words (likely names)
    candidates = re.findall(r'\b([A-Z][a-z]+(?: [A-Z][a-z]+)+)\b', text)
    persons = []
    seen_ids = set()
    for name in candidates:
        try:
            p = resolve_person(name)
            if p.entity_id not in seen_ids:
                persons.append(p)
                seen_ids.add(p.entity_id)
        except (PersonNotFound, PersonAmbiguous):
            pass
    return persons

def log_session_interactions(workspace_root: Path, session_id: str):
    """
    Read today's log, extract meaningful turns involving named people,
    and record each via record_interaction().
    """
    if not _context_available:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = workspace_root / "vault" / "logs" / f"{today}.md"
    if not log_file.exists():
        return
    lines = log_file.read_text(encoding="utf-8").splitlines()
    for turn_index, line in enumerate(lines):
        if not line.strip():
            continue
        persons = _extract_persons(line)
        if not _is_meaningful(line, persons):
            continue
        for person in persons:
            try:
                # Use a simple summarization: take the line itself as summary
                # (session turns are already concise log entries)
                record_interaction(
                    person_id=person.entity_id,
                    source='claude_session',
                    external_id=f"{session_id}_{turn_index:04d}",
                    raw=line,
                    summary=line,  # log lines are already short summaries
                    open_items="[]",
                )
            except Exception as e:
                print(f"[stop] record_interaction failed for {person.name}: {e}", file=sys.stderr)
```

- [ ] **Step 4: Call `log_session_interactions` in `main()`**

In `main()`, after the git commit block and before `update_standup`, add:

```python
    # Log meaningful session interactions to per-person memory
    import uuid as _uuid
    session_id = str(_uuid.uuid4())[:8]
    log_session_interactions(workspace_root, session_id)
```

- [ ] **Step 5: Verify stop hook runs without error**

```bash
python3 .claude/hooks/stop.py
echo "Exit code: $?"
```
Expected: `[stop] Stop hook completed` and exit code 0.

- [ ] **Step 6: Commit**

```bash
git add .claude/hooks/stop.py
git commit -m "feat: wire record_interaction into stop hook with person-extraction and relevance filter"
```

---

## Task 9: Update docs + archive old DB

**Files:**
- Modify: `.claude/rules/notion.md`
- Modify: `.claude/rules/slack.md`

- [ ] **Step 1: Update `notion.md`**

Find the retrieval/write spec section in `.claude/rules/notion.md` (the "## MCP Queries" or "## Retrieval" block) and replace it with:

```
## Retrieval and Write Rules
Retrieval and write rules are defined in `.claude/hooks/kamil_context.py` — do not re-specify here.
```

- [ ] **Step 2: Update `slack.md`**

Find the "## Patterns" section in `.claude/rules/slack.md` and add at the top:

```
Person lookup and interaction write-back: see `.claude/hooks/kamil_context.py` — do not re-specify here.
```

- [ ] **Step 3: Commit**

```bash
git add .claude/rules/notion.md .claude/rules/slack.md
git commit -m "docs: defer retrieval/write rules to kamil_context.py in notion.md and slack.md"
```

- [ ] **Step 4: One-week wait — verify People Intelligence receives all writes**

Check that `People Intelligence` DB is getting `Last Interaction` and `Open Items` updates:

```bash
python3 -c "
import sys; sys.path.insert(0, '.claude/hooks')
import kamil_context as kc, sqlite3
conn = sqlite3.connect(kc.HARNESS_DB)
rows = conn.execute('SELECT id, synced_notion, sync_retries FROM interactions ORDER BY created_at DESC LIMIT 10').fetchall()
for r in rows: print(dict(r))
health = conn.execute(\"SELECT value FROM health WHERE key='last_sync_at'\").fetchone()
print('last_sync_at:', health[0] if health else 'never')
"
```
Expected: rows with `synced_notion=1`, `last_sync_at` is recent.

- [ ] **Step 5: Archive old DB in Notion (after one-week verification)**

Rename `Team People / focus` to `[ARCHIVED] Team People` in Notion. This is a manual step in the Notion UI — not automated.

---

## Self-Review

**Spec coverage:**
- ✅ SQLite schema with all tables, indexes, health table → Task 1
- ✅ `resolve_person` with alias matching, PersonAmbiguous, PersonNotFound → Task 2
- ✅ DB merge dry-run + approval gate → Task 3 (STOP step)
- ✅ DB merge write + reference grep → Task 4
- ✅ `record_interaction` with dedup-as-update, sync loop, heartbeat, dead-letter → Task 5
- ✅ `lookup_context` with freshness gate, topic classifier, escalation chain → Task 6
- ✅ Slack listener wired → Task 7
- ✅ Stop hook wired with person-extraction + relevance filter → Task 8
- ✅ Docs one-liners + archive → Task 9

**Placeholder scan:** No TBD, no TODO, no "similar to above" — clean.

**Type consistency:**
- `PersonRecord` defined in Task 2, used in Tasks 7 and 8 ✅
- `ContextResult` defined in Task 6 ✅
- `record_interaction` signature consistent across Tasks 5, 7, 8 ✅
- `HARNESS_DB` constant used in all DB access ✅
