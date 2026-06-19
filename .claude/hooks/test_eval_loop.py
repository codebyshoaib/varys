#!/usr/bin/env python3
"""
test_eval_loop.py — Self-check for the nightly self-improvement loop's pure logic.

No framework, asserts only, temp files. Makes NO live Notion/Slack/Claude calls.
Run: python3 .claude/hooks/test_eval_loop.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOOKS = Path(__file__).parent
sys.path.insert(0, str(HOOKS))

# A captured sample of real run-tier1.sh stdout (trimmed but representative):
# indented "  OK ..." / "  FAIL ..." per-check lines, plus freshness lines that
# include a "  STALE ..." line the parser MUST NOT count as either OK or FAIL.
TIER1_SAMPLE = """== Tier-1: eval route files exist ==
  OK .claude/rules/notion.md
  OK .claude/rules/slack.md
  FAIL missing route: .claude/rules/ghost.md (x.yaml)
== Tier-1: markdown frontmatter (rules/standards/memory) ==
  OK fm .claude/rules/content.md
  FAIL no frontmatter: .claude/rules/people.md
== Tier-1: CLAUDE.md <=150 lines ==
  OK CLAUDE.md 137 lines
== Tier-1: freshness (rules within 31 days of last_verified) ==
  OK .claude/rules/notion.md (3d)
  STALE .claude/rules/old.md (90d)
  FAIL no last_verified: .claude/rules/people.md
