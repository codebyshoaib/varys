#!/usr/bin/env python3
"""Tests for varys-dream.py — scope guard is the safety-critical piece."""
import importlib.util
import sys
from pathlib import Path

HOOKS = Path(__file__).parent
spec = importlib.util.spec_from_file_location("varys_dream", HOOKS / "varys-dream.py")
dream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dream)


def test_in_scope_allows_only_dream_and_log():
    assert dream._in_scope("DREAM.md")
    assert dream._in_scope(".beads/dream_log.jsonl")


def test_in_scope_denies_everything_else():
    # The whole point: a dream cycle can change its dream and NOTHING else.
    for p in (
        ".claude/hooks/varys-tick.py",
        ".claude/skills/varys/routing.md",
        ".claude/rules/orchestrator.md",
        "memory/learnings.jsonl",
        "CLAUDE.md",
        "settings.json",
        "DREAM.md.bak",          # near-miss must not pass
        "dream_log.jsonl",        # wrong path (not under .beads/) must not pass
    ):
        assert not dream._in_scope(p), f"{p} should be out of scope"


def test_parse_json_extracts_last_object():
    out = "blah blah\nsome reasoning\n{\"action\": \"advance\", \"aspiration\": \"x\"}"
    assert dream._parse_json(out)["action"] == "advance"


def test_parse_json_empty_on_garbage():
    assert dream._parse_json("no json here at all") == {}


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
    print("\nALL DREAM TESTS PASSED")
    sys.exit(0)
