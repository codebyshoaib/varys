#!/usr/bin/env python3
"""
varys-tick.py — ONE orchestrator tick, agent-free.

Replaces the `/loop 270s` agent-driven heartbeat. An LLM is NO LONGER in the
loop: the three pollers are pure Python and orchestrator-dispatch.py is pure
Python — `claude` is spawned ONLY downstream by the dispatcher (via
varys-manager.py) when events are actually pending. Idle ticks now cost a few
SQLite reads + HTTP polls instead of a full agent turn.

Tick semantics match orchestrator.md exactly:
  - acquire tick lock; if held, another tick is running -> exit (rule: tick atomicity)
  - run all pollers; if ANY fails -> release lock, DON'T advance last_sync_at,
    exit. Everything retries next tick (safe: deterministic event IDs) (rule 6)
  - all pollers ok -> orchestrator-dispatch.py -> advance last_sync_at
"""
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
REPO = HOOKS.parent.parent
sys.path.insert(0, str(HOOKS))
from varys_harness_db import (  # noqa: E402
    get_db,
    acquire_tick_lock,
    release_tick_lock,
    set_last_sync_at,
)

POLLERS = ["poll-harness-notion.py", "poll-eng-slack.py", "poll-taleemabad-github.py"]

# Poller exit-code contract:
#   0       → ran OK
#   2       → not configured (e.g. missing creds) → SKIP this source, tick continues
#   other   → real/transient failure → ABORT tick (rule 6), retry next tick
SKIP_RC = 2


def poller_outcome(rc: int) -> str:
    """Classify a poller exit code into ok | skip | abort."""
    if rc == 0:
        return "ok"
    if rc == SKIP_RC:
        return "skip"
    return "abort"


def main() -> int:
    db = get_db()
    if not acquire_tick_lock(db, "varys-tick"):
        print("[tick] lock held — another tick running; skip")
        db.close()
        return 0
    try:
        for p in POLLERS:
            r = subprocess.run(
                ["python3", str(HOOKS / p)],
                cwd=str(REPO), capture_output=True, text=True, timeout=120,
            )
            outcome = poller_outcome(r.returncode)
            if outcome == "skip":
                print(f"[tick] poller {p} skipped (not configured); continuing\n"
                      f"{r.stderr[-300:]}", file=sys.stderr)
                continue
            if outcome == "abort":
                # rule 6: a real/transient poller failure -> abort, do NOT advance last_sync_at
                print(f"[tick] poller {p} failed (rc={r.returncode}); aborting tick\n"
                      f"{r.stderr[-500:]}", file=sys.stderr)
                return 0  # `finally` still releases the lock
        # all pollers ok -> dispatch (spawns `claude` only if events pending).
        # stdio inherited so dispatch output flows to the daemon log.
        subprocess.run(
            ["python3", str(HOOKS / "orchestrator-dispatch.py")],
            cwd=str(REPO), timeout=900,
        )
        set_last_sync_at(db, datetime.now(timezone.utc).isoformat())
        return 0
    finally:
        release_tick_lock(db)
        db.close()


if __name__ == "__main__":
    sys.exit(main())
