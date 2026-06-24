#!/usr/bin/env python3
"""
test_stop.py — self-check for the Stop hook's pure decision logic.

Hermetic: imports the underscore-safe module via importlib; never calls main() (which runs
git, mempalace, claude, and the brain watcher). We exercise the pure helpers:
  - _is_meaningful: a session-log turn is recorded iff it names a known person OR contains a
    decision keyword — this is the filter that keeps trivial chatter out of relationship memory
  - _extract_persons: Title-Case name extraction, with resolve_person stubbed so NO brain.db
    read happens (and the not-available short-circuit returns [])

COVERAGE NOTE: most of stop.py is side-effecting I/O (commit, STANDUP rewrite, brain seed);
those are integration concerns, not unit-testable pure logic. The meaningful-turn filter is
the real decision surface and is fully covered here.

Run: python3 .claude/hooks/test_stop.py
"""
import importlib.util
import sys
from pathlib import Path

HOOKS = Path(__file__).parent
sys.path.insert(0, str(HOOKS))
spec = importlib.util.spec_from_file_location("stop_hook", HOOKS / "stop.py")
st = importlib.util.module_from_spec(spec)
spec.loader.exec_module(st)


def test_is_meaningful():
    # a turn naming a known person is meaningful regardless of content
    assert st._is_meaningful("just chatting", person_ids=["p1"]) is True
    # a decision keyword makes a turn meaningful even with no person
    for kw in ("decided", "approved", "blocked", "done", "confirmed"):
        assert st._is_meaningful(f"we {kw} the plan", person_ids=[]) is True, kw
    # neither a person nor a keyword → not meaningful (filtered out of memory)
    assert st._is_meaningful("random small talk", person_ids=[]) is False
    print("PASS test_is_meaningful")


def test_extract_persons_short_circuits_when_unavailable():
    """When the people-context layer is unavailable, extraction must return [] (never crash)."""
    orig = st._context_available
    try:
        st._context_available = False
        assert st._extract_persons("Met with Ali Khan today") == []
    finally:
        st._context_available = orig
    print("PASS test_extract_persons_short_circuits_when_unavailable")


def test_extract_persons_resolves_titlecase_names():
    """With resolve_person stubbed (no brain.db read), the Title-Case regex must find
    multi-word capitalised names and dedupe by entity id."""
    if not st._context_available:
        print("PASS test_extract_persons_resolves_titlecase_names (skipped — context layer not importable)")
        return

    class _P:
        def __init__(self, name, eid):
            self.name, self.entity_id = name, eid

    seen = {}
    def _stub_resolve(name):
        # resolve only "Ali Khan"; raise PersonNotFound for anything else
        if name == "Ali Khan":
            return seen.setdefault(name, _P(name, "ent-ali"))
        raise st.PersonNotFound(name)

    orig = st.resolve_person
    try:
        st.resolve_person = _stub_resolve
        # "Ali Khan" appears twice → must dedupe to one; "the System" is not a person
        persons = st._extract_persons("Ali Khan and Ali Khan synced; the System logged it")
        assert len(persons) == 1 and persons[0].entity_id == "ent-ali", persons
        # a single capitalised word is NOT a candidate (regex requires 2+ words)
        assert st._extract_persons("Hello there") == []
    finally:
        st.resolve_person = orig
    print("PASS test_extract_persons_resolves_titlecase_names")


if __name__ == "__main__":
    test_is_meaningful()
    test_extract_persons_short_circuits_when_unavailable()
    test_extract_persons_resolves_titlecase_names()
    print("\nALL STOP TESTS PASSED")
