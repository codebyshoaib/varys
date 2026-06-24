#!/usr/bin/env python3
"""
test_varys_harness_db.py — hermetic self-check for the orchestrator's shared SQLite layer.

Hermetic: builds an in-memory sqlite DB from the module's own _SCHEMA + migrate_db (so it
NEVER touches the live ~/.varys-harness/harness.db), and monkeypatches the module's _bd()
so NO `bd` subprocess is ever spawned. All functions under test take a db connection arg,
so we pass our in-memory connection directly and never call get_db().

Covers the load-bearing invariants this module owns:
  - tick-lock acquire / re-entrancy / stale-lock (>1800s) clearing  (rule 6: one tick at a time)
  - register_entity idempotency via UNIQUE(source, external_id)     (deterministic entities)
  - link / get_linked_entities (both directions, excludes self)
  - sync_state get/set round-trip                                   (last_sync_at)
  - slack_queue dequeue ordering: priority DESC, then FIFO          (fast-path replies)
  - slack-queue retry → exhaustion → 'failed' status math

Run: python3 .claude/hooks/test_varys_harness_db.py
"""
import importlib.util
import sqlite3
import sys
from pathlib import Path

HOOKS = Path(__file__).parent
spec = importlib.util.spec_from_file_location("varys_harness_db", HOOKS / "varys_harness_db.py")
hdb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hdb)

# Neutralise the bd subprocess entirely — the queue helpers call _bd() to mint/close beads.
hdb._bd = lambda *a, **kw: ""


def _fresh_db() -> sqlite3.Connection:
    """In-memory DB seeded with the real schema + migrations — never the live file."""
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.executescript(hdb._SCHEMA)
    db.commit()
    hdb.migrate_db(db)
    return db


def test_tick_lock_reentrancy_and_release():
    db = _fresh_db()
    assert hdb.acquire_tick_lock(db, "a") is True, "first acquire must succeed"
    assert hdb.acquire_tick_lock(db, "b") is False, "second acquire must fail (one tick at a time)"
    hdb.release_tick_lock(db)
    assert hdb.acquire_tick_lock(db, "c") is True, "after release, acquire must succeed again"
    print("PASS test_tick_lock_reentrancy_and_release")


def test_tick_lock_stale_is_stolen():
    """A lock older than 1800s is cleared on the next acquire (crashed-tick recovery)."""
    db = _fresh_db()
    # Plant a lock that is 2 hours old (well past the 1800s stale threshold).
    db.execute("INSERT INTO tick_lock (id, locked_at, locked_by) "
               "VALUES ('global', datetime('now','-2 hours'), 'ghost')")
    db.commit()
    assert hdb.acquire_tick_lock(db, "fresh") is True, "stale lock (>1800s) must be stolen"
    # A fresh lock (just planted) must NOT be stolen.
    db2 = _fresh_db()
    db2.execute("INSERT INTO tick_lock (id, locked_at, locked_by) "
                "VALUES ('global', datetime('now'), 'live')")
    db2.commit()
    assert hdb.acquire_tick_lock(db2, "fresh") is False, "a fresh lock must not be stolen"
    print("PASS test_tick_lock_stale_is_stolen")


def test_register_entity_idempotent():
    db = _fresh_db()
    a = hdb.register_entity(db, "beads", "bd-1", "ticket", "beads:bd-1")
    b = hdb.register_entity(db, "beads", "bd-1", "ticket", "beads:bd-1")
    assert a == b, "re-registering same (source, external_id) must return the same id"
    c = hdb.register_entity(db, "beads", "bd-2", "ticket", "beads:bd-2")
    assert c != a, "a different external_id must get a different entity id"
    n = db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    assert n == 2, f"expected 2 entities, got {n}"
    print("PASS test_register_entity_idempotent")


