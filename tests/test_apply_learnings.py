import sys
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "kamil_apply_learnings",
    Path(__file__).parent.parent / ".claude/hooks/kamil-apply-learnings.py",
)
kal = importlib.util.module_from_spec(spec)
sys.modules["kamil_apply_learnings"] = kal
spec.loader.exec_module(kal)


def test_dedup_skips_existing_title():
    gap = {"title": "Durable execution for kamil-listener", "what_to_build": "x", "why": "y", "priority": "P1", "effort": "medium"}
    existing_titles = {"[auto] durable execution for kamil-listener"}
    assert kal._is_duplicate(gap, existing_titles) is True


def test_dedup_allows_new_title():
    gap = {"title": "Brand new feature nobody built yet", "what_to_build": "x", "why": "y", "priority": "P1", "effort": "medium"}
    existing_titles = {"[auto] durable execution for kamil-listener"}
    assert kal._is_duplicate(gap, existing_titles) is False
