#!/usr/bin/env python3
"""
test_varys_manager.py — hermetic self-check for the manager's pure helpers.

Hermetic: imports the hyphen-named module via importlib; never calls run_manager_phase /
run_worker_phase (those spawn claude + post to Slack). We exercise only deterministic logic:
  - _slugify (branch-name derivation: lowercase, spaces/underscores → '-', strip, <=40)
  - _agent_to_skill mapping (which agents feed which synthesis skill; None for unmapped)
  - _load_registry (parses repos-registry.json, unwrapping the {"repos": {...}} envelope)
  - _load_cfg env override
  - SHOAIB_DM invariant: when a ticket has no Slack origin thread the manager DMs Shoaib
    rather than guessing a public channel — assert the constant is a real user id

Run: python3 .claude/hooks/test_varys_manager.py
"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

HOOKS = Path(__file__).parent
sys.path.insert(0, str(HOOKS))
spec = importlib.util.spec_from_file_location("varys_manager", HOOKS / "varys-manager.py")
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)


def test_slugify():
    assert vm._slugify("Fix the Login Bug!") == "fix-the-login-bug"
    assert vm._slugify("multiple   spaces__and-dashes") == "multiple-spaces-and-dashes"
    assert vm._slugify("  trim me  ") == "trim-me"
    # length cap at 40 chars
    long = vm._slugify("x" * 100)
    assert len(long) <= 40, f"slug must be capped at 40 chars, got {len(long)}"
    print("PASS test_slugify")


def test_agent_to_skill_mapping():
    assert vm._agent_to_skill("research-agent") == "research"
    assert vm._agent_to_skill("people-agent") == "helping-team"
    # product-lead + notion-agent are explicitly mapped to None (no synthesis skill update)
    assert vm._agent_to_skill("product-lead") is None
    assert vm._agent_to_skill("notion-agent") is None
    # an unknown agent falls through to None
    assert vm._agent_to_skill("nonexistent-agent") is None
    print("PASS test_agent_to_skill_mapping")


def test_load_registry_unwraps_repos_envelope():
    """_load_registry returns the inner mapping whether the file is {"repos": {...}} or flat."""
    orig = vm.RULES_DIR
    with tempfile.TemporaryDirectory() as d:
        vm.RULES_DIR = Path(d)
        try:
            # envelope form
            (Path(d) / "repos-registry.json").write_text(json.dumps(
                {"repos": {"taleemabad-core": {"abs_path": "/x", "branch": "develop"}}}))
            reg = vm._load_registry()
            assert reg["taleemabad-core"]["branch"] == "develop", reg
            # missing file → empty dict (never raises)
            (Path(d) / "repos-registry.json").unlink()
            assert vm._load_registry() == {}
        finally:
            vm.RULES_DIR = orig
    print("PASS test_load_registry_unwraps_repos_envelope")


def test_load_cfg_env_override():
    os.environ["GITHUB_TOKEN"] = "ghp-test-xyz"
    try:
        cfg = vm._load_cfg()
        assert cfg.get("GITHUB_TOKEN") == "ghp-test-xyz", "env var must override file cfg"
    finally:
        del os.environ["GITHUB_TOKEN"]
    print("PASS test_load_cfg_env_override")


def test_shoaib_dm_is_a_user_id():
    """No-origin-thread fallback must be a Slack USER id (DM), not a public channel id.
    Slack user ids start with 'U'; channel ids start with 'C'/'G'. This guards the
    'never guess a public channel' invariant in run_manager_phase / run_worker_phase."""
    assert isinstance(vm.SHOAIB_DM, str) and vm.SHOAIB_DM.startswith("U"), vm.SHOAIB_DM
    print("PASS test_shoaib_dm_is_a_user_id")


if __name__ == "__main__":
    test_slugify()
    test_agent_to_skill_mapping()
    test_load_registry_unwraps_repos_envelope()
    test_load_cfg_env_override()
    test_shoaib_dm_is_a_user_id()
    print("\nALL VARYS_MANAGER TESTS PASSED")
