#!/usr/bin/env python3
"""Tests for varys-synthesize-learnings.py — the daily cron that compresses
memory/*.jsonl archives into memory/active_learnings.md + active_slack_learnings.md,
which session-start.py injects into every session. A silent break here corrupts the
compounding self-knowledge loop with no alarm, and its __main__ is NOT run by the gate —
the gate only runs test_*.py.

Covers the branchy, memory-SAFETY-critical pure pieces with NO model/subprocess/git and
NO real memory mutation (main()/_synthesize's LLM path are never called; only pure helpers
+ temp files). The backup/restore round-trip is the whole point: if synthesis fails, the
old active file must be recovered, never left half-written.

Traceable to wisdom: "Self-healing/feedback systems need idempotency and verification MORE
than features do" — a memory-mutating cron with no gate-run test is a guard nobody enforces.
Mirrors test_varys_reflect.py / test_varys_session_review.py."""
import importlib.util
import sys
import tempfile
from pathlib import Path

HOOKS = Path(__file__).parent
spec = importlib.util.spec_from_file_location(
    "varys_synthesize_learnings", HOOKS / "varys-synthesize-learnings.py"
)
synth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(synth)


# ── _count_lines: missing → 0, non-blank counted, blanks ignored ──
def test_count_lines_missing_file_returns_zero():
    assert synth._count_lines(Path("/nonexistent/learnings.jsonl")) == 0


def test_count_lines_counts_non_blank_only():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "a.jsonl"
        f.write_text('{"x":1}\n\n   \n{"y":2}\n')
        assert synth._count_lines(f) == 2


# ── backup/restore round-trip: the corruption-safety contract ──
def test_backup_then_restore_recovers_original_content():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "active_learnings.md"
        out.write_text("ORIGINAL good context\n")
        bak = synth._backup(out)
        assert bak is not None and bak.exists()
        # simulate a corrupt half-write, then a failed-synthesis restore
        out.write_text("GARBAGE partial output")
        synth._restore(out, bak)
        assert out.read_text() == "ORIGINAL good context\n"


def test_backup_of_missing_file_returns_none():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "active_learnings.md"  # does not exist
        assert synth._backup(out) is None


def test_restore_with_no_backup_removes_corrupt_file():
    # No prior file existed → no backup → a failed synthesis must delete the
    # potentially-corrupt output rather than leave garbage in place.
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "active_learnings.md"
        out.write_text("GARBAGE partial output")
        synth._restore(out, None)
        assert not out.exists()


def test_cleanup_backup_removes_bak_and_tolerates_none():
    with tempfile.TemporaryDirectory() as td:
        bak = Path(td) / "active_learnings.md.bak"
        bak.write_text("x")
        synth._cleanup_backup(bak)
        assert not bak.exists()
        synth._cleanup_backup(None)  # must not raise


# ── _synthesize empty-archive branch: writes placeholder, NEVER calls the LLM ──
def test_synthesize_empty_archive_writes_learnings_placeholder():
    with tempfile.TemporaryDirectory() as td:
        archive = Path(td) / "learnings.jsonl"  # missing → treated as empty
        out = Path(td) / "active_learnings.md"
        assert synth._synthesize(archive, out, "learnings") is True
        text = out.read_text()
        assert text.startswith("# Active Learnings")
        assert "No entries yet" in text


def test_synthesize_empty_archive_writes_slack_placeholder():
    with tempfile.TemporaryDirectory() as td:
        archive = Path(td) / "slack_learnings.jsonl"
        archive.write_text("   \n\n")  # exists but blank → empty branch
        out = Path(td) / "active_slack_learnings.md"
        assert synth._synthesize(archive, out, "slack") is True
        text = out.read_text()
        assert text.startswith("# Active Slack Learnings")
        assert "No entries yet" in text


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
