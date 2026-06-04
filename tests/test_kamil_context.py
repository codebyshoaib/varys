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

def test_record_interaction_synced_notion_default_zero():
    import tempfile, sqlite3
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    import kamil_context as kc
    kc.HARNESS_DB = path
    eid = _seed_person(path, "Mahnoor Baig", "U123")
    iid = kc.record_interaction(eid, 'slack', 'C_test_1', 'raw', 'summary', '[]')
    conn = sqlite3.connect(path)
    row = conn.execute("SELECT synced_notion, sync_retries FROM interactions WHERE id=?", (iid,)).fetchone()
    conn.close()
    assert row[0] == 0   # not yet synced
    assert row[1] == 0   # no retries

def test_sync_one_row_dead_letter_after_5_failures():
    import tempfile, sqlite3
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    import kamil_context as kc
    kc.HARNESS_DB = path
    eid = _seed_person(path, "Mahnoor Baig", "U123")
    iid = kc.record_interaction(eid, 'slack', 'C_test_dl', 'raw', 'summary', '[]')
    # Simulate 4 failures bringing retries to 4
    conn = sqlite3.connect(path)
    conn.execute("UPDATE interactions SET sync_retries=4 WHERE id=?", (iid,))
    conn.commit()
    # Patch kamil_notion to raise so _sync_one_row fails
    import sys
    sys.modules['kamil_notion'] = type(sys)('kamil_notion')
    sys.modules['kamil_notion'].notion_request = lambda *a, **kw: (_ for _ in ()).throw(Exception("Notion down"))
    row_obj = conn.execute("SELECT * FROM interactions WHERE id=?", (iid,)).fetchone()
    # Convert to dict-like using sqlite3.Row
    conn.row_factory = sqlite3.Row
    row_obj = conn.execute("SELECT * FROM interactions WHERE id=?", (iid,)).fetchone()
    kc._sync_one_row(row_obj, conn)
    conn.commit()
    final = conn.execute("SELECT synced_notion, sync_retries FROM interactions WHERE id=?", (iid,)).fetchone()
    conn.close()
    assert final[0] == -1   # dead-letter
    assert final[1] == 5    # retries maxed

def test_lookup_context_web_fallback():
    import kamil_context as kc
    orig_notion = kc._notion_query
    orig_nlm = kc._nlm_query
    orig_web = kc._web_search
    kc._notion_query = lambda db_id, question: (None, "thin")
    kc._nlm_query = lambda question: (None, "thin")
    kc._web_search = lambda question: ("web result", "clear")
    try:
        result = kc.lookup_context("what is the latest news?")
        assert result.answer == "web result"
        assert "web" in result.source_chain
    finally:
        kc._notion_query = orig_notion
        kc._nlm_query = orig_nlm
        kc._web_search = orig_web

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

def test_suppression_log_columns():
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

def test_lookup_context_person_skips_freshness_gate():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        path = f.name
    import kamil_context as kc
    kc.HARNESS_DB = path
    eid = _seed_person(path, "Mahnoor Baig", "U123")
    calls = []
    orig_notion = kc._notion_query
    orig_web = kc._web_search
    kc._notion_query = lambda db_id, q: (calls.append(db_id) or ("notion answer", "clear"))
    kc._web_search = lambda q: ("web answer", "clear")
    try:
        result = kc.lookup_context("what is Mahnoor's latest news?", person_id=eid)
        assert len(calls) > 0, "Notion must be queried even with freshness keywords when person_id set"
        assert "notion" in result.source_chain[0]
    finally:
        kc._notion_query = orig_notion
        kc._web_search = orig_web
