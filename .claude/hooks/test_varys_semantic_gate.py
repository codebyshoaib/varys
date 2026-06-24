#!/usr/bin/env python3
"""
test_varys_semantic_gate.py — self-check for the shared semantic safety veto.

Hermetic: the only impure function (_run_semantic_judge → claude -p) is
monkeypatched, so this never spawns a subprocess or hits the network. Run:
  python3 .claude/hooks/test_varys_semantic_gate.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import varys_semantic_gate as sg


def test_parse_keep_verdict():
    v, reason, risk = sg._parse_semantic_verdict('{"verdict":"keep","reason":"ok","risk":"none"}')
    assert v == "keep" and risk == "none", (v, risk)
    print("PASS test_parse_keep_verdict")


def test_parse_revert_verdict():
    v, _r, risk = sg._parse_semantic_verdict('{"verdict":"revert","reason":"weakens guard","risk":"high"}')
    assert v == "revert" and risk == "high"
    print("PASS test_parse_revert_verdict")


def test_parse_embedded_in_prose():
    raw = 'Here is my verdict:\n{"verdict":"keep","reason":"additive","risk":"low"}'
    v, _r, risk = sg._parse_semantic_verdict(raw)
    assert v == "keep" and risk == "low"
    print("PASS test_parse_embedded_in_prose")


def test_parse_malformed_fails_safe_to_revert():
    for raw in ["", "   ", "not json", '{"verdict":"maybe"}',
                '["verdict","keep"]', '{"verdict":"keep"']:
        v, _r, risk = sg._parse_semantic_verdict(raw)
        assert v == "revert", f"malformed {raw!r} must revert, got {v}"
        assert risk == "high", f"malformed {raw!r} must be high risk, got {risk}"
    print("PASS test_parse_malformed_fails_safe_to_revert")


def test_gate_empty_diff_is_noop():
    """Empty diff → keep + semantic-noop, judge NEVER spawned."""
    def _boom(*a, **kw):
        raise AssertionError("judge must NOT be spawned on an empty diff")
    orig = sg._run_semantic_judge
    sg._run_semantic_judge = _boom
    try:
        for empty in ["", "   ", "\n\n"]:
            res = sg.semantic_gate(empty)
            assert res["verdict"] == "keep" and res["gate"] == "semantic-noop", res
    finally:
        sg._run_semantic_judge = orig
    print("PASS test_gate_empty_diff_is_noop")


def test_gate_none_diff_fails_safe():
    """None (could-not-read) → revert tagged semantic-error."""
    res = sg.semantic_gate(None)
    assert res["verdict"] == "revert" and res["gate"] == "semantic-error", res
    print("PASS test_gate_none_diff_fails_safe")


def test_gate_judge_error_fails_safe():
    diff = "diff --git a/.claude/hooks/x.py b/.claude/hooks/x.py\n-    assert safe\n"
    orig = sg._run_semantic_judge
    try:
        sg._run_semantic_judge = lambda *a, **kw: ""          # empty output
        res = sg.semantic_gate(diff)
        assert res["verdict"] == "revert" and res["gate"] == "semantic-error", res

        def _raise(*a, **kw):
            raise RuntimeError("subprocess blew up")
        sg._run_semantic_judge = _raise
        res2 = sg.semantic_gate(diff)
        assert res2["verdict"] == "revert" and res2["gate"] == "semantic-error", res2
    finally:
        sg._run_semantic_judge = orig
    print("PASS test_gate_judge_error_fails_safe")


def test_gate_parses_real_verdict():
    diff = "diff --git a/.claude/rules/x.md b/.claude/rules/x.md\n+clarify wording\n"
    orig = sg._run_semantic_judge
    try:
        sg._run_semantic_judge = lambda *a, **kw: '{"verdict":"keep","reason":"additive","risk":"none"}'
        res = sg.semantic_gate(diff)
        assert res["verdict"] == "keep" and res["gate"] == "semantic", res
    finally:
        sg._run_semantic_judge = orig
    print("PASS test_gate_parses_real_verdict")


if __name__ == "__main__":
    test_parse_keep_verdict()
    test_parse_revert_verdict()
    test_parse_embedded_in_prose()
    test_parse_malformed_fails_safe_to_revert()
    test_gate_empty_diff_is_noop()
    test_gate_none_diff_fails_safe()
    test_gate_judge_error_fails_safe()
    test_gate_parses_real_verdict()
    print("\nALL SEMANTIC-GATE TESTS PASSED")
