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


def test_dedup_strips_auto_prefix_from_gap_title():
    """Gap title that already has [Auto] prefix should still match."""
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "kamil_apply_learnings",
        pathlib.Path(__file__).parent.parent / ".claude/hooks/kamil-apply-learnings.py"
    )
    kal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kal)
    gap = {"title": "[Auto] Durable execution for kamil-listener", "what_to_build": "x", "why": "y", "priority": "P1", "effort": "medium"}
    existing_titles = {"[auto] durable execution for kamil-listener"}
    assert kal._is_duplicate(gap, existing_titles) is True


def test_fetch_existing_titles_returns_none_on_network_error():
    """_fetch_existing_ticket_titles returns None (not empty set) on API failure."""
    import importlib.util, pathlib, urllib.error
    from unittest.mock import patch
    spec = importlib.util.spec_from_file_location(
        "kamil_apply_learnings",
        pathlib.Path(__file__).parent.parent / ".claude/hooks/kamil-apply-learnings.py"
    )
    kal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kal)
    with patch("urllib.request.urlopen", side_effect=OSError("network down")):
        result = kal._fetch_existing_ticket_titles("fake-token")
    assert result is None


def test_slack_message_includes_why():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "kamil_apply_learnings",
        pathlib.Path(__file__).parent.parent / ".claude/hooks/kamil-apply-learnings.py"
    )
    kal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kal)
    item = {
        "gap": {
            "title": "Adversarial checker agent",
            "what_to_build": "Add an agent that verifies Kamil outputs",
            "why": "Lesson: silent failures are invisible without an adversary",
            "priority": "P0",
            "effort": "medium",
        },
        "page_id": "abc123def456",
    }
    msg = kal._format_slack_message([item], ["[tech] harness research"])
    assert "silent failures" in msg
    assert "abc123" in msg
