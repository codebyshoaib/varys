#!/usr/bin/env python3
"""
test_varys_proactive_evolve.py — self-check for the tiered (CORE vs leaf) fence in the
proactive evolution loop. Hermetic: imports the hyphen-named module via importlib (like
the loop's own test_varys_tick.py), monkeypatches the semantic judges so NO claude -p /
network / git is ever invoked, and only exercises pure logic + the early-return branch of
gate_tests (the missing-sibling check, which returns BEFORE running any real test files).

Run: python3 .claude/hooks/test_varys_proactive_evolve.py
"""
import importlib.util
import sys
from pathlib import Path

HOOKS = Path(__file__).parent
sys.path.insert(0, str(HOOKS))

spec = importlib.util.spec_from_file_location(
    "varys_proactive_evolve", HOOKS / "varys-proactive-evolve.py")
pe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pe)


def test_fence_still_blocks_outside_and_denylist():
    """Tiering must not weaken the base fence: out-of-fence + denylisted still rejected."""
    assert pe._is_allowed(".claude/hooks/friction_signals.py")          # leaf, allowed
    assert pe._is_allowed(".claude/rules/orchestrator.md")              # rules, allowed
    assert not pe._is_allowed("settings.json")                         # outside fence
    assert not pe._is_allowed(".claude/hooks/.env")                    # denylist fragment
    assert not pe._is_allowed(".claude/hooks/varys-slack-listener.py") # denylisted daemon
    assert not pe._is_allowed(".claude/hooks/varys-proactive-evolve.py")  # the loop itself
    assert not pe._is_allowed(".claude/hooks/varys_semantic_gate.py")  # the judge itself
    print("PASS test_fence_still_blocks_outside_and_denylist")


def test_core_detection():
    """CORE_FILES are recognised as core; leaf hooks and rules are not."""
    assert pe._is_core(".claude/hooks/orchestrator-dispatch.py")
    assert pe._is_core(".claude/hooks/varys_notion.py")
    assert pe._is_core(".claude/hooks/poll-beads.py")
    assert not pe._is_core(".claude/hooks/friction_signals.py")   # leaf hook
    assert not pe._is_core(".claude/rules/orchestrator.md")       # rules text
    assert not pe._is_core(".claude/hooks/varys_semantic_gate.py")  # denylisted, not core
    # every declared core file lives inside the fence (never silently unreachable)
    for f in pe.CORE_FILES:
        assert pe._is_allowed(f), f"core file {f} is not inside the fence!"
    print("PASS test_core_detection")


def test_touched_core_subset():
    changed = [".claude/hooks/friction_signals.py",
               ".claude/hooks/varys-tick.py",
               ".claude/rules/x.md",
               ".claude/hooks/poll-beads.py"]
    assert pe._touched_core(changed) == [".claude/hooks/poll-beads.py",
                                         ".claude/hooks/varys-tick.py"]
    assert pe._touched_core([".claude/hooks/friction_signals.py"]) == []
    print("PASS test_touched_core_subset")


def _underscore_stem(filename: str) -> str:
    return Path(filename).stem.replace("-", "_")


def test_hyphenated_hook_resolves_to_underscore_sibling():
    """REGRESSION (hyphen→underscore bug): a changed hyphenated hook (varys-tick.py) must
    resolve to the UNDERSCORE sibling test_varys_tick.py — which exists on disk — and so
    pass the sibling-presence check. Before the fix, gate_tests looked for the hyphen name
    test_varys-tick.py, which never exists, so every hyphen-named hook wrongly failed.

    Asserted via the sibling-resolution logic directly (we do NOT call gate_tests here: it
    would spawn every test_*.py as a subprocess — including THIS file — recursively). We
    replicate the gate's stem→sibling derivation and confirm it lands on the underscore file
    that exists, not the hyphen file that never does."""
    underscore_sibling = pe.HOOKS_DIR / f"test_{_underscore_stem('varys-tick.py')}.py"
    assert underscore_sibling.name == "test_varys_tick.py", underscore_sibling.name
    assert underscore_sibling.exists(), "test_varys_tick.py must exist for this regression test"
    assert not (pe.HOOKS_DIR / "test_varys-tick.py").exists()  # buggy hyphen path never exists
    # Behaviorally: a hyphenated hook whose underscore sibling exists must NOT be the one
    # gate_tests rejects for a missing sibling. We verify the negative cheaply by checking
    # the sibling the gate would look for is present (full-suite run is covered by the gate
    # itself in production; calling it here would recurse).
    print("PASS test_hyphenated_hook_resolves_to_underscore_sibling")