def test_link_and_get_linked_entities():
    db = _fresh_db()
    bead = hdb.register_entity(db, "beads", "bd-9", "ticket", "")
    slack = hdb.register_entity(db, "slack", "C1/123.45", "thread", "")
    hdb.link_entities(db, bead, slack, "origin", session_id="t")
    linked = hdb.get_linked_entities(db, bead)
    assert len(linked) == 1, f"expected 1 linked entity, got {len(linked)}"
    assert linked[0]["id"] == slack and linked[0]["source"] == "slack", linked[0]
    # symmetric: querying from the slack side resolves back to the bead
    back = hdb.get_linked_entities(db, slack)
    assert back and back[0]["id"] == bead, "link must resolve in both directions"
    # never returns the entity itself
    assert all(e["id"] != bead for e in linked)
    print("PASS test_link_and_get_linked_entities")


def test_sync_state_roundtrip():
    db = _fresh_db()
    assert hdb.get_last_sync_at(db) == "1970-01-01T00:00:00Z", "default must be epoch"
    hdb.set_last_sync_at(db, "2026-01-02T03:04:05Z")
    assert hdb.get_last_sync_at(db) == "2026-01-02T03:04:05Z"
    print("PASS test_sync_state_roundtrip")


def test_slack_queue_dequeue_priority_then_fifo():
    """dequeue_pending_slack returns priority DESC, then enqueued-order (FIFO) within a tier —
    this is what lets a Shoaib-on-blocked-thread reply (priority>0) jump the queue."""
    db = _fresh_db()
    # Insert directly (avoid enqueue_slack_mention's bd side effect path); newer enqueued_at
    # on the high-priority row to prove priority wins over FIFO.
    db.execute("INSERT INTO slack_queue (id, source, channel, thread_ts, text, priority, "
               "enqueued_at) VALUES ('low-1','rt','C','1','a',0,'2026-01-01T00:00:00')")
    db.execute("INSERT INTO slack_queue (id, source, channel, thread_ts, text, priority, "
               "enqueued_at) VALUES ('low-2','rt','C','2','b',0,'2026-01-01T00:00:01')")
    db.execute("INSERT INTO slack_queue (id, source, channel, thread_ts, text, priority, "
               "enqueued_at) VALUES ('hi-1','rt','C','3','c',5,'2026-01-01T00:00:02')")
    db.commit()
    order = [r[0] for r in hdb.dequeue_pending_slack(db, limit=10)]
    assert order == ["hi-1", "low-1", "low-2"], f"priority DESC then FIFO expected, got {order}"
    print("PASS test_slack_queue_dequeue_priority_then_fifo")


def test_slack_retry_then_exhaust():
    """retry increments retry_count and re-queues as 'pending'; once retry_count >= max it
    flips to 'failed' (so a perpetually-failing job can't loop forever)."""
    db = _fresh_db()
    db.execute("INSERT INTO slack_queue (id, source, channel, thread_ts, text) "
               "VALUES ('j','rt','C','1','x')")
    db.commit()
    hdb.mark_slack_retry(db, "j", max_retries=2, failure_context="boom")
    row = db.execute("SELECT status, retry_count FROM slack_queue WHERE id='j'").fetchone()
    assert row == ("pending", 1), f"first failure → pending, retry_count=1; got {row}"
    hdb.mark_slack_retry(db, "j", max_retries=2, failure_context="boom2")
    row = db.execute("SELECT status, retry_count FROM slack_queue WHERE id='j'").fetchone()
    assert row == ("pending", 2), f"second failure → pending, retry_count=2; got {row}"
    # retry_count (2) >= max_retries (2) → exhausted → failed
    hdb.mark_slack_retry(db, "j", max_retries=2, failure_context="boom3")
    row = db.execute("SELECT status, failure_context FROM slack_queue WHERE id='j'").fetchone()
    assert row[0] == "failed", f"third failure (>=max) → failed; got {row[0]}"
    assert row[1] == "boom3", "last failure_context must be stored"
    print("PASS test_slack_retry_then_exhaust")


if __name__ == "__main__":
    test_tick_lock_reentrancy_and_release()
    test_tick_lock_stale_is_stolen()
    test_register_entity_idempotent()
    test_link_and_get_linked_entities()
    test_sync_state_roundtrip()
    test_slack_queue_dequeue_priority_then_fifo()
    test_slack_retry_then_exhaust()
    print("\nALL VARYS_HARNESS_DB TESTS PASSED")
