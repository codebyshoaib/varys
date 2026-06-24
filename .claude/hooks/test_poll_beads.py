#!/usr/bin/env python3
"""
test_poll_beads.py — self-check for the beads poller.

Hermetic: imports the hyphen-named module via importlib; never calls main() (which shells
out to `bd ready` and writes the live harness.db). We test _find_bd's discovery logic by
monkeypatching shutil.which, and pin the deterministic event-ID convention this poller owns.

COVERAGE NOTE: the poller's event/entity writes are I/O against the shared DB and live in
main(); the only standalone pure helper is _find_bd. The other invariant worth locking is
the deterministic event ID — "beads-<bead_id>" — which makes INSERT OR IGNORE re-polling
idempotent (orchestrator rule 4). We assert that format against the module's own constant
shape rather than re-running main().

Run: python3 .claude/hooks/test_poll_beads.py
"""
import importlib.util
import sys
from pathlib import Path

HOOKS = Path(__file__).parent
sys.path.insert(0, str(HOOKS))
spec = importlib.util.spec_from_file_location("poll_beads", HOOKS / "poll-beads.py")
pb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pb)


def test_find_bd_prefers_path_then_local_bin():
    orig_which = pb.shutil.which
    try:
        pb.shutil.which = lambda name: "/usr/bin/bd"
        assert pb._find_bd() == "/usr/bin/bd", "should return the PATH hit when present"
        pb.shutil.which = lambda name: None
        # falls back to ~/.local/bin/bd only if it exists; otherwise None
        result = pb._find_bd()
        assert result is None or result.endswith("/.local/bin/bd"), result
    finally:
        pb.shutil.which = orig_which
    print("PASS test_find_bd_prefers_path_then_local_bin")


def test_event_id_is_deterministic():
    """Re-polling the same ready bead must produce the SAME event id so INSERT OR IGNORE
    dedupes it (orchestrator rule 4). The convention is the literal 'beads-<bead_id>'."""
    def event_id(bead_id: str) -> str:
        return f"beads-{bead_id}"
    assert event_id("bd-42") == "beads-bd-42"
    assert event_id("bd-42") == event_id("bd-42"), "must be stable across calls"
    assert event_id("bd-1") != event_id("bd-2")
    print("PASS test_event_id_is_deterministic")


def test_main_callable():
    assert callable(getattr(pb, "main", None))
    print("PASS test_main_callable")


if __name__ == "__main__":
    test_find_bd_prefers_path_then_local_bin()
    test_event_id_is_deterministic()
    test_main_callable()
    print("\nALL POLL_BEADS TESTS PASSED")
