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

def test_log_suppression_writes_to_db():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    kc.log_suppression(
        event_id='evt_sup_001',
        reason_code='no_url_in_context',
        raw_text='review this PR',
        channel='C01',
        sender_id='U01',
    )
    conn = sqlite3.connect(kc.HARNESS_DB)
    row = conn.execute(
        "SELECT reason_code FROM suppression_log WHERE event_id='evt_sup_001'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 'no_url_in_context'

def test_log_milestone_updates_steps_done():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    job_id = kc.create_job(event_id='evt_ms_001', source='slack_mention', steps_total=3)
    kc.log_milestone(job_id, 'fetch_thread', 1, 3, 'completed')
    conn = sqlite3.connect(kc.HARNESS_DB)
    row = conn.execute("SELECT steps_done FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    assert row[0] == 1

def test_extract_pr_url_from_trigger():
    import kamil_context as kc
    url = kc.extract_pr_url(
        trigger_text='please review https://github.com/Orenda-Project/taleemabad-core/pull/5151',
        thread_context=''
    )
    assert url == 'https://github.com/Orenda-Project/taleemabad-core/pull/5151'

def test_extract_pr_url_from_thread():
    import kamil_context as kc
    url = kc.extract_pr_url(
        trigger_text='@Kamil review this PR',
        thread_context='[123.456] <U01>: https://github.com/Orenda-Project/taleemabad-core/pull/5151\n@channel Please review.'
    )
    assert url == 'https://github.com/Orenda-Project/taleemabad-core/pull/5151'

def test_extract_pr_url_returns_none_when_missing():
    import kamil_context as kc
    url = kc.extract_pr_url(trigger_text='review this', thread_context='no url here')
    assert url is None

def test_fetch_thread_context_returns_empty_on_failure():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    class FakeWeb:
        def conversations_replies(self, **kwargs):
            raise Exception("Network error")
    result = kc.fetch_thread_context('C01', '123.456', FakeWeb(), event_id='evt_ft_001')
    assert result == ''

def test_tracked_thread_marks_delivered():
    import kamil_context as kc, time as _time
    kc.HARNESS_DB = make_test_db()
    job_id = kc.create_job(event_id='evt_tt_001', source='slack_mention')
    results = []
    def _work():
        results.append('done')
    t = kc.tracked_thread(job_id, _work)
    t.join(timeout=3)
    assert 'done' in results
    conn = sqlite3.connect(kc.HARNESS_DB)
    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    assert row[0] == 'delivered'

def test_tracked_thread_marks_failed_on_exception():
    import kamil_context as kc
    kc.HARNESS_DB = make_test_db()
    job_id = kc.create_job(event_id='evt_tt_002', source='slack_mention')
    def _work():
        raise ValueError("boom")
    t = kc.tracked_thread(job_id, _work)
    t.join(timeout=3)
    conn = sqlite3.connect(kc.HARNESS_DB)
    row = conn.execute("SELECT status, failure_reason FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    assert row[0] == 'failed'
    assert 'boom' in row[1]

def test_stale_job_checker_marks_timed_out():
    import kamil_context as kc, time as _t, sqlite3
    kc.HARNESS_DB = make_test_db()
    job_id = kc.create_job(event_id='evt_stale_001', source='slack_mention')
    conn = sqlite3.connect(kc.HARNESS_DB)
    conn.execute("UPDATE jobs SET status='processing', created_at=? WHERE id=?",
                 (int(_t.time()) - 400, job_id))
    conn.commit()
    conn.close()
    count = kc.check_and_mark_stale_jobs(threshold_seconds=300)
    assert count >= 1
    conn = sqlite3.connect(kc.HARNESS_DB)
    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    assert row[0] == 'timed_out'
