#!/usr/bin/env python3
"""
test_slack_queue_drain.py — thin self-check for the slack_queue drainer.

COVERAGE IS THIN BY DESIGN: this hook is almost entirely I/O — it dequeues rows, marks
them processing, and fans out one slack-worker.py subprocess per row in threads. It exposes
no pure transform to test. So this is a smoke test (import + key callables + the
MAX_CONCURRENT bound) PLUS one genuine cross-module invariant worth pinning:

  _run_job unpacks the dequeued row into EXACTLY 14 named fields. Those rows come from
  varys_harness_db.dequeue_pending_slack, whose SELECT returns 14 columns. If either side
  changes arity the unpack throws at runtime for every job. We assert the contract here by
  reading the real column count from a hermetic in-memory DB (never the live harness.db).

Run: python3 .claude/hooks/test_slack_queue_drain.py
"""
import importlib.util
import sqlite3
import sys
from pathlib import Path

HOOKS = Path(__file__).parent
sys.path.insert(0, str(HOOKS))
spec = importlib.util.spec_from_file_location("slack_queue_drain", HOOKS / "slack-queue-drain.py")
sqd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sqd)

import varys_harness_db as hdb
hdb._bd = lambda *a, **kw: ""  # no bd subprocess


def test_smoke_callables_and_bound():
    assert callable(getattr(sqd, "main", None))
    assert callable(getattr(sqd, "_run_job", None))
    # bounded concurrency so a backlog can't fork-bomb the box
    assert sqd.MAX_CONCURRENT == 3, sqd.MAX_CONCURRENT
    print("PASS test_smoke_callables_and_bound")


def test_dequeue_row_arity_matches_worker_unpack():
    """_run_job destructures the row into 14 fields; dequeue_pending_slack must return 14."""
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.executescript(hdb._SCHEMA)
    db.commit()
    hdb.migrate_db(db)
    db.execute("INSERT INTO slack_queue (id, source, channel, thread_ts, text) "
               "VALUES ('j','rt','C','1','hi')")
    db.commit()
    rows = hdb.dequeue_pending_slack(db, limit=1)
    assert len(rows) == 1, "expected one pending row"
    assert len(rows[0]) == 14, f"dequeue must return 14 columns (drain unpacks 14); got {len(rows[0])}"
    print("PASS test_dequeue_row_arity_matches_worker_unpack")


if __name__ == "__main__":
    test_smoke_callables_and_bound()
    test_dequeue_row_arity_matches_worker_unpack()
    print("\nALL SLACK_QUEUE_DRAIN TESTS PASSED")
