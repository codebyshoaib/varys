#!/usr/bin/env python3
"""
test_slack_queue.py — Regression test for the live Slack queue's idempotency +
lease-based retry machinery in varys_harness_db.py.

Locks in the P1 varys-lc7 fix (ack-spam / infinite re-run): the "On it" ack is
posted at most once EVER, a slow-but-alive worker is never re-dispatched under
itself, and a job that never succeeds dead-letters instead of looping forever.

Hermetic: points the module at a throwaway temp DB and stubs `_bd` so nothing
touches the real harness.db or shells out to beads. Asserts only, no framework.
Run: python3 .claude/hooks/test_slack_queue.py
"""
import importlib
import sys
import tempfile
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOKS))

import varys_harness_db as db_mod  # underscore module name — importable directly

# Redirect all DB I/O to a throwaway dir and neuter the beads side-effect.
_TMP = Path(tempfile.mkdtemp(prefix="slack-queue-test-"))
db_mod.HARNESS_DIR = _TMP
db_mod.HARNESS_DB = _TMP / "harness.db"
db_mod._bd = lambda *a, **k: ""  # no real beads created/claimed/closed


def _reset():
    """Fresh DB for each test — unlink the file so get_db() rebuilds the schema."""
    if db_mod.HARNESS_DB.exists():
        db_mod.HARNESS_DB.unlink()
    return db_mod.get_db()


def _insert(db, row_id, status="pending", retry_count=0, ack_posted=0,
            lease_offset=None):
    """Insert one slack_queue row. lease_offset (seconds) sets lease_expires_at
    relative to now; None leaves it NULL."""
    lease = f"datetime('now', '{lease_offset:+d} seconds')" if lease_offset is not None else "NULL"
    db.execute(
        f"INSERT INTO slack_queue (id, source, channel, thread_ts, text, "
        f"status, retry_count, ack_posted, lease_expires_at) "
        f"VALUES (?, 'slack', 'C1', 'ts1', 'hi', ?, ?, ?, {lease})",
        (row_id, status, retry_count, ack_posted),
    )
    db.commit()


def _status(db, row_id):
    return db.execute("SELECT status FROM slack_queue WHERE id=?", (row_id,)).fetchone()[0]


def _retries(db, row_id):
    return db.execute("SELECT retry_count FROM slack_queue WHERE id=?", (row_id,)).fetchone()[0]


# --- idempotent ack (the varys-lc7 core) ------------------------------------

def test_try_ack_true_exactly_once():
    """slack_try_ack returns True on the first claim and False forever after —
    so a job dispatched more than once never double-posts the 'On it' ack."""
    db = _reset()
    _insert(db, "j1")
    assert db_mod.slack_try_ack(db, "j1") is True
    assert db_mod.slack_try_ack(db, "j1") is False
    assert db_mod.slack_try_ack(db, "j1") is False


def test_enqueue_dedup_prevents_second_queue_row():
    """Same event id enqueued twice -> second is a no-op (INSERT OR IGNORE), so a
    re-delivered Slack event can't spawn a duplicate job (and duplicate ack)."""
    db = _reset()
    args = dict(source="slack", channel="C1", thread_ts="ts9", sender_id="U",
                sender_name="Shoaib", text="fix X", thread_history="",
                is_dm=False, is_third_party=False)
    assert db_mod.enqueue_slack_mention(db, "dup1", **args) is True
    assert db_mod.enqueue_slack_mention(db, "dup1", **args) is False
    n = db.execute("SELECT COUNT(*) FROM slack_queue WHERE id='dup1'").fetchone()[0]
    assert n == 1, n


# --- retry / dead-letter -----------------------------------------------------

def test_retry_increments_then_dead_letters():
    """mark_slack_retry keeps the job 'pending' (retry_count++) below the cap,
    then flips to 'failed' at the cap — a job that never succeeds can't loop."""
    db = _reset()
    _insert(db, "r1")
    for expected in (1, 2, 3):
        db_mod.mark_slack_retry(db, "r1", max_retries=3, failure_context="boom")
        assert _status(db, "r1") == "pending", expected
        assert _retries(db, "r1") == expected
    # retry_count is now 3 == max_retries -> next call dead-letters.
    db_mod.mark_slack_retry(db, "r1", max_retries=3, failure_context="boom")
    assert _status(db, "r1") == "failed"


# --- lease-based reclaim (migrate_db Migration 003) --------------------------

def test_expired_lease_reclaimed_to_pending():
    """A 'processing' job whose lease has expired (crashed/hung worker) is
    reclaimed to 'pending' with retry_count++ on the next get_db()/migrate."""
    db = _reset()
    _insert(db, "e1", status="processing", retry_count=0, lease_offset=-30)
    db_mod.migrate_db(db)
    assert _status(db, "e1") == "pending"
    assert _retries(db, "e1") == 1
    lease = db.execute("SELECT lease_expires_at FROM slack_queue WHERE id='e1'").fetchone()[0]
    assert lease is None


def test_expired_lease_dead_letters_after_max_retries():
    """Expired lease + retry_count>=3 -> 'failed', not another reclaim. This is
    the infinite-ack backstop: a perpetually-failing job stops re-dispatching."""
    db = _reset()
    _insert(db, "e2", status="processing", retry_count=3, lease_offset=-30)
    db_mod.migrate_db(db)
    assert _status(db, "e2") == "failed"


def test_live_lease_not_reclaimed():
    """A 'processing' job with a still-valid lease (slow-but-alive worker) is
    left alone — never re-dispatched under itself. The key correctness property."""
    db = _reset()
    _insert(db, "e3")
    db_mod.mark_slack_processing(db, "e3")  # sets lease to now + SLACK_LEASE_SECONDS
    db_mod.migrate_db(db)
    assert _status(db, "e3") == "processing"
    assert _retries(db, "e3") == 0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"\n{failed} TEST(S) FAILED")
        sys.exit(1)
    print(f"\nALL {len(tests)} SLACK-QUEUE TESTS PASSED")
