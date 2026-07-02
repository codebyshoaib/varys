#!/usr/bin/env python3
"""Tests for varys-session-review.py — the live memory path (debounce, transcript
digest, engram dual-write trailer parsing). This is the one hook whose silent failure
would rot the learning loop, and its __main__ self-check is NOT run by the gate — the
gate only runs test_*.py. Covers the pure, branchy pieces without any model/subprocess.

Traceable to wisdom: "Self-healing loops need idempotency and current-state verification
above all" — the debounce IS the idempotency guard; a regression there re-reflects every
turn. The engram trailer parse was changed in varys-c85.1 and had no gate-run test."""
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HOOKS = Path(__file__).parent
spec = importlib.util.spec_from_file_location("varys_session_review", HOOKS / "varys-session-review.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


# ── Debounce (idempotency guard — fires once per session, honours cooldown) ──
def _base_state():
    base = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    return {"sessions": {"s": 100}, "last_ts": base.isoformat()}, base


def test_should_review_skips_when_too_little_new_transcript():
    st, base = _base_state()
    assert not review.should_review(st, "s", 100 + review.MIN_NEW_LINES - 1, base)


def test_should_review_skips_inside_cooldown_even_with_enough_lines():
    st, base = _base_state()
    assert not review.should_review(st, "s", 100 + review.MIN_NEW_LINES, base)


def test_should_review_fires_when_growth_and_cooldown_both_met():
    st, base = _base_state()
    later = base.replace(hour=13)  # +60min > COOLDOWN_MIN
    assert review.should_review(st, "s", 100 + review.MIN_NEW_LINES, later)


def test_should_review_fires_for_brand_new_session():
    st, base = _base_state()
    later = base.replace(hour=13)
    assert review.should_review(st, "new", review.MIN_NEW_LINES, later)


def test_should_review_tolerates_corrupt_last_ts():
    # bad timestamp must not crash the guard; growth check still governs
    st = {"sessions": {"s": 100}, "last_ts": "garbage"}
    now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    assert review.should_review(st, "s", 100 + review.MIN_NEW_LINES, now)


# ── Engram dual-write trailer (varys-c85.1) — only real JSON after prefix parses ──
def test_parse_summary_extracts_trailer():
    out = 'work happened\nSUMMARY_JSON: {"title":"t","summary":"s"}'
    assert review._parse_summary(out) == {"title": "t", "summary": "s"}


def test_parse_summary_ignores_non_trailer_output():
    assert review._parse_summary("no lesson this session") is None


def test_parse_summary_returns_none_on_malformed_json():
    assert review._parse_summary("SUMMARY_JSON: not json") is None


def test_parse_summary_takes_last_trailer_when_multiple():
    out = 'SUMMARY_JSON: {"title":"old"}\nmore\nSUMMARY_JSON: {"title":"new"}'
    assert review._parse_summary(out) == {"title": "new"}


# ── Transcript digest — keeps prose, drops tool noise, caps length ──
def test_build_digest_keeps_prose_drops_tool_noise():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.jsonl"
        rows = [
            {"type": "user", "message": {"role": "user", "content": "fix the bug"}},
            {"type": "assistant", "message": {"role": "assistant",
                "content": [{"type": "text", "text": "on it"},
                             {"type": "tool_use", "name": "Bash", "input": {}}]}},
            {"type": "tool_result", "message": {"content": "exit 0"}},  # dropped: wrong type
            {"type": "assistant", "message": {"role": "assistant", "content": "done"}},
        ]
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        digest, n_turns = review.build_digest(p)
        assert n_turns == 3, n_turns  # two assistant + one user; tool_result excluded
        assert "fix the bug" in digest and "on it" in digest and "done" in digest
        assert "exit 0" not in digest and "tool_use" not in digest


def test_build_digest_tolerates_malformed_lines():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.jsonl"
        p.write_text("not json\n\n" +
                     json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}) + "\n")
        digest, n_turns = review.build_digest(p)
        assert n_turns == 1 and "hi" in digest


def test_build_digest_caps_long_transcript():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.jsonl"
        big = "x" * (review.MAX_DIGEST_CH * 2)
        p.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": big}}) + "\n")
        digest, _ = review.build_digest(p)
        assert len(digest) <= review.MAX_DIGEST_CH + 64  # cap + elision marker
        assert digest.startswith("…(earlier turns elided)…")


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
    print("\nALL SESSION-REVIEW TESTS PASSED")
    sys.exit(0)
