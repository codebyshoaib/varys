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

import uuid
import json

def _seed_person(path, name, slack_id, aliases=None):
    """Helper: insert a person entity directly into the test DB."""
    import kamil_context as kc
    kc.HARNESS_DB = path
    kc.init_schema()
    import sqlite3
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
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    import kamil_context as kc
    kc.HARNESS_DB = path
    eid = _seed_person(path, "Mahnoor Baig", "U123")
    result = kc.resolve_person("Mahnoor Baig")
    assert result.entity_id == eid
    assert result.slack_id == "U123"

def test_resolve_person_alias():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    import kamil_context as kc
    kc.HARNESS_DB = path
    eid = _seed_person(path, "Mahnoor Baig", "U123", aliases=["Mahnoor", "@m.baig"])
    result = kc.resolve_person("Mahnoor")
    assert result.entity_id == eid

def test_resolve_person_not_found_raises():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    import kamil_context as kc
    kc.HARNESS_DB = path
    kc.init_schema()
    kc._notion_fetch_person = lambda name: None
    try:
        kc.resolve_person("Nobody Here")
        assert False, "Should have raised PersonNotFound"
    except kc.PersonNotFound:
        pass

def test_resolve_person_ambiguous_raises():
    import tempfile
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
