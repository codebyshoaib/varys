#!/usr/bin/env python3
"""
test_meeting_queue.py — Unit tests for meeting_queue DB functions.

Tests:
  - enqueue_meeting + dequeue_pending_meeting round-trip
  - dequeue_pending_meeting returns None on empty queue
  - mark_meeting_processing / mark_meeting_done lifecycle
  - mark_meeting_retry increments retry_count and eventually marks failed
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# Resolve hooks directory and insert at the front of sys.path so that
# varys_harness_db imports cleanly without needing the real harness.db.
HOOKS = Path(__file__).resolve().parent.parent / ".claude" / "hooks"
sys.path.insert(0, str(HOOKS))

import varys_harness_db as hdb


def _make_test_db() -> sqlite3.Connection:
    """Create an in-memory (temp file) harness DB for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    # Patch HARNESS_DB so get_db() writes to our temp file
    with patch.object(hdb, "HARNESS_DB", db_path):
        with patch.object(hdb, "HARNESS_DIR", db_path.parent):
            db = hdb.get_db()
    return db


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_enqueue_and_dequeue_round_trip():
    """enqueue_meeting followed by dequeue_pending_meeting returns the same job."""
    db = _make_test_db()

    job_id = hdb.enqueue_meeting(
        db,
        meeting_name="test-meeting",
        audio_path="/tmp/test.flac",
        output_dir="/tmp/output",
        channel="C123456",
        thread_ts="1234567890.000100",
    )
    assert job_id, "enqueue_meeting must return a non-empty job_id"

    row = hdb.dequeue_pending_meeting(db)
    assert row is not None, "dequeue_pending_meeting must return a row after enqueue"

    row_id, meeting_name, audio_path, output_dir, channel, thread_ts, retry_count, failure_context = row
    assert row_id == job_id
    assert meeting_name == "test-meeting"
    assert audio_path == "/tmp/test.flac"
    assert output_dir == "/tmp/output"
    assert channel == "C123456"
    assert thread_ts == "1234567890.000100"
    assert retry_count == 0
    assert failure_context is None


def test_dequeue_returns_none_on_empty_queue():
    """dequeue_pending_meeting must return None when the queue has no pending jobs."""
    db = _make_test_db()
    row = hdb.dequeue_pending_meeting(db)
    assert row is None, "dequeue_pending_meeting must return None on empty queue"


def test_mark_processing_and_done_lifecycle():
    """mark_meeting_processing + mark_meeting_done change status correctly."""
    db = _make_test_db()
    job_id = hdb.enqueue_meeting(
        db, "lifecycle-test", "/tmp/a.flac", "/tmp/out", "C1", "1.0"
    )

    hdb.mark_meeting_processing(db, job_id)
    status = db.execute(
        "SELECT status FROM meeting_queue WHERE id=?", (job_id,)
    ).fetchone()[0]
    assert status == "processing"

    hdb.mark_meeting_done(db, job_id)
    status, processed_at = db.execute(
        "SELECT status, processed_at FROM meeting_queue WHERE id=?", (job_id,)
    ).fetchone()
    assert status == "done"
    assert processed_at is not None, "processed_at must be set on done"


def test_dequeue_does_not_return_processing_job():
    """A job already marked processing must not be returned by dequeue."""
    db = _make_test_db()
    job_id = hdb.enqueue_meeting(
        db, "proc-test", "/tmp/b.flac", "/tmp/out", "C1", "1.0"
    )
    hdb.mark_meeting_processing(db, job_id)

    row = hdb.dequeue_pending_meeting(db)
    assert row is None, "processing job must not be dequeued again"


def test_mark_retry_increments_count():
    """mark_meeting_retry increments retry_count and resets to pending."""
    db = _make_test_db()
    job_id = hdb.enqueue_meeting(
        db, "retry-test", "/tmp/c.flac", "/tmp/out", "C1", "1.0"
    )
    hdb.mark_meeting_processing(db, job_id)

    hdb.mark_meeting_retry(db, job_id, max_retries=3, failure_context="boom")
    status, retry_count, failure_ctx = db.execute(
        "SELECT status, retry_count, failure_context FROM meeting_queue WHERE id=?",
        (job_id,),
    ).fetchone()
    assert status == "pending"
    assert retry_count == 1
    assert failure_ctx == "boom"


def test_mark_retry_exhausted_marks_failed():
    """mark_meeting_retry marks status=failed after max_retries exhausted."""
    db = _make_test_db()
    job_id = hdb.enqueue_meeting(
        db, "exhausted-test", "/tmp/d.flac", "/tmp/out", "C1", "1.0"
    )
    hdb.mark_meeting_processing(db, job_id)

    # Simulate 3 prior retries by updating directly
    db.execute(
        "UPDATE meeting_queue SET retry_count=3 WHERE id=?", (job_id,)
    )
    db.commit()

    hdb.mark_meeting_retry(db, job_id, max_retries=3, failure_context="final failure")
    status = db.execute(
        "SELECT status FROM meeting_queue WHERE id=?", (job_id,)
    ).fetchone()[0]
    assert status == "failed"


def test_fifo_ordering():
    """dequeue_pending_meeting returns the oldest enqueued pending job first."""
    db = _make_test_db()
    id1 = hdb.enqueue_meeting(db, "first",  "/tmp/1.flac", "/tmp/out", "C1", "1.0")
    id2 = hdb.enqueue_meeting(db, "second", "/tmp/2.flac", "/tmp/out", "C1", "2.0")

    row = hdb.dequeue_pending_meeting(db)
    assert row is not None
    # The first enqueued job must be dequeued first
    assert row[0] == id1, f"Expected first job {id1}, got {row[0]}"


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_enqueue_and_dequeue_round_trip,
        test_dequeue_returns_none_on_empty_queue,
        test_mark_processing_and_done_lifecycle,
        test_dequeue_does_not_return_processing_job,
        test_mark_retry_increments_count,
        test_mark_retry_exhausted_marks_failed,
        test_fifo_ordering,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
