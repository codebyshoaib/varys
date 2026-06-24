#!/usr/bin/env python3
"""Self-check for the tick's poller exit-code contract + the 'Slack is not polled'
invariant. Run: python3 test_varys_tick.py"""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("varys_tick", Path(__file__).parent / "varys-tick.py")
vt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vt)

# Poller exit-code classification (orchestrator rule 6: a real failure aborts the tick).
assert vt.poller_outcome(0) == "ok"
assert vt.poller_outcome(2) == "skip"      # not configured -> don't abort the tick
assert vt.poller_outcome(1) == "abort"     # real failure -> rule 6 abort
assert vt.poller_outcome(137) == "abort"   # killed/timeout -> abort
assert vt.SKIP_RC == 2                      # the "not configured" sentinel

# Invariant: the tick polls ONLY sources that can't push to this box (beads, GitHub).
# Slack intake belongs to the real-time listener, never the tick — guard against a
# poll-*slack* poller sneaking back into the loop.
assert vt.POLLERS == ["poll-beads.py", "poll-taleemabad-github.py"], vt.POLLERS
assert not any("slack" in p.lower() for p in vt.POLLERS), \
    "Slack must NOT be polled by the tick (listener owns Slack intake)"

print("ok")
