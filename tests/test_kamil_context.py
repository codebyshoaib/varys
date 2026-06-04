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
    orig = kc._notion_fetch_person
    kc._notion_fetch_person = lambda name: None
    try:
        kc.resolve_person("Nobody Here")
        assert False, "Should have raised PersonNotFound"
    except kc.PersonNotFound:
        pass
    finally:
        kc._notion_fetch_person = orig

def test_resolve_person_ambiguous_raises():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    import kamil_context as kc
    kc.HARNESS_DB = path
    _seed_person(path, "Mah Noor", "U111", aliases=["Mahnoor"])
    _seed_person(path, "Mahnoor Khan", "U222", aliases=["Mahnoor"])
    orig = kc._notion_fetch_person
    kc._notion_fetch_person = lambda name: None
    try:
        kc.resolve_person("Mahnoor")
        assert False, "Should have raised PersonAmbiguous"
    except kc.PersonAmbiguous as e:
        assert len(e.candidates) >= 2
    finally:
        kc._notion_fetch_person = orig

def test_record_interaction_inserts():
    import tempfile, json
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    import kamil_context as kc
    kc.HARNESS_DB = path
    import sqlite3
    eid = _seed_person(path, "Mahnoor Baig", "U123")
    iid = kc.record_interaction(
        person_id=eid, source='slack',
        external_id='C01_1234567890.000100',
        raw='test thread', summary='Mahnoor asked about sprint',
        open_items=json.dumps(['Follow up on ticket'])
    )
    conn = sqlite3.connect(path)
    row = conn.execute("SELECT * FROM interactions WHERE id=?", (iid,)).fetchone()
    conn.close()
    assert row is not None

def test_record_interaction_dedup():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    import kamil_context as kc
    kc.HARNESS_DB = path
    eid = _seed_person(path, "Mahnoor Baig", "U123")
    ext_id = 'C01_9999999999.000100'
    id1 = kc.record_interaction(eid, 'slack', ext_id, 'raw1', 'summary1', '[]')
    id2 = kc.record_interaction(eid, 'slack', ext_id, 'raw2-updated', 'summary2-updated', '[]')
    assert id1 == id2  # same thread → same id
    import sqlite3
    conn = sqlite3.connect(path)
    row = conn.execute("SELECT raw FROM interactions WHERE id=?", (id1,)).fetchone()
    conn.close()
    assert 'updated' in row[0]  # row was updated, not duplicated
