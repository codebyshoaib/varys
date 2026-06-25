#!/usr/bin/env python3
"""
test_varys_skill_evolve.py — self-check for varys-skill-evolve.py.

Tests gate_content (empty/no-title/too-long/valid) and the _is_allowed fence
(correct dir + .md only, wrong dir denied, non-.md denied).
Hermetic: imports the hyphen-named module via importlib; no subprocess, no network.

Run: python3 .claude/hooks/test_varys_skill_evolve.py
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

HOOKS = Path(__file__).parent
sys.path.insert(0, str(HOOKS))

spec = importlib.util.spec_from_file_location(
    "varys_skill_evolve", HOOKS / "varys-skill-evolve.py")
se = importlib.util.module_from_spec(spec)
spec.loader.exec_module(se)


# ── gate_content tests ─────────────────────────────────────────────────────

def test_gate_content_empty_file_fails():
    with tempfile.TemporaryDirectory() as d:
        skill_dir = Path(d) / ".claude" / "skills" / "varys"
        skill_dir.mkdir(parents=True)
        f = skill_dir / "empty.md"
        f.write_text("")

        orig = se._WORK_DIR
        se._WORK_DIR = Path(d)
        try:
            ok, reason = se.gate_content([".claude/skills/varys/empty.md"])
            assert ok is False, "empty file must fail gate_content"
            assert "empty" in reason
        finally:
            se._WORK_DIR = orig
    print("PASS test_gate_content_empty_file_fails")


def test_gate_content_no_title_fails():
    with tempfile.TemporaryDirectory() as d:
        skill_dir = Path(d) / ".claude" / "skills" / "varys"
        skill_dir.mkdir(parents=True)
        f = skill_dir / "no_title.md"
        f.write_text("Some content without a title line.\n\nMore content here.\n")

        orig = se._WORK_DIR
        se._WORK_DIR = Path(d)
        try:
            ok, reason = se.gate_content([".claude/skills/varys/no_title.md"])
            assert ok is False, "file without # title must fail gate_content"
            assert "title" in reason.lower()
        finally:
            se._WORK_DIR = orig
    print("PASS test_gate_content_no_title_fails")


def test_gate_content_too_long_fails():
    with tempfile.TemporaryDirectory() as d:
        skill_dir = Path(d) / ".claude" / "skills" / "varys"
        skill_dir.mkdir(parents=True)
        f = skill_dir / "toolong.md"
        lines = ["# Too Long Skill\n"] + [f"- line {i}\n" for i in range(201)]
        f.write_text("".join(lines))

        orig = se._WORK_DIR
        se._WORK_DIR = Path(d)
        try:
            ok, reason = se.gate_content([".claude/skills/varys/toolong.md"])
            assert ok is False, "file >200 lines must fail gate_content"
            assert "200" in reason or "lines" in reason.lower()
        finally:
            se._WORK_DIR = orig
    print("PASS test_gate_content_too_long_fails")


def test_gate_content_valid_skill_passes():
    with tempfile.TemporaryDirectory() as d:
        skill_dir = Path(d) / ".claude" / "skills" / "varys"
        skill_dir.mkdir(parents=True)
        f = skill_dir / "valid.md"
        f.write_text("# Valid Skill\n\n## Rules\n- Do the thing.\n")

        orig = se._WORK_DIR
        se._WORK_DIR = Path(d)
        try:
            ok, reason = se.gate_content([".claude/skills/varys/valid.md"])
            assert ok is True, f"valid skill must pass gate_content: {reason}"
            assert reason == ""
        finally:
            se._WORK_DIR = orig
    print("PASS test_gate_content_valid_skill_passes")


def test_gate_content_deleted_file_skipped():
    """A file listed in changed but not on disk (deleted) is skipped without error."""
    with tempfile.TemporaryDirectory() as d:
        orig = se._WORK_DIR
        se._WORK_DIR = Path(d)
        try:
            ok, reason = se.gate_content([".claude/skills/varys/gone.md"])
            assert ok is True, f"deleted file should be skipped: {reason}"
        finally:
            se._WORK_DIR = orig
    print("PASS test_gate_content_deleted_file_skipped")


# ── gate_fence + _is_allowed tests ────────────────────────────────────────

def test_fence_allows_skill_md():
    assert se._is_allowed(".claude/skills/varys/routing.md")
    assert se._is_allowed(".claude/skills/varys/slack-replies.md")
    assert se._is_allowed(".claude/skills/varys/new-skill.md")
    print("PASS test_fence_allows_skill_md")


def test_fence_denies_wrong_dir():
    assert not se._is_allowed(".claude/hooks/foo.py")
    assert not se._is_allowed(".claude/rules/orchestrator.md")
    assert not se._is_allowed(".claude/agents/manager.md")
    assert not se._is_allowed("memory/active_learnings.md")
    assert not se._is_allowed("settings.json")
    print("PASS test_fence_denies_wrong_dir")


def test_fence_denies_non_markdown():
    assert not se._is_allowed(".claude/skills/varys/foo.py")
    assert not se._is_allowed(".claude/skills/varys/data.json")
    assert not se._is_allowed(".claude/skills/varys/script.sh")
    print("PASS test_fence_denies_non_markdown")


def test_fence_denies_denylist():
    assert not se._is_allowed(".claude/skills/varys/varys-skill-evolve.py")
    assert not se._is_allowed(".claude/skills/varys/settings.json")
    print("PASS test_fence_denies_denylist")


def test_gate_fence_reports_violations():
    ok, reason = se.gate_fence([".claude/skills/varys/ok.md",
                                ".claude/hooks/bad.py"])
    assert ok is False
    assert "bad.py" in reason
    print("PASS test_gate_fence_reports_violations")


def test_gate_fence_clean_passes():
    ok, reason = se.gate_fence([".claude/skills/varys/ok.md",
                                ".claude/skills/varys/other.md"])
    assert ok is True
    assert reason == ""
    print("PASS test_gate_fence_clean_passes")


if __name__ == "__main__":
    test_gate_content_empty_file_fails()
    test_gate_content_no_title_fails()
    test_gate_content_too_long_fails()
    test_gate_content_valid_skill_passes()
    test_gate_content_deleted_file_skipped()
    test_fence_allows_skill_md()
    test_fence_denies_wrong_dir()
    test_fence_denies_non_markdown()
    test_fence_denies_denylist()
    test_gate_fence_reports_violations()
    test_gate_fence_clean_passes()
    print("\nALL SKILL-EVOLVE TESTS PASSED")
    sys.exit(0)