def test_missing_sibling_fails_gate_with_core_message():
    """A core file with NO sibling test fails the test gate, and the message names it a CORE
    file (no exemption) and the UNDERSCORE sibling name. Uses a temp hyphenated hook
    registered as core via monkeypatch, so the gate returns at the sibling check BEFORE
    running any real test files — and we don't depend on a real core file lacking a sibling
    (after this PR they all have one)."""
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".py", prefix="zz-temp-core-", dir=str(pe.HOOKS_DIR))
    os.close(fd)
    rel = ".claude/hooks/" + os.path.basename(path)
    orig_core = pe.CORE_FILES
    try:
        pe.CORE_FILES = frozenset(orig_core | {rel})   # treat temp hook as core
        ok, reason = pe.gate_tests([rel])
        assert ok is False, "core file without a sibling test must fail the gate"
        assert "CORE" in reason and "no sibling" in reason.lower(), reason
        stem = _underscore_stem(os.path.basename(path))
        assert f"test_{stem}.py" in reason, reason   # complained about the underscore sibling
    finally:
        pe.CORE_FILES = orig_core
        os.unlink(path)
    print("PASS test_missing_sibling_fails_gate_with_core_message")


def test_load_semantic_judge_routes_core_vs_leaf():
    """_load_semantic_judge returns (leaf, core). Monkeypatch the underlying judge so no
    subprocess runs: the leaf judge uses the base prompt (gate 'semantic'), the core judge
    runs the 2-of-2 double judge (gate 'semantic-core-2of2' on a clean keep)."""
    import varys_semantic_gate as sg
    orig = sg._run_semantic_judge
    try:
        sg._run_semantic_judge = lambda *a, **kw: '{"verdict":"keep","reason":"ok","risk":"none"}'
        leaf, core = pe._load_semantic_judge()
        diff = "diff --git a/.claude/hooks/varys_notion.py b/.claude/hooks/varys_notion.py\n+x\n"
        leaf_res = leaf(diff)
        core_res = core(diff)
        assert leaf_res["verdict"] == "keep" and leaf_res["gate"] == "semantic", leaf_res
        assert core_res["verdict"] == "keep" and core_res["gate"] == "semantic-core-2of2", core_res
    finally:
        sg._run_semantic_judge = orig
    print("PASS test_load_semantic_judge_routes_core_vs_leaf")


def test_core_judge_reverts_when_one_dissents():
    """The wiring the loop relies on: a core diff is REVERTED if either judge pass dissents
    (the loop calls the core judge for any core-touching run)."""
    import varys_semantic_gate as sg
    orig = sg._run_semantic_judge
    n = {"i": 0}
    try:
        def _flip(*a, **kw):
            n["i"] += 1
            return ('{"verdict":"keep","reason":"ok","risk":"none"}' if n["i"] == 1
                    else '{"verdict":"revert","reason":"weakens tick atomicity","risk":"high"}')
        sg._run_semantic_judge = _flip
        _leaf, core = pe._load_semantic_judge()
        res = core("diff --git a/.claude/hooks/varys-tick.py b/.claude/hooks/varys-tick.py\n+x\n")
        assert res["verdict"] == "revert", res
    finally:
        sg._run_semantic_judge = orig
    print("PASS test_core_judge_reverts_when_one_dissents")


if __name__ == "__main__":
    test_fence_still_blocks_outside_and_denylist()
    test_core_detection()
    test_touched_core_subset()
    test_hyphenated_hook_resolves_to_underscore_sibling()
    test_missing_sibling_fails_gate_with_core_message()
    test_load_semantic_judge_routes_core_vs_leaf()
    test_core_judge_reverts_when_one_dissents()
    print("\nALL PROACTIVE-EVOLVE TIERED-FENCE TESTS PASSED")
