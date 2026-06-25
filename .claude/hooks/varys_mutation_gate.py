#!/usr/bin/env python3
"""
varys_mutation_gate.py — plug the vacuous-test hole in the evolution gate.

The evolve gate requires that a changed hook has a sibling test_<module>.py that PASSES.
But `assert True` passes too — a test that asserts nothing about the change satisfies the
gate while proving nothing. This module closes that: it mutates the lines the evolution
ACTUALLY changed, runs the sibling test against each mutant, and fails the gate only when
the test kills ZERO mutants (positive evidence the test doesn't exercise the new code).

Design choices (deliberately conservative — a gate that blocks good work is worse than the
hole it plugs):
  - Scope = changed lines only. A test for gate_content shouldn't be expected to catch a
    mutation in an unrelated function. We mutate the diff, not the whole file.
  - Fail-OPEN on the checker's own errors. A bug in this module must never block evolution.
  - Verdict 'revert' ONLY when mutants were generated AND none were killed. No mutable
    construct on the changed lines → 'keep' (can't conclude the test is toothless).

Stdlib only (ast, subprocess, tempfile) — no new dependency, per house rules.

Used by varys-proactive-evolve.py as an extra gate after gate_tests passes.
"""

import ast
import subprocess
import sys
from pathlib import Path

MAX_MUTANTS   = 12     # cap mutants per hook so a big diff can't blow the time budget
PER_TEST_SECS = 60     # timeout for one sibling-test run against one mutant

# Comparison-operator swaps (each maps to its logical inverse/sibling).
_CMP_SWAP = {
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
    ast.Lt: ast.GtE,  ast.GtE: ast.Lt,
    ast.Gt: ast.LtE,  ast.LtE: ast.Gt,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
}
_BOOL_SWAP = {ast.And: ast.Or, ast.Or: ast.And}


def changed_line_numbers(work_dir, rel, base_sha) -> set:
    """Added/modified line numbers in the NEW version of `rel` since base_sha.
    Parses `git diff -U0` hunk headers (@@ -a,b +c,d @@). Returns an empty set on any error."""
    try:
        r = subprocess.run(
            ["git", "diff", "-U0", base_sha, "--", rel],
            cwd=str(work_dir), capture_output=True, text=True, timeout=30)
    except Exception:
        return set()
    lines = set()
    for ln in r.stdout.splitlines():
        if not ln.startswith("@@"):
            continue
        # @@ -old,oldn +new,newn @@
        try:
            plus = ln.split("+", 1)[1].split(" ", 1)[0]   # "new,newn" or "new"
            start = int(plus.split(",")[0])
            count = int(plus.split(",")[1]) if "," in plus else 1
        except (IndexError, ValueError):
            continue
        for i in range(start, start + max(count, 1)):
            lines.add(i)
    return lines


class _Mutator(ast.NodeTransformer):
    """Apply exactly ONE mutation at a target line, then stop. Re-instantiated per mutant."""
    def __init__(self, target_lines, skip):
        self.target_lines = target_lines
        self.skip = skip          # how many eligible sites to skip before mutating
        self.done = False
        self._seen = 0

    def _fire(self, node) -> bool:
        if self.done:
            return False
        if getattr(node, "lineno", None) not in self.target_lines:
            return False
        self._seen += 1
        if self._seen <= self.skip:
            return False
        return True

    def visit_Compare(self, node):
        self.generic_visit(node)
        if node.ops and type(node.ops[0]) in _CMP_SWAP and self._fire(node):
            node.ops[0] = _CMP_SWAP[type(node.ops[0])]()
            self.done = True
        return node

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        if type(node.op) in _BOOL_SWAP and self._fire(node):
            node.op = _BOOL_SWAP[type(node.op)]()
            self.done = True
        return node

    def visit_Constant(self, node):
        if isinstance(node.value, bool) and self._fire(node):
            node.value = not node.value
            self.done = True
        elif isinstance(node.value, int) and not isinstance(node.value, bool) and self._fire(node):
            node.value = node.value + 1
            self.done = True
        return node

    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        if isinstance(node.op, ast.Not) and self._fire(node):
            # strip the `not` → return the operand directly
            return node.operand
        return node


def _generate_mutants(src, target_lines):
    """Yield up to MAX_MUTANTS (label, mutated_source) pairs mutating target_lines.
    Each mutant flips exactly one construct; we walk the skip index until no more fire."""
    try:
        base_tree = ast.parse(src)
    except SyntaxError:
        return
    mutants = []
    for skip in range(MAX_MUTANTS * 3):     # try more sites than we keep; many won't fire
        if len(mutants) >= MAX_MUTANTS:
            break
        tree = ast.parse(src)               # fresh tree each time (transform is destructive)
        m = _Mutator(target_lines, skip)
        new_tree = m.visit(tree)
        if not m.done:
            # no eligible site at this skip index → if we've passed all sites, stop
            if skip > m._seen:
                break
            continue
        ast.fix_missing_locations(new_tree)
        try:
            mutated = ast.unparse(new_tree)
        except Exception:
            continue
        if mutated != src:
            mutants.append((f"mut#{len(mutants)+1}", mutated))
    return mutants


def mutation_check(rel, work_dir, base_sha, timeout=PER_TEST_SECS) -> dict:
    """Mutate the changed lines of hook `rel` and run its sibling test against each mutant.

    Returns {verdict: keep|revert, reason, mutants, killed}. Fails OPEN (verdict=keep) on
    any internal error — a checker bug must never block evolution."""
    try:
        work = Path(work_dir)
        stem = Path(rel).stem
        sibling = work / ".claude" / "hooks" / f"test_{stem}.py"
        hook = work / rel
        if not sibling.exists() or not hook.exists():
            return {"verdict": "keep", "reason": "no sibling test / hook absent (other gate's job)",
                    "mutants": 0, "killed": 0}

        target = changed_line_numbers(work, rel, base_sha)
        if not target:
            return {"verdict": "keep", "reason": "no changed lines resolved — skipping mutation check",
                    "mutants": 0, "killed": 0}

        original = hook.read_text()
        mutants = _generate_mutants(original, target) or []
        if not mutants:
            return {"verdict": "keep",
                    "reason": "no mutable construct on changed lines — cannot assess test teeth",
                    "mutants": 0, "killed": 0}

        killed = 0
        try:
            for _, mutated in mutants:
                hook.write_text(mutated)
                try:
                    r = subprocess.run(["python3", str(sibling)],
                                       cwd=str(work), capture_output=True, text=True, timeout=timeout)
                    if r.returncode != 0:      # test failed against the mutant → caught it
                        killed += 1
                except subprocess.TimeoutExpired:
                    killed += 1                # a hang on a mutant counts as caught (behavior changed)
        finally:
            hook.write_text(original)          # ALWAYS restore, even mid-loop

        if killed == 0:
            return {"verdict": "revert",
                    "reason": (f"sibling test_{stem}.py killed 0/{len(mutants)} mutants on the "
                               f"changed lines — the test does not exercise this change"),
                    "mutants": len(mutants), "killed": 0}
        return {"verdict": "keep",
                "reason": f"test killed {killed}/{len(mutants)} mutants — has teeth",
                "mutants": len(mutants), "killed": killed}

    except Exception as e:
        return {"verdict": "keep", "reason": f"mutation check errored (fail-open): {e}",
                "mutants": 0, "killed": 0}


if __name__ == "__main__":
    print("varys_mutation_gate: importable;", _CMP_SWAP and "swaps loaded")
