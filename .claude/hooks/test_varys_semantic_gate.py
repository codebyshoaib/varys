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


# ── CORE-strict prompt + double-judge ──────────────────────────────────────

def test_core_prompt_names_invariants():
    """The core-strict prompt must quote the documented orchestrator invariants so the
    judge actually checks them (this is the whole point of the stricter tier)."""
    p = sg._build_core_semantic_judge_prompt("diff --git a/x b/x\n+x\n").lower()
    for needle in ("tick atomicity", "status=done is written last", "350ms",
                   "deterministic event id", "two-query", "270s",
                   "one session per context_key", "plan-first", "context_key is always"):
        assert needle in p, f"core prompt missing invariant language: {needle!r}"
    # and it must still carry the base safety + fail-safe language
    assert "weakens a safety" in p and "revert" in p
    print("PASS test_core_prompt_names_invariants")


def test_core_gate_uses_strict_prompt():
    """semantic_gate(diff, core=True) must build the CORE prompt and tag gate semantic-core."""
    diff = "diff --git a/.claude/hooks/varys-tick.py b/.claude/hooks/varys-tick.py\n+x\n"
    seen = {}
    orig = sg._run_semantic_judge
    try:
        def _spy(prompt, *a, **kw):
            seen["prompt"] = prompt
            return '{"verdict":"keep","reason":"ok","risk":"none"}'
        sg._run_semantic_judge = _spy
        res = sg.semantic_gate(diff, core=True)
        assert res["gate"] == "semantic-core", res
        assert "CORE ORCHESTRATION" in seen["prompt"], "core gate did not use the strict prompt"
        assert "270s" in seen["prompt"], "core prompt missing invariant"
    finally:
        sg._run_semantic_judge = orig
    print("PASS test_core_gate_uses_strict_prompt")


def test_double_judge_keeps_only_on_2of2():
    """core_semantic_gate keeps only when BOTH independent passes say keep; reverts when
    either dissents — even if the FIRST said keep (adversarial double-verify)."""
    diff = "diff --git a/.claude/hooks/varys_notion.py b/.claude/hooks/varys_notion.py\n+x\n"
    calls = {"n": 0}
    orig = sg._run_semantic_judge
    try:
        # both keep → keep, gate semantic-core-2of2
        sg._run_semantic_judge = lambda *a, **kw: '{"verdict":"keep","reason":"ok","risk":"low"}'
        res = sg.core_semantic_gate(diff)
        assert res["verdict"] == "keep" and res["gate"] == "semantic-core-2of2", res

        # first keep, second revert → REVERT (the dissent wins)
        def _flip(*a, **kw):
            calls["n"] += 1
            return ('{"verdict":"keep","reason":"first ok","risk":"none"}' if calls["n"] == 1
                    else '{"verdict":"revert","reason":"breaks tick atomicity","risk":"high"}')
        calls["n"] = 0
        sg._run_semantic_judge = _flip
        res2 = sg.core_semantic_gate(diff)
        assert res2["verdict"] == "revert", res2
        assert calls["n"] == 2, f"both judges should have run independently, got {calls['n']}"

        # first revert → short-circuit, do NOT run the second
        calls["n"] = 0
        def _first_revert(*a, **kw):
            calls["n"] += 1
            return '{"verdict":"revert","reason":"unsafe","risk":"high"}'
        sg._run_semantic_judge = _first_revert
        res3 = sg.core_semantic_gate(diff)
        assert res3["verdict"] == "revert", res3
        assert calls["n"] == 1, f"first-revert must short-circuit, ran {calls['n']} judges"
    finally:
        sg._run_semantic_judge = orig
    print("PASS test_double_judge_keeps_only_on_2of2")


def test_double_judge_fails_safe_on_error():
    """If a judge pass errors / yields no output, core_semantic_gate reverts (never raises)."""
    diff = "diff --git a/.claude/hooks/stop.py b/.claude/hooks/stop.py\n+x\n"
    orig = sg._run_semantic_judge
    try:
        sg._run_semantic_judge = lambda *a, **kw: ""   # empty → semantic-error → revert
        res = sg.core_semantic_gate(diff)
        assert res["verdict"] == "revert", res

        def _raise(*a, **kw):
            raise RuntimeError("boom")
        sg._run_semantic_judge = _raise
        res2 = sg.core_semantic_gate(diff)
        assert res2["verdict"] == "revert", res2
    finally:
        sg._run_semantic_judge = orig
    # None and empty-diff degenerate cases route through semantic_gate too
    assert sg.core_semantic_gate(None)["verdict"] == "revert"
    assert sg.core_semantic_gate("")["verdict"] == "keep"   # confirmed no-op
    print("PASS test_double_judge_fails_safe_on_error")


if __name__ == "__main__":
    test_parse_keep_verdict()
    test_parse_revert_verdict()
    test_parse_embedded_in_prose()
    test_parse_malformed_fails_safe_to_revert()
    test_gate_empty_diff_is_noop()
    test_gate_none_diff_fails_safe()
    test_gate_judge_error_fails_safe()
    test_gate_parses_real_verdict()
    test_core_prompt_names_invariants()
    test_core_gate_uses_strict_prompt()
    test_double_judge_keeps_only_on_2of2()
    test_double_judge_fails_safe_on_error()
    print("\nALL SEMANTIC-GATE TESTS PASSED")
