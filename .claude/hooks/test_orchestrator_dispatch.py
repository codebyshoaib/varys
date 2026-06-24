#!/usr/bin/env python3
"""
test_orchestrator_dispatch.py — hermetic self-check for the dispatcher's pure logic.

Hermetic: imports the hyphen-named module via importlib (no get_db / no claude / no HTTP is
invoked — main() is never called). We only exercise the deterministic helpers:
  - _page_title / _page_status for BOTH bead (flat) and Notion (nested) page shapes,
    including the Phase-before-Status precedence the Harness DB relies on
  - _build_subagent_prompt embeds the orchestrator invariants the spawned agent must obey
    (plan-first, "Status=Done LAST", the two-query context_key wiring) — if a refactor drops
    them from the prompt the agent silently loses its rules, so we assert they're present
  - _load_config lets an env var override file config
  - _available_skills tolerates a missing skills dir

Run: python3 .claude/hooks/test_orchestrator_dispatch.py
"""
import importlib.util
import os
import sys
from pathlib import Path

HOOKS = Path(__file__).parent
sys.path.insert(0, str(HOOKS))
spec = importlib.util.spec_from_file_location("orchestrator_dispatch",
                                              HOOKS / "orchestrator-dispatch.py")
od = importlib.util.module_from_spec(spec)
spec.loader.exec_module(od)


def test_page_title_bead_and_notion():
    # Bead (flat) format
    assert od._page_title({"id": "bd-1", "title": "Fix login"}) == "Fix login"
    assert od._page_title({"id": "bd-1", "title": ""}) == "Untitled"
    # Notion (nested) format
    notion = {"properties": {"Name": {"type": "title",
              "title": [{"plain_text": "Hello "}, {"plain_text": "world"}]}}}
    assert od._page_title(notion) == "Hello world"
    assert od._page_title({"properties": {}}) == "Untitled"
    print("PASS test_page_title_bead_and_notion")


def test_page_status_bead_and_notion_phase_precedence():
    # Bead (flat) format
    assert od._page_status({"id": "x", "status": "open"}) == "open"
    assert od._page_status({"id": "x", "status": ""}) == "Unknown"
    # Notion: Harness DB uses "Phase" (select) and it must win over a "Status" prop.
    page = {"properties": {
        "Phase":  {"type": "select", "select": {"name": "In progress"}},
        "Status": {"type": "status", "status": {"name": "Done"}},
    }}
    assert od._page_status(page) == "In progress", "Phase must be read before Status"
    # status-type prop when no Phase present
    only_status = {"properties": {"Status": {"type": "status", "status": {"name": "Blocked"}}}}
    assert od._page_status(only_status) == "Blocked"
    assert od._page_status({"properties": {}}) == "Unknown"
    print("PASS test_page_status_bead_and_notion_phase_precedence")


def test_build_subagent_prompt_carries_invariants():
    prompt = od._build_subagent_prompt(
        context_key="ctx-123",
        events=[{"type": "ticket.created"}],
        notion_page={"id": "bd-1", "title": "Fix the thing"},
        linked_entities=[],
        slack_messages=[{"user": "U1", "text": "hi"}],
        github_pr=None,
        session_id="session-abc",
        cfg={"GITHUB_REPO": "org/repo"},
    )
    # context_key + session_id are wired through verbatim (the agent uses them in its SQL)
    assert "ctx-123" in prompt and "session-abc" in prompt
    # plan-first invariant (rule 9) and Status=Done-LAST invariant (rule 2) must survive
    assert "PLAN-FIRST" in prompt, "plan-first rule dropped from subagent prompt"
    assert "STATUS=DONE IS ALWAYS THE LAST" in prompt, "Status=Done-LAST rule dropped"
    # the agent is told to gate Phase 2 on the human "@Varys go" approval
    assert "@Varys go" in prompt
    # ticket fields resolved from the bead-format page
    assert "Fix the thing" in prompt
    # the slack thread context made it in
    assert "SLACK THREAD" in prompt
    print("PASS test_build_subagent_prompt_carries_invariants")


def test_load_config_env_overrides_file():
    os.environ["NOTION_API_KEY"] = "env-secret-123"
    try:
        cfg = od._load_config()
        assert cfg.get("NOTION_API_KEY") == "env-secret-123", "env must override file config"
    finally:
        del os.environ["NOTION_API_KEY"]
    print("PASS test_load_config_env_overrides_file")


def test_available_skills_returns_list():
    skills = od._available_skills()
    assert isinstance(skills, list), "available_skills must always return a list (never raise)"
    print("PASS test_available_skills_returns_list")


if __name__ == "__main__":
    test_page_title_bead_and_notion()
    test_page_status_bead_and_notion_phase_precedence()
    test_build_subagent_prompt_carries_invariants()
    test_load_config_env_overrides_file()
    test_available_skills_returns_list()
    print("\nALL ORCHESTRATOR_DISPATCH TESTS PASSED")
