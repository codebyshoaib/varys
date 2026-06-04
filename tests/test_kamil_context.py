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
