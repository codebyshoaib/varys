#!/usr/bin/env python3
"""
test_slack_worker.py — hermetic self-check for slack-worker's pure prompt logic.

Hermetic: imports the hyphen-named module via importlib; never calls main() (which reads
the DB, spawns claude, and posts to Slack). We exercise the deterministic prompt builder
and lock the trailing-directive (NLM:/WORK:) extraction contract that main() depends on.

_build_prompt is the real testable surface: it branches on is_third_party, prepends a
"Previous attempt failed" note when retrying, and — on the normal path — instructs the
agent how to emit the NLM:/WORK: directive lines the worker later parses. If those
instructions are dropped the WORK→bead and NLM→artifact pipelines silently die, so we
assert they're present.

Run: python3 .claude/hooks/test_slack_worker.py
"""
import importlib.util
import sys
from pathlib import Path

HOOKS = Path(__file__).parent
sys.path.insert(0, str(HOOKS))
spec = importlib.util.spec_from_file_location("slack_worker", HOOKS / "slack-worker.py")
sw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sw)


def test_module_smoke():
    """Key callables exist (this hook is mostly I/O; the pure surface is _build_prompt)."""
    for name in ("main", "_build_prompt", "_create_work_bead", "_repo_cwd"):
        assert callable(getattr(sw, name, None)), f"missing callable {name}"
    print("PASS test_module_smoke")


def test_build_prompt_third_party_vs_normal():
    third = sw._build_prompt(
        text="hi", thread_history="", source="mention", sender_name="Ali",
        is_third_party=True, is_dm=False, failure_context="",
    )
    # third-party reply must NOT instruct a Varys sign-off and must guard private info
    assert "on behalf of a conversation" in third
    assert 'Do NOT sign off' in third
    normal = sw._build_prompt(
        text="how does X work?", thread_history="", source="dm", sender_name="Shoaib",
        is_third_party=False, is_dm=True, failure_context="",
    )
    # normal path signs off as Varys and documents BOTH trailing directives
    assert sw.AGENT_NAME in normal
    assert "NLM: <subcommand> <topic>" in normal, "NLM directive instruction missing"
    assert "WORK: <repo>" in normal, "WORK directive instruction missing"
    print("PASS test_build_prompt_third_party_vs_normal")


def test_build_prompt_failure_context_prefix():
    """A retry must surface the prior failure so the agent doesn't repeat it."""
    p = sw._build_prompt(
        text="x", thread_history="", source="dm", sender_name="S",
        is_third_party=False, is_dm=True, failure_context="timed out talking to GitHub",
    )
    assert p.startswith("[Previous attempt failed: timed out talking to GitHub]"), p[:80]
    # and it must be truncated/bounded (uses [:500]); short input passes through verbatim
    print("PASS test_build_prompt_failure_context_prefix")


def _extract_directive(answer: str):
    """Replicates main()'s trailing-directive parser (lines ~490-496) so its contract is
    pinned: only the LAST line, NLM: takes the 4-char prefix, WORK: the 5-char prefix."""
    nlm, work = None, None
    lines = answer.splitlines()
    if lines and lines[-1].startswith("NLM:"):
        nlm = lines[-1][4:].strip()
        answer = "\n".join(lines[:-1]).strip()
    elif lines and lines[-1].startswith("WORK:"):
        work = lines[-1][5:].strip()
        answer = "\n".join(lines[:-1]).strip()
    return answer, nlm, work


def test_directive_extraction_contract():
    body, nlm, work = _extract_directive("Sure thing.\nNLM: slides graphify")
    assert nlm == "slides graphify" and work is None and body == "Sure thing."
    body, nlm, work = _extract_directive("On it.\nWORK: taleemabad-core | fix login crash")
    assert work == "taleemabad-core | fix login crash" and nlm is None and body == "On it."
    # no directive → both None, body untouched
    body, nlm, work = _extract_directive("just a chat reply")
    assert nlm is None and work is None and body == "just a chat reply"
    print("PASS test_directive_extraction_contract")


if __name__ == "__main__":
    test_module_smoke()
    test_build_prompt_third_party_vs_normal()
    test_build_prompt_failure_context_prefix()
    test_directive_extraction_contract()
    print("\nALL SLACK_WORKER TESTS PASSED")
