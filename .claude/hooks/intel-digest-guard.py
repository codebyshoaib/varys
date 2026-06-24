#!/usr/bin/env python3
"""
intel-digest-guard.py — Ensure the PM intel digest actually runs each evening.

Plain cron has no catch-up: if the laptop is asleep / off / offline at the
scheduled minute, the run is simply lost. This guard fixes that. It runs hourly
across the evening (cron: 0 18-23 * * *) and:

  1. Idempotent per evening — checks slack-intel-digest's durable last_run_ts. If
     the digest already delivered since today's 18:00 boundary, it does nothing.
     So at most ONE digest goes out per evening no matter how many ticks fire.
  2. Catch-up — if the 18:00 tick was missed (laptop asleep), whichever later
     hourly tick first finds the machine awake runs it.
  3. In-run retry with backoff — for a transient blip (network down, LLM rate
     limit) it retries a few times within the same tick before giving up to the
     next hourly tick.

Success is read from last_run_ts advancing past the 18:00 boundary — which, after
the digest's "advance window only on delivered DM" fix, is a true delivery signal.
A failed DM no longer advances the window, so the guard correctly retries.

cron: 0 18-23 * * * cd ~/varys && .claude/hooks/cron-wrap.sh intel-digest-guard python3 .claude/hooks/intel-digest-guard.py >> /tmp/varys-intel-digest.log 2>&1
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HOOKS_DIR  = Path(__file__).parent
VARYS_DIR  = HOOKS_DIR.parent.parent
STATE_FILE = Path.home() / ".varys-harness" / "intel-digest-state.json"
DIGEST     = HOOKS_DIR / "slack-intel-digest.py"

CYCLE_HOUR   = 18              # PM cycle boundary (local time)
MAX_ATTEMPTS = 3
BACKOFF_SECS = [60, 300]       # waits between attempts: 1min, then 5min


def _cycle_boundary_epoch() -> float:
    """Epoch of the most recent 18:00 boundary. If it's somehow before 18:00
    (guard shouldn't run then, but be safe), use yesterday's 18:00."""
    now = datetime.now()
    boundary = now.replace(hour=CYCLE_HOUR, minute=0, second=0, microsecond=0)
    if now < boundary:
        boundary -= timedelta(days=1)
    return boundary.timestamp()


def _already_delivered_this_cycle() -> bool:
    if not STATE_FILE.exists():
        return False
    try:
        ts = float(json.loads(STATE_FILE.read_text()).get("last_run_ts", 0))
    except Exception:
        return False
    return ts >= _cycle_boundary_epoch()


def main() -> int:
    if _already_delivered_this_cycle():
        print(f"[guard] PM digest already delivered this cycle "
              f"(since {datetime.fromtimestamp(_cycle_boundary_epoch()):%a %d %b %H:%M}) — nothing to do.")
        return 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"[guard] running intel digest (attempt {attempt}/{MAX_ATTEMPTS}) at {datetime.now():%H:%M:%S}")
        try:
            subprocess.run([sys.executable, str(DIGEST)], cwd=str(VARYS_DIR), timeout=600)
        except subprocess.TimeoutExpired:
            print("[guard] digest timed out (600s).")
        # Success = the window advanced past the 18:00 boundary (true delivery).
        if _already_delivered_this_cycle():
            print("[guard] digest delivered.")
            return 0
        if attempt < MAX_ATTEMPTS:
            wait = BACKOFF_SECS[attempt - 1]
            print(f"[guard] not delivered — backing off {wait}s before retry.")
            time.sleep(wait)

    print("[guard] digest not delivered after retries — next hourly tick will catch up.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
