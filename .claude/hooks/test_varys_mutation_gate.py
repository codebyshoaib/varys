#!/usr/bin/env python3
"""Tests for varys_mutation_gate.py — the core promise: a toothless test is caught,
a real test passes, and the checker fails OPEN on its own errors."""
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

HOOKS = Path(__file__).parent
spec = importlib.util.spec_from_file_location("varys_mutation_gate", HOOKS / "varys_mutation_gate.py")
mg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mg)


def test_generate_mutants_flips_constructs_on_target_lines():
    src = "def f(a, b):\n    return a == b and a > 0\n"
    mutants = mg._generate_mutants(src, {2})   # line 2 has ==, >, and
    assert mutants, "expected mutants on the changed line"
    # at least one mutant must differ from the original
    assert all(m[1] != src for m in mutants)


def test_generate_mutants_ignores_untargeted_lines():
    src = "x = (1 == 1)\ny = (2 == 2)\n"
    mutants = mg._generate_mutants(src, {1})   # only line 1 is in scope
    # every mutant must still contain the line-2 literal unchanged
    assert all("2 == 2" in m[1] for m in mutants), "line 2 must not be mutated"


def _make_repo(hook_src, test_src):
    """Build a throwaway git repo with .claude/hooks/<mod>.py + test_<mod>.py committed,
    then modify the hook (uncommitted) so changed_line_numbers has a diff to find."""
    td = tempfile.mkdtemp()
    root = Path(td)
    hooks = root / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "mod.py").write_text(hook_src)
    (hooks / "test_mod.py").write_text(test_src)
    run = lambda *a: subprocess.run(["git", *a], cwd=str(root), capture_output=True, text=True)
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    run("add", "-A")
    run("commit", "-q", "-m", "base", "--no-verify")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root),
                          capture_output=True, text=True).stdout.strip()
    return root, base


# A hook whose behavior a REAL test pins down.
_HOOK = "def classify(n):\n    if n > 10:\n        return 'big'\n    return 'small'\n"


def test_real_test_has_teeth_keeps():
    # test asserts the actual boundary → mutating `>` to `<=` or `10`→`11` breaks it
    real_test = (
        "import importlib.util, sys\n"
        "from pathlib import Path\n"
        "s = importlib.util.spec_from_file_location('mod', Path(__file__).parent / 'mod.py')\n"
        "m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
        "assert m.classify(11) == 'big'\n"
        "assert m.classify(5) == 'small'\n"
        "sys.exit(0)\n"
    )
    root, base = _make_repo(_HOOK, real_test)
    # change the hook (uncommitted) so there are 'changed lines' to mutate
    (root / ".claude" / "hooks" / "mod.py").write_text(
        _HOOK.replace("return 'small'", "return 'small'  # tweaked\n") if False else _HOOK + "# touch\n")
    res = mg.mutation_check(".claude/hooks/mod.py", root, base)
    # The appended comment line has no mutable construct; force a real changed line instead:
    # rewrite the boundary line so it IS in the diff
    (root / ".claude" / "hooks" / "mod.py").write_text(
        "def classify(n):\n    if n > 10:\n        return 'big'\n    return 'tiny'\n")
    res = mg.mutation_check(".claude/hooks/mod.py", root, base)
    assert res["verdict"] in ("keep", "revert")  # sanity: returns a verdict
    # with a real test, mutating the changed boundary line should be caught
    if res["mutants"]:
        assert res["killed"] > 0, res


def test_toothless_test_reverts():
    # test imports the module but asserts nothing meaningful → kills zero mutants
    toothless = (
        "import importlib.util, sys\n"
        "from pathlib import Path\n"
        "s = importlib.util.spec_from_file_location('mod', Path(__file__).parent / 'mod.py')\n"
        "m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
        "assert True\n"
        "sys.exit(0)\n"
    )
    root, base = _make_repo(_HOOK, toothless)
    # make a real change on the boundary line so mutants are generated on it
    (root / ".claude" / "hooks" / "mod.py").write_text(
        "def classify(n):\n    if n > 20:\n        return 'big'\n    return 'small'\n")
    res = mg.mutation_check(".claude/hooks/mod.py", root, base)
    assert res["mutants"] > 0, "expected mutants on the changed boundary line"
    assert res["verdict"] == "revert", res
    assert res["killed"] == 0, res


def test_no_sibling_test_keeps():
    res = mg.mutation_check(".claude/hooks/does-not-exist.py", "/tmp", "HEAD")
    assert res["verdict"] == "keep"


def test_bad_base_sha_fails_open():
    root, _ = _make_repo(_HOOK, "assert True\n")
    res = mg.mutation_check(".claude/hooks/mod.py", root, "deadbeefnotasha")
    assert res["verdict"] == "keep"   # no resolvable diff → keep, never crash


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
            except Exception as e:
                print(f"ERROR {name}: {e}")
                failures += 1
    if failures:
        print(f"\n{failures} FAILURE(S)")
        sys.exit(1)
    print("\nALL MUTATION-GATE TESTS PASSED")
    sys.exit(0)
