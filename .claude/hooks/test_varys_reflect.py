#!/usr/bin/env python3
"""Tests for varys-reflect.py — the reflection cron that appends lessons to
memory/learnings.jsonl (which synthesize-learnings.py rolls into active_learnings.md,
injected into every session by session-start.py). A silent break here rots the
compounding self-knowledge loop with no alarm, and its __main__ is NOT run by the gate —
the gate only runs test_*.py. Covers the branchy pure pieces with NO model/subprocess and
NO memory mutation (main() is never called; only pure helpers + a monkeypatched temp path).

Traceable to wisdom: "Enforcement Without Sensors Is Theater" — a memory-mutating cron with
no gate-run test is a guard nobody enforces. Mirrors the merged test_varys_session_review.py."""
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

HOOKS = Path(__file__).parent
spec = importlib.util.spec_from_file_location("varys_reflect", HOOKS / "varys-reflect.py")
reflect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reflect)


# ── build_prompt: conditional blocks + the append instruction must survive edits ──
def test_build_prompt_includes_commits():
    p = reflect.build_prompt("fix X, ship Y", "", "", "")
    assert "fix X, ship Y" in p


def test_build_prompt_shows_placeholder_when_no_commits():
    p = reflect.build_prompt("", "", "", "")
    assert "(no notable commits)" in p


def test_build_prompt_omits_optional_blocks_when_empty():
    p = reflect.build_prompt("c", "", "", "")
    assert "## Failure patterns you've been hitting" not in p
    assert "## What you did (session log)" not in p
    assert "## SELF-WISDOM" not in p


def test_build_prompt_includes_optional_blocks_when_present():
    p = reflect.build_prompt("c", "did a thing", "boom ×3", "old lesson")
    assert "## Failure patterns you've been hitting" in p and "boom ×3" in p
    assert "## What you did (session log)" in p and "did a thing" in p
    assert "## SELF-WISDOM" in p and "old lesson" in p


def test_build_prompt_keeps_append_instruction_and_abstain_path():
    # The heredoc append target and the "write nothing" branch are the whole contract:
    # lose either and reflection silently stops writing (or writes to the wrong file).
    p = reflect.build_prompt("c", "", "", "")
    assert "memory/learnings.jsonl" in p
    assert "PYEOF" in p
    assert "no lesson this period" in p


# ── gather_failure_patterns: JSONL parse, 14-day cutoff, type exclusion, incident tail ──
def _write_failures(tmp: Path, lines):
    tmp.write_text("\n".join(lines) + "\n")


def test_gather_failure_patterns_missing_file_returns_empty():
    reflect.FAILURES_FILE = Path("/nonexistent/failures.jsonl")
    assert reflect.gather_failure_patterns() == ""


def test_gather_failure_patterns_counts_types_and_excludes_evolution_applied():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "failures.jsonl"
        _write_failures(f, [
            json.dumps({"failure_type": "gate-revert", "ts": ts}),
            json.dumps({"failure_type": "gate-revert", "ts": ts}),
            json.dumps({"failure_type": "evolution-applied", "ts": ts}),  # must be excluded
        ])
        reflect.FAILURES_FILE = f
        out = reflect.gather_failure_patterns()
        assert "gate-revert ×2" in out
        assert "evolution-applied" not in out


def test_gather_failure_patterns_respects_14_day_cutoff():
    now = datetime.now(timezone.utc)
    recent = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    old = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "failures.jsonl"
        _write_failures(f, [
            json.dumps({"failure_type": "fresh", "ts": recent}),
            json.dumps({"failure_type": "stale", "ts": old}),
        ])
        reflect.FAILURES_FILE = f
        out = reflect.gather_failure_patterns()
        assert "fresh" in out
        assert "stale" not in out  # older than 14d → dropped


def test_gather_failure_patterns_tolerates_malformed_lines():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "failures.jsonl"
        _write_failures(f, [
            "not json at all",
            "",
            json.dumps({"failure_type": "real", "ts": now}),
        ])
        reflect.FAILURES_FILE = f
        out = reflect.gather_failure_patterns()
        assert "real" in out  # malformed lines skipped, valid one still counted


def test_gather_failure_patterns_includes_incident_tail():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "failures.jsonl"
        _write_failures(f, [
            json.dumps({"incident": "listener flapped", "ts": now}),
        ])
        reflect.FAILURES_FILE = f
        out = reflect.gather_failure_patterns()
        assert "listener flapped" in out


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
    print("\nALL REFLECT TESTS PASSED")
    sys.exit(0)
