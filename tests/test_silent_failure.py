import sqlite3, os, sys, tempfile, json, time, uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '.claude', 'hooks'))

def make_test_db():
    import kamil_context as kc
    f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    kc.HARNESS_DB = f.name
    kc.init_schema()
    return f.name

def test_create_job_returns_id():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    job_id = kc.create_job(
        event_id='evt_001',
        source='slack_mention',
        intent='pr_review',
        raw_text='review this PR',
        channel='C01',
        thread_ts='123.456',
        sender_id='U01',
    )
    assert job_id is not None
    assert len(job_id) == 64  # sha256 hex

def test_create_job_idempotent():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    id1 = kc.create_job(event_id='evt_002', source='slack_mention')
    id2 = kc.create_job(event_id='evt_002', source='slack_mention')
    assert id1 == id2

def test_mark_job_delivered():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    job_id = kc.create_job(event_id='evt_003', source='slack_mention')
    kc.mark_job_delivered(job_id)
    conn = sqlite3.connect(kc.HARNESS_DB)
    row = conn.execute("SELECT status, delivered_at FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    assert row[0] == 'delivered'
    assert row[1] is not None

def test_mark_job_failed():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    job_id = kc.create_job(event_id='evt_004', source='slack_mention')
    kc.mark_job_failed(job_id, 'no_url_in_context')
    conn = sqlite3.connect(kc.HARNESS_DB)
    row = conn.execute("SELECT status, failure_reason FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    assert row[0] == 'failed'
    assert row[1] == 'no_url_in_context'

def test_get_stale_jobs():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    job_id = kc.create_job(event_id='evt_005', source='slack_mention')
    # backdate created_at to simulate stale
    conn = sqlite3.connect(kc.HARNESS_DB)
    conn.execute("UPDATE jobs SET status='processing', created_at=? WHERE id=?",
                 (int(time.time()) - 400, job_id))
    conn.commit()
    conn.close()
    stale = kc.get_stale_jobs(threshold_seconds=300)
    assert any(j['id'] == job_id for j in stale)

def test_mark_job_processing():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    job_id = kc.create_job(event_id='evt_006', source='slack_mention')
    kc.mark_job_processing(job_id)
    conn = sqlite3.connect(kc.HARNESS_DB)
    row = conn.execute("SELECT status, updated_at FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    assert row[0] == 'processing'
    assert row[1] is not None
