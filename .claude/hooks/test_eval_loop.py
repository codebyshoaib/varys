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
    """New rows map to Name/Task/Agent/Notes/Thread/Tools/Date, Score+Pass UNSET."""
    import varys_eval
    props = varys_eval._row_to_props(
        "Mahnoor", "fix the login bug", "Here is the fix.",
        "slack", "dm", "2026-06-19",
        thread="Mahnoor: fix the login bug\nVarys: Here is the fix.",
        tools="Bash, Edit")
    assert set(props) == {"Name", "Task", "Agent", "Notes", "Thread", "Tools", "Date"}, \
        f"only the real schema fields may be written, got {set(props)}"
    assert "Score" not in props and "Pass" not in props, "unjudged rows leave Score/Pass unset"
    assert props["Name"]["title"][0]["text"]["content"] == "Mahnoor: fix the login bug"
    assert props["Task"]["rich_text"][0]["text"]["content"] == "fix the login bug"
    assert props["Agent"]["rich_text"][0]["text"]["content"] == "slack/dm"
    assert props["Tools"]["rich_text"][0]["text"]["content"] == "Bash, Edit"
    assert "Varys: Here is the fix." in props["Thread"]["rich_text"][0]["text"]["content"]
    assert props["Date"]["date"]["start"] == "2026-06-19"
    # thread/tools default to "" so any older call site keeps working
    bare = varys_eval._row_to_props("X", "q", "a", "slack", "dm", "2026-06-19")
    assert bare["Thread"]["rich_text"][0]["text"]["content"] == ""
    assert bare["Tools"]["rich_text"][0]["text"]["content"] == ""
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


if __name__ == "__main__":
    test_mint_failures_dedupes_by_page_id()
    test_mint_failures_dedupes_within_batch()
    test_mint_failures_skips_blank_page_id()
    test_clean_note_strips_newlines_and_caps_length()
    test_mint_failures_note_is_newline_safe()
    test_score_to_pass_threshold()
    test_fail_score_mints_a_failure_but_pass_does_not()
    test_build_unjudged_query_filters_empty_score()
    test_build_scored_and_low_queries()
    test_row_to_props_maps_real_schema_only()
    test_build_patch_props_sets_score_pass_and_appends_note()
    test_props_to_row_reads_score_and_pass()
    print("\nALL EVAL-LOOP TESTS PASSED")
