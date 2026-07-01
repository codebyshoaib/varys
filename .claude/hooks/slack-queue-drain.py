#!/usr/bin/env python3
"""
slack-queue-drain.py — Drain up to 3 pending slack_queue jobs concurrently.

Called by varys-tick.py after orchestrator-dispatch.py.
Each job runs in its own subprocess (slack-worker.py) so sessions are isolated.
"""
import subprocess
import sys
import threading
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
REPO  = HOOKS.parent.parent
sys.path.insert(0, str(HOOKS))

from varys_harness_db import get_db, dequeue_pending_slack, mark_slack_processing, mark_slack_retry

MAX_CONCURRENT = 3


def _run_job(row: tuple, db_path: str) -> None:
    """Run slack-worker.py for one job; mark retry on failure."""
    import sqlite3
    from varys_harness_db import get_db as _get_db, mark_slack_retry as _retry

    (row_id, source, channel, thread_ts, sender_id, sender_name,
     text, thread_history, is_dm, is_third_party, job_id, retry_count,
     priority, failure_context) = row

    # Backstop timeout MUST exceed the worker's own longest timeout (900s for the
    # PR-reviewer in slack-worker.py). If it's shorter, subprocess.run SIGKILLs the
    # worker before it can mark the job done — leaving it 'processing' to be reclaimed
    # and re-run forever. Let the worker own its lifecycle; this is only a last resort.
    try:
        result = subprocess.run(
            ["python3", str(HOOKS / "slack-worker.py"), "--job-id", row_id],
            capture_output=True, text=True,
            cwd=str(REPO), timeout=960,
        )
    except subprocess.TimeoutExpired:
        db = _get_db()
        _retry(db, row_id, failure_context="drain backstop: worker exceeded 960s")
        print(f"[drain] {row_id} hit 960s backstop, retry queued (capped)")
        return

    if result.returncode != 0:
        ctx = (result.stderr.strip() or result.stdout.strip())[:1000]
        db = _get_db()
        _retry(db, row_id, failure_context=ctx)
        print(f"[drain] {row_id} failed (rc={result.returncode}), retry queued: {ctx[:120]}")
    else:
        # worker already marked done
        print(f"[drain] {row_id} done")


def main() -> int:
    db   = get_db()
    rows = dequeue_pending_slack(db, limit=MAX_CONCURRENT)
    if not rows:
        return 0

    print(f"[drain] {len(rows)} job(s) to process")

    # Mark all as processing before spawning so the next tick doesn't re-pick them
    for row in rows:
        mark_slack_processing(db, row[0])

    threads = [
        threading.Thread(target=_run_job, args=(row, str(db)), daemon=False)
        for row in rows
    ]
    for t in threads:
        t.start()
    for t in threads:
        # ponytail: join must outlast the 960s worker backstop so main() doesn't
        # return while a review is still in flight (threads are non-daemon anyway).
        t.join(timeout=1000)

    return 0


if __name__ == "__main__":
    sys.exit(main())