TIER-1: FAIL
"""


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_mint_failures_dedupes_by_page_id():
    """Same page_id minted twice (across runs) -> only one failure entry."""
    import varys_eval
    with tempfile.TemporaryDirectory() as d:
        fpath = Path(d) / "failures.jsonl"
        varys_eval.FAILURES_FILE = fpath  # redirect to temp

        rows = [{"page_id": "abc123", "failure_type": "wrong-intent",
                 "note": "did the opposite"}]

        n1 = varys_eval._mint_failures(rows)
        assert n1 == 1, f"first mint should write 1, got {n1}"

        # Same page_id again on a later run — must NOT duplicate.
        n2 = varys_eval._mint_failures(rows)
        assert n2 == 0, f"second mint of same page_id should write 0, got {n2}"

        lines = [l for l in fpath.read_text().splitlines() if l.strip()]
        assert len(lines) == 1, f"file should hold exactly 1 entry, got {len(lines)}"

        entry = json.loads(lines[0])
        # ts is REQUIRED so the evolution counter sees the entry.
        assert "ts" in entry and entry["ts"], "minted entry must carry a ts field"
        assert entry["page_id"] == "abc123"
        assert entry["source"] == "auto-judge"
        assert entry["root_cause"] == "wrong-intent"
    print("PASS test_mint_failures_dedupes_by_page_id")


def test_mint_failures_dedupes_within_batch():
    """Two rows with the same page_id in one batch -> one entry."""
    import varys_eval
    with tempfile.TemporaryDirectory() as d:
        fpath = Path(d) / "failures.jsonl"
        varys_eval.FAILURES_FILE = fpath
        rows = [
            {"page_id": "dup1", "failure_type": "x", "note": "1"},
            {"page_id": "dup1", "failure_type": "x", "note": "2"},
            {"page_id": "uniq", "failure_type": "y", "note": "3"},
        ]
        n = varys_eval._mint_failures(rows)
        assert n == 2, f"expected 2 unique mints, got {n}"
        lines = [l for l in fpath.read_text().splitlines() if l.strip()]
        assert len(lines) == 2
    print("PASS test_mint_failures_dedupes_within_batch")


def test_mint_failures_skips_blank_page_id():
    import varys_eval
    with tempfile.TemporaryDirectory() as d:
        fpath = Path(d) / "failures.jsonl"
        varys_eval.FAILURES_FILE = fpath
        rows = [{"page_id": "", "failure_type": "z", "note": "n"}]
        n = varys_eval._mint_failures(rows)
        assert n == 0, f"blank page_id must be skipped, got {n}"
        assert not fpath.exists() or not fpath.read_text().strip()
    print("PASS test_mint_failures_skips_blank_page_id")


def test_is_worse_more_fails_triggers_revert():
    """More FAIL lines after the run -> revert path chosen."""
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    # before (ok, fail, rc), after
    assert evo._is_worse((10, 1, 0), (9, 3, 0)) is True, "more fails should be worse"
    print("PASS test_is_worse_more_fails_triggers_revert")


def test_is_worse_exit_code_regression_triggers_revert():
    """Exit code 0 -> 1 (even with same fail count parsing) is worse."""
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    assert evo._is_worse((10, 0, 0), (10, 0, 1)) is True, "rc 0->1 should be worse"
    print("PASS test_is_worse_exit_code_regression_triggers_revert")


def test_is_worse_no_regression_keeps_edits():
    """Equal or better -> not worse, keep edits."""
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    assert evo._is_worse((10, 2, 0), (10, 2, 0)) is False, "equal is not worse"
    assert evo._is_worse((10, 2, 1), (12, 0, 0)) is False, "improvement is not worse"
    print("PASS test_is_worse_no_regression_keeps_edits")


def test_is_worse_unmeasurable_disables_gate():
    """Sentinel rc=-1 on either side -> never revert (can't measure)."""
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    assert evo._is_worse((0, 0, -1), (10, 5, 1)) is False
    assert evo._is_worse((10, 0, 0), (0, 0, -1)) is False
    print("PASS test_is_worse_unmeasurable_disables_gate")


def test_run_tier1_parses_ok_fail_ignores_stale():
    """
    _run_tier1 counts indented OK/FAIL per-check lines and IGNORES STALE freshness
    lines. Run against a fake grader that emits a captured real-output sample, so we
    exercise the actual parser (not a re-implementation).
    """
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    with tempfile.TemporaryDirectory() as d:
        grader = Path(d) / "fake-tier1.sh"
        # Emit the sample verbatim, then exit 1 (TIER-1: FAIL present in sample).
        sample_file = Path(d) / "sample.txt"
        sample_file.write_text(TIER1_SAMPLE)
        grader.write_text(f'#!/bin/bash\ncat {sample_file}\nexit 1\n')
        grader.chmod(0o755)
        evo.TIER1_GRADER = grader

        ok, fail, rc = evo._run_tier1()
        # Sample has 5 "OK " lines, 3 "FAIL " lines, 1 "STALE" line (ignored).
        assert ok == 5, f"expected 5 OK, got {ok}"
        assert fail == 3, f"expected 3 FAIL, got {fail}"
        assert rc == 1, f"expected rc 1, got {rc}"
    print("PASS test_run_tier1_parses_ok_fail_ignores_stale")


def test_run_tier1_missing_grader_returns_sentinel():
    """Missing grader -> (0,0,-1) sentinel so the gate never reverts on no measurement."""
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    evo.TIER1_GRADER = Path("/nonexistent/run-tier1.sh")
    assert evo._run_tier1() == (0, 0, -1)
    print("PASS test_run_tier1_missing_grader_returns_sentinel")


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def test_recovery_patch_captures_dirty_work_before_revert():
    """
    The capture-then-revert behavior (P1-1): in a temp git repo with a committed
    baseline and an UNRELATED dirty edit under a gated path, _capture_recovery_patch
    must record that edit BEFORE _revert_gated_paths discards it — so the work is
    recoverable via `git apply`, and _paths_already_dirty reports the dirtiness.
    """
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        _git(["init"], repo)
        _git(["config", "user.email", "t@t.test"], repo)
        _git(["config", "user.name", "t"], repo)

        # Committed baseline under a gated path (.claude/rules).
        rules = repo / ".claude" / "rules"
        rules.mkdir(parents=True)
        target = rules / "people.md"
        target.write_text("ORIGINAL committed content\n")
        _git(["add", "-A"], repo)
        _git(["commit", "-m", "baseline"], repo)

        # Simulate a PRE-EXISTING uncommitted WIP edit (another hook's, not the agent's).
        wip_text = "ORIGINAL committed content\nUNRELATED WIP EDIT — must be recoverable\n"
        target.write_text(wip_text)

        # Point the module at this temp repo and isolate the recovery dir.
        evo.VARYS_DIR = repo
        recovery = repo / "_recovery"
        evo.RECOVERY_DIR = recovery

        assert evo._paths_already_dirty() is True, "should detect the dirty gated path"

        patch_path = evo._capture_recovery_patch()
        assert patch_path, "a recovery patch must be produced for dirty paths"
        patch_file = Path(patch_path)
        assert patch_file.exists(), "recovery patch file must exist on disk"
        patch_body = patch_file.read_text()
        assert "UNRELATED WIP EDIT" in patch_body, "patch must capture the clobbered work"

        # Now the gate reverts — clobbering the WIP edit back to HEAD.
        evo._revert_gated_paths()
        assert target.read_text() == "ORIGINAL committed content\n", "revert should restore HEAD"

        # The captured patch must restore the lost work via `git apply`.
        subprocess.run(["git", "apply", str(patch_file)], cwd=repo,
                       capture_output=True, text=True, check=True)
        assert "UNRELATED WIP EDIT" in target.read_text(), "patch must restore clobbered WIP"
    print("PASS test_recovery_patch_captures_dirty_work_before_revert")


def test_recovery_patch_empty_when_clean():
    """No dirty gated paths -> no patch, and _paths_already_dirty is False."""
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        _git(["init"], repo)
        _git(["config", "user.email", "t@t.test"], repo)
        _git(["config", "user.name", "t"], repo)
        rules = repo / ".claude" / "rules"
        rules.mkdir(parents=True)
        (rules / "people.md").write_text("clean\n")
        _git(["add", "-A"], repo)
        _git(["commit", "-m", "baseline"], repo)

        evo.VARYS_DIR = repo
        evo.RECOVERY_DIR = repo / "_recovery"
        assert evo._paths_already_dirty() is False
        assert evo._capture_recovery_patch() == ""
    print("PASS test_recovery_patch_empty_when_clean")


def test_clean_note_strips_newlines_and_caps_length():
    """P2: judge notes must never break a JSON line — newlines collapsed, length capped."""
    import varys_eval
    noisy = 'line one\nline "two"\twith\ttabs\n' + ("x" * 200)
    cleaned = varys_eval._clean_note(noisy)
    assert "\n" not in cleaned and "\t" not in cleaned, "no newlines/tabs allowed"
    assert len(cleaned) <= 120, f"note must be capped at 120, got {len(cleaned)}"
    # And the resulting failure entry is still a single valid JSON line.
    line = json.dumps({"note": cleaned})
    assert "\n" not in line
    json.loads(line)
    print("PASS test_clean_note_strips_newlines_and_caps_length")


def test_mint_failures_note_is_newline_safe():
    """P2: minted entry stays a single valid JSON line even with a noisy note."""
    import varys_eval
    with tempfile.TemporaryDirectory() as d:
        fpath = Path(d) / "failures.jsonl"
        varys_eval.FAILURES_FILE = fpath
        rows = [{"page_id": "c1",
                 "failure_type": "wrong-intent",
                 "note": "did the opposite\nof what was asked"}]
        n = varys_eval._mint_failures(rows)
        assert n == 1
        raw = fpath.read_text()
        lines = [l for l in raw.splitlines() if l.strip()]
        assert len(lines) == 1, "must be exactly one JSON line"
        entry = json.loads(lines[0])  # proves the line is valid single-line JSON
        assert entry["page_id"] == "c1"
        assert entry["root_cause"] == "wrong-intent"
        assert "\n" not in entry["lesson"], "note/lesson must be single-line"
    print("PASS test_mint_failures_note_is_newline_safe")


# ---------------------------------------------------------------------------
# Score->Pass mapping, query/props builders, judged-row parsing — all PURE,
# no network. These cover the new direct-Notion-HTTP eval layer.
# ---------------------------------------------------------------------------


def test_score_to_pass_threshold():
    """>=70 -> pass; <70 -> fail; None/garbage -> fail (never crash)."""
    import varys_eval
    assert varys_eval._score_to_pass(70) is True
    assert varys_eval._score_to_pass(100) is True
    assert varys_eval._score_to_pass(69) is False
    assert varys_eval._score_to_pass(0) is False
    assert varys_eval._score_to_pass(None) is False
    assert varys_eval._score_to_pass("not-a-number") is False
    print("PASS test_score_to_pass_threshold")


def test_fail_score_mints_a_failure_but_pass_does_not():
    """A <70 row mints a failure (Pass false); a >=70 row never does."""
    import varys_eval
    with tempfile.TemporaryDirectory() as d:
        fpath = Path(d) / "failures.jsonl"
        varys_eval.FAILURES_FILE = fpath
        # Only failing (Pass=false) rows are ever passed to _mint_failures by the
        # judge, so simulate exactly that contract: a failing row mints one entry.
        failing = [{"page_id": "p_fail", "failure_type": "wrong-intent", "note": "n"}]
        assert varys_eval._mint_failures(failing) == 1
        # A passing row would simply never reach _mint_failures -> empty batch -> 0.
        assert varys_eval._mint_failures([]) == 0
    print("PASS test_fail_score_mints_a_failure_but_pass_does_not")


def test_build_unjudged_query_filters_empty_score():
    """Unjudged = Score is_empty; with a date it ANDs Date==date."""
    import varys_eval
    no_date = varys_eval._build_unjudged_query()
    assert no_date["filter"] == {"property": "Score", "number": {"is_empty": True}}
    assert no_date["page_size"] == 100

    dated = varys_eval._build_unjudged_query("2026-06-19")
    conds = dated["filter"]["and"]
    assert {"property": "Score", "number": {"is_empty": True}} in conds
    assert {"property": "Date", "date": {"equals": "2026-06-19"}} in conds
    print("PASS test_build_unjudged_query_filters_empty_score")


def test_build_scored_and_low_queries():
    """confidence query = Score is_not_empty; low query = Pass==false AND scored."""
    import varys_eval
    scored = varys_eval._build_scored_query()
    assert scored["filter"] == {"property": "Score", "number": {"is_not_empty": True}}

    low = varys_eval._build_low_query("2026-06-19")
    conds = low["filter"]["and"]
    assert {"property": "Pass", "checkbox": {"equals": False}} in conds
    assert {"property": "Score", "number": {"is_not_empty": True}} in conds
    assert {"property": "Date", "date": {"equals": "2026-06-19"}} in conds
    print("PASS test_build_scored_and_low_queries")


def test_row_to_props_maps_real_schema_only():
    """New rows map to Name/Task/Agent/Notes/Date and leave Score+Pass UNSET."""
    import varys_eval
    props = varys_eval._row_to_props(
        "Mahnoor", "fix the login bug", "Here is the fix.",
        "slack", "dm", "2026-06-19")
    assert set(props) == {"Name", "Task", "Agent", "Notes", "Date"}, \
        f"only the real schema fields may be written, got {set(props)}"
    assert "Score" not in props and "Pass" not in props, "unjudged rows leave Score/Pass unset"
    assert props["Name"]["title"][0]["text"]["content"] == "Mahnoor: fix the login bug"
    assert props["Task"]["rich_text"][0]["text"]["content"] == "fix the login bug"
    assert props["Agent"]["rich_text"][0]["text"]["content"] == "slack/dm"
    assert props["Date"]["date"]["start"] == "2026-06-19"
    print("PASS test_row_to_props_maps_real_schema_only")


def test_build_patch_props_sets_score_pass_and_appends_note():
    """PATCH sets Score+Pass and appends 'judge: <note>' to existing Notes."""
    import varys_eval
    # Failing score -> Pass false, note appended to the prior reply.
    p = varys_eval._build_patch_props(40, "asked a question a tool answers", "the reply")
    assert p["Score"] == {"number": 40}
    assert p["Pass"] == {"checkbox": False}
    appended = p["Notes"]["rich_text"][0]["text"]["content"]
    assert appended == "the reply | judge: asked a question a tool answers"

    # Passing score -> Pass true; empty note -> Notes untouched (no key).
    p2 = varys_eval._build_patch_props(85, "", "the reply")
    assert p2["Pass"] == {"checkbox": True}
    assert "Notes" not in p2, "empty judge note must not rewrite Notes"
    print("PASS test_build_patch_props_sets_score_pass_and_appends_note")


def test_props_to_row_reads_score_and_pass():
    """_props_to_row pulls text/number/checkbox from a Notion page object."""
    import varys_eval
    page = {
        "id": "page-xyz",
        "properties": {
            "Name":  {"type": "title", "title": [{"plain_text": "Sho: do X"}]},
            "Task":  {"type": "rich_text", "rich_text": [{"plain_text": "do X"}]},
            "Agent": {"type": "rich_text", "rich_text": [{"plain_text": "slack/dm"}]},
            "Notes": {"type": "rich_text", "rich_text": [{"plain_text": "did X"}]},
            "Score": {"type": "number", "number": 90},
            "Pass":  {"type": "checkbox", "checkbox": True},
        },
    }
    row = varys_eval._props_to_row(page)
    assert row["page_id"] == "page-xyz"
    assert row["name"] == "Sho: do X"
    assert row["task"] == "do X"
    assert row["agent"] == "slack/dm"
    assert row["notes"] == "did X"
    assert row["score"] == 90
    assert row["pass"] is True

    # An unjudged row: Score number is None -> treated as unscored.
    page["properties"]["Score"] = {"type": "number", "number": None}
    row2 = varys_eval._props_to_row(page)
    assert row2["score"] is None, "empty Score must read as None (unjudged)"
    print("PASS test_props_to_row_reads_score_and_pass")


# ---------------------------------------------------------------------------
# Semantic gate (bead varys-hnz.6): the LLM judge over the agent's diff + the
# pure combine logic. NO live claude -p calls — only the PURE parse/combine/no-op
# functions are exercised (the judge subprocess is the one unverified piece).
# ---------------------------------------------------------------------------


def test_semantic_parse_keep_verdict():
    """Clean {"verdict":"keep"} -> keep, risk normalised."""
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    v, reason, risk = evo._parse_semantic_verdict(
        '{"verdict":"keep","reason":"purely additive clarification","risk":"none"}')
    assert v == "keep", f"expected keep, got {v}"
    assert risk == "none"
    assert "additive" in reason
    print("PASS test_semantic_parse_keep_verdict")


def test_semantic_parse_revert_verdict():
    """Clean {"verdict":"revert"} -> revert with its reason/risk preserved."""
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    v, reason, risk = evo._parse_semantic_verdict(
        '{"verdict":"revert","reason":"removed never-commit guardrail","risk":"high"}')
    assert v == "revert", f"expected revert, got {v}"
    assert risk == "high"
    assert "never-commit" in reason
    print("PASS test_semantic_parse_revert_verdict")


def test_semantic_parse_embedded_in_prose():
    """Judge wrapping the JSON in prose -> last JSON object is still parsed."""
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    raw = ('Here is my assessment of the diff.\n'
           '{"verdict":"keep","reason":"strengthens approval gate","risk":"low"}')
    v, _reason, risk = evo._parse_semantic_verdict(raw)
    assert v == "keep" and risk == "low"
    print("PASS test_semantic_parse_embedded_in_prose")


def test_semantic_parse_malformed_fails_safe_to_revert():
    """Malformed / empty / non-object / missing-verdict -> FAIL-SAFE revert."""
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    for raw in ["", "   ", "not json at all", "{ broken json",
                '{"reason":"no verdict key","risk":"low"}',           # missing verdict
                '{"verdict":"maybe","reason":"r","risk":"low"}',       # invalid verdict
                '["verdict","keep"]',                                   # not an object
                '{"verdict":"keep"'                                     # unterminated
                ]:
        v, _reason, risk = evo._parse_semantic_verdict(raw)
        assert v == "revert", f"malformed {raw!r} must fail safe to revert, got {v}"
        assert risk == "high", f"malformed {raw!r} must be high risk, got {risk}"
    print("PASS test_semantic_parse_malformed_fails_safe_to_revert")


def test_semantic_gate_empty_diff_is_noop():
    """
    Empty diff -> gate no-op: keep verdict, gate='semantic-noop', and (critically)
    the judge subprocess is NEVER spawned. We monkeypatch _run_semantic_judge to
    blow up so the test fails loudly if it were called.
    """
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")

    def _boom(*a, **kw):
        raise AssertionError("judge must NOT be spawned on an empty diff")
    evo._run_semantic_judge = _boom

    for empty in ["", "   ", "\n\n"]:
        res = evo._semantic_gate(empty)
        assert res["verdict"] == "keep", f"empty diff must keep, got {res}"
        assert res["gate"] == "semantic-noop", f"expected semantic-noop, got {res['gate']}"
    print("PASS test_semantic_gate_empty_diff_is_noop")


def test_semantic_gate_judge_error_fails_safe():
    """Judge returns nothing / errors -> revert tagged 'semantic-error' (distinct)."""
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    diff = "diff --git a/.claude/rules/x.md b/.claude/rules/x.md\n-never commit\n"

    evo._run_semantic_judge = lambda *a, **kw: ""        # empty output
    res = evo._semantic_gate(diff)
    assert res["verdict"] == "revert", "empty judge output must fail safe to revert"
    assert res["gate"] == "semantic-error", f"expected semantic-error, got {res['gate']}"

    def _raise(*a, **kw):
        raise RuntimeError("subprocess blew up")
    evo._run_semantic_judge = _raise                      # judge itself raises
    res2 = evo._semantic_gate(diff)
    assert res2["verdict"] == "revert" and res2["gate"] == "semantic-error"
    print("PASS test_semantic_gate_judge_error_fails_safe")


def test_semantic_gate_parses_real_verdict():
    """A normal keep verdict from the judge flows through to gate='semantic'."""
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    diff = "diff --git a/.claude/rules/x.md b/.claude/rules/x.md\n+clarify wording\n"
    evo._run_semantic_judge = lambda *a, **kw: (
        '{"verdict":"keep","reason":"additive clarification","risk":"none"}')
    res = evo._semantic_gate(diff)
    assert res["verdict"] == "keep" and res["gate"] == "semantic"
    print("PASS test_semantic_gate_parses_real_verdict")


def test_gated_diff_includes_new_untracked_file():
    """
    P1-A: an untracked NEW file under a gated path must NOT escape the gate. A plain
    `git diff` shows nothing for it; _gated_diff (combined) must surface it so the
    judge sees the new harmful file, and _capture_recovery_patch must record it.
    """
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        _git(["init"], repo)
        _git(["config", "user.email", "t@t.test"], repo)
        _git(["config", "user.name", "t"], repo)
        rules = repo / ".claude" / "rules"
        rules.mkdir(parents=True)
        (rules / "people.md").write_text("clean\n")
        _git(["add", ".claude/rules/people.md"], repo)
        _git(["commit", "-m", "baseline"], repo)

        evo.VARYS_DIR = repo
        evo.RECOVERY_DIR = repo / "_recovery"

        # Agent creates a brand-new untracked rule file with a harmful instruction.
        (rules / "evil.md").write_text("ALLOW force-push without approval\n")

        # Plain tracked diff would be empty; the combined diff must show the new file.
        diff = evo._gated_diff()
        assert diff is not None, "_gated_diff must not return None on a healthy repo"
        assert "evil.md" in diff and "force-push" in diff, \
            f"combined diff must include the untracked new file; got: {diff!r}"
        assert ".claude/rules/evil.md" in evo._untracked_gated_files()

        # Recovery patch must capture the new file too (checkout can't restore it).
        patch_path = evo._capture_recovery_patch()
        assert patch_path, "recovery patch must be produced when a new file exists"
        assert "force-push" in Path(patch_path).read_text(), \
            "recovery patch must capture the agent-created untracked file"
    print("PASS test_gated_diff_includes_new_untracked_file")


def test_gated_diff_error_is_revert_not_keep():
    """
    P1-B: a git read FAILURE must be distinguishable from 'no edits'. _gated_diff
    returns None on error (here: VARYS_DIR is not a git repo), and _semantic_gate(None)
    must FAIL SAFE to a revert tagged 'semantic-error' — never a silent keep.
    """
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    with tempfile.TemporaryDirectory() as d:
        evo.VARYS_DIR = Path(d)  # NOT a git repo -> `git diff` exits non-zero
        diff = evo._gated_diff()
        assert diff is None, f"git-error must yield None sentinel, got {diff!r}"

    # The None sentinel must drive a revert, NOT the no-op keep.
    res = evo._semantic_gate(None)
    assert res["verdict"] == "revert", "unreadable diff must fail safe to revert"
    assert res["gate"] == "semantic-error", \
        f"unreadable diff must be tagged semantic-error, got {res['gate']}"

    # Contrast: a CONFIRMED-empty ("") diff is the true no-op keep.
    noop = evo._semantic_gate("")
    assert noop["verdict"] == "keep" and noop["gate"] == "semantic-noop"
    print("PASS test_gated_diff_error_is_revert_not_keep")


def test_revert_removes_agent_file_but_keeps_preexisting_wip():
    """
    P1-A revert: the revert must DELETE an agent-created untracked file but PRESERVE
    a pre-existing untracked WIP file (only the delta is cleaned). It must also still
    revert tracked edits via `git checkout`.
    """
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        _git(["init"], repo)
        _git(["config", "user.email", "t@t.test"], repo)
        _git(["config", "user.name", "t"], repo)
        rules = repo / ".claude" / "rules"
        rules.mkdir(parents=True)
        tracked = rules / "people.md"
        tracked.write_text("ORIGINAL\n")
        _git(["add", ".claude/rules/people.md"], repo)
        _git(["commit", "-m", "baseline"], repo)
        evo.VARYS_DIR = repo

        # Pre-existing untracked WIP (another hook's work, present BEFORE the agent).
        preexisting = rules / "wip.md"
        preexisting.write_text("PRE-EXISTING WIP — must survive\n")
        pre_untracked = set(evo._untracked_gated_files())
        assert ".claude/rules/wip.md" in pre_untracked

        # Now the agent runs: a tracked edit + a NEW untracked file.
        tracked.write_text("ORIGINAL\nAGENT TRACKED EDIT\n")
        agent_file = rules / "agent_new.md"
        agent_file.write_text("AGENT CREATED — must be deleted on revert\n")

        # The delta the revert is allowed to clean: only files the agent added.
        agent_created = sorted(set(evo._untracked_gated_files()) - pre_untracked)
        assert agent_created == [".claude/rules/agent_new.md"], \
            f"delta must be exactly the agent-created file, got {agent_created}"

        evo._revert_gated_paths(agent_created)

        assert tracked.read_text() == "ORIGINAL\n", "tracked edit must be reverted to HEAD"
        assert not agent_file.exists(), "agent-created untracked file must be cleaned"
        assert preexisting.exists(), "pre-existing untracked WIP must be PRESERVED"
        assert preexisting.read_text() == "PRE-EXISTING WIP — must survive\n"
    print("PASS test_revert_removes_agent_file_but_keeps_preexisting_wip")


def test_combine_gate_decision_truth_table():
    """The full struct_worse x semantic-verdict truth table, exactly as documented."""
    evo = _load("evo_agent", HOOKS / "varys-evolution-agent.py")
    # (struct_worse, sem_verdict) -> (should_revert, gate_label)
    cases = [
        ((False, "keep"),   (False, "none")),       # struct-ok + sem-keep   -> KEEP
        ((False, "revert"), (True,  "semantic")),   # struct-ok + sem-revert -> revert (semantic)
        ((True,  "keep"),   (True,  "structural")), # struct-worse + sem-keep -> revert (structural)
        ((True,  "revert"), (True,  "both")),       # both -> revert (both)
    ]
    for (sw, sv), expected in cases:
        got = evo._combine_gate_decision(sw, sv)
        assert got == expected, f"combine({sw},{sv!r}) expected {expected}, got {got}"
    print("PASS test_combine_gate_decision_truth_table")


if __name__ == "__main__":
    test_mint_failures_dedupes_by_page_id()
    test_mint_failures_dedupes_within_batch()
    test_mint_failures_skips_blank_page_id()
    test_is_worse_more_fails_triggers_revert()
    test_is_worse_exit_code_regression_triggers_revert()
    test_is_worse_no_regression_keeps_edits()
    test_is_worse_unmeasurable_disables_gate()
    test_run_tier1_parses_ok_fail_ignores_stale()
    test_run_tier1_missing_grader_returns_sentinel()
    test_recovery_patch_captures_dirty_work_before_revert()
    test_recovery_patch_empty_when_clean()
    test_clean_note_strips_newlines_and_caps_length()
    test_mint_failures_note_is_newline_safe()
    test_score_to_pass_threshold()
    test_fail_score_mints_a_failure_but_pass_does_not()
    test_build_unjudged_query_filters_empty_score()
    test_build_scored_and_low_queries()
    test_row_to_props_maps_real_schema_only()
    test_build_patch_props_sets_score_pass_and_appends_note()
    test_props_to_row_reads_score_and_pass()
    test_semantic_parse_keep_verdict()
    test_semantic_parse_revert_verdict()
    test_semantic_parse_embedded_in_prose()
    test_semantic_parse_malformed_fails_safe_to_revert()
    test_semantic_gate_empty_diff_is_noop()
    test_semantic_gate_judge_error_fails_safe()
    test_semantic_gate_parses_real_verdict()
    test_gated_diff_includes_new_untracked_file()
    test_gated_diff_error_is_revert_not_keep()
    test_revert_removes_agent_file_but_keeps_preexisting_wip()
    test_combine_gate_decision_truth_table()
    print("\nALL TESTS PASSED")
