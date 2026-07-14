#!/usr/bin/env python3
"""Tests for varys-synthesize-learnings.py — the daily (cron 0 12) synthesis that rolls
memory/*.jsonl archives into active_learnings.md / active_slack_learnings.md, which
session-start.py injects into every session. A silent break here corrupts the context
Varys enters every conversation with — including the trajectory this very evolver reads —
with no alarm. Its __main__ is NOT run by the gate; the gate only runs test_*.py.

Covers the pure, branchy pieces with NO model call, NO git, NO real-memory mutation:
  - _count_lines (missing file, blank-line skipping)
  - _synthesize's empty-archive placeholder branch (returns True WITHOUT invoking claude -p)
  - _backup/_restore/_cleanup_backup — the corruption-safety guard that reverts a bad run

Traceable to wisdom "Enforcement Without Sensors Is Theater" and the deliberate push to give
every memory-mutating cron a gate-run test (mirrors test_varys_reflect.py,
test_varys_session_review.py). varys-synthesize-learnings was the one crontab-wired
memory-mutating cron still missing it."""
import importlib.util
import sys
import tempfile
from pathlib import Path

HOOKS = Path(__file__).parent
spec = importlib.util.spec_from_file_location(
    "varys_synthesize_learnings", HOOKS / "varys-synthesize-learnings.py")
synth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(synth)


# ── _count_lines: missing file → 0, blank lines skipped ──
def test_count_lines_missing_file_returns_zero():
    assert synth._count_lines(Path("/nonexistent/learnings.jsonl")) == 0


def test_count_lines_skips_blank_lines():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "learnings.jsonl"
        f.write_text('{"a":1}\n\n   \n{"b":2}\n')
        assert synth._count_lines(f) == 2


# ── _synthesize empty-archive branch: writes placeholder, returns True, NO model call ──
def test_synthesize_empty_learnings_writes_placeholder():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "active_learnings.md"
        # archive path does not exist → empty → placeholder branch, no subprocess
        ok = synth._synthesize(Path(td) / "missing.jsonl", out, "learnings")
        assert ok is True
        text = out.read_text()
        assert text.startswith("# Active Learnings")
        assert "(No entries yet)" in text


def test_synthesize_empty_slack_writes_placeholder():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "active_slack_learnings.md"
        ok = synth._synthesize(Path(td) / "missing.jsonl", out, "slack")
        assert ok is True
        text = out.read_text()
        assert text.startswith("# Active Slack Learnings")
        assert "(No entries yet)" in text


# ── backup/restore: the corruption-safety guard. A bad synthesis MUST leave the old file. ──
def test_backup_then_restore_recovers_original():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "active_learnings.md"
        out.write_text("ORIGINAL GOOD CONTENT\n")
        bak = synth._backup(out)
        assert bak is not None and bak.exists()
        out.write_text("corrupted half-written garbage")  # simulate a failed run
        synth._restore(out, bak)
        assert out.read_text() == "ORIGINAL GOOD CONTENT\n"


def test_backup_of_missing_file_is_none():
    with tempfile.TemporaryDirectory() as td:
        assert synth._backup(Path(td) / "nope.md") is None


def test_restore_with_no_backup_removes_corrupt_file():
    # First-ever run has no prior file → no backup → a malformed output must be removed,
    # not left in place as corrupt active memory.
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "active_learnings.md"
        out.write_text("garbage from a failed first run")
        synth._restore(out, None)
        assert not out.exists()


def test_cleanup_backup_removes_bak():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "active_learnings.md"
        out.write_text("good\n")
        bak = synth._backup(out)
        synth._cleanup_backup(bak)
        assert not bak.exists()


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                print(f"FAIL {name}: {e}")
                failures += 1
    if failures:
        print(f"\n{failures} FAILURE(S)")
        sys.exit(1)
    print("\nALL SYNTHESIZE TESTS PASSED")
    sys.exit(0)
