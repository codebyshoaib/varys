#!/usr/bin/env python3
"""
test_varys_slack_reflect.py — Self-check for varys-slack-reflect.py's pure logic.

Hermetic: NO claude -p, NO network, NO live intel-context read (uses fixtures).
Exercises the isolatable pure functions: the JSONL entry builder/schema, the
"already known" dedup of recent lessons, intel-context parsing (fixture dict),
and the "no signal -> write nothing" path.

No framework, asserts only. exit(1) on any failure.
Run: python3 .claude/hooks/test_varys_slack_reflect.py
"""
import importlib.util
import json
import sys
from pathlib import Path

HOOKS = Path(__file__).parent
sys.path.insert(0, str(HOOKS))

spec = importlib.util.spec_from_file_location(
    "varys_slack_reflect", HOOKS / "varys-slack-reflect.py")
sr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sr)


# --- fixtures ---------------------------------------------------------------

INTEL_FIXTURE = [
    {"run": "Fri 19 Jun, 18:00", "channels": {}},  # empty run — must be skipped
    {
        "run": "Fri 19 Jun, 18:08",
        "channels": {
            "#region-punjab": {
                "summary": "PR review request and a baseline report landed.",
                "mood": "productive",
                "people": [
                    {"name": "Iqra Zanib", "working_on": "ComplianceTracker PR #407",
                     "blocked_on": None, "shipped": None},
                    {"name": "Mahrah", "working_on": None, "blocked_on": None,
                     "shipped": "Baseline Observation Analysis"},
                ],
                "key_links": ["https://example/407"],
            },
            "#regionpunjab-internal": {
                "summary": "Muavia asking for guidance on permissions.",
                "mood": "productive",
                "people": [
                    {"name": "Muavia Qureshi", "working_on": None,
                     "blocked_on": "cannot see permissions option", "shipped": None},
                ],
                "key_links": [],
            },
        },
    },
    {
        "run": "Fri 19 Jun, 18:30",
        "channels": {
            # SAME channel + SAME summary as the prior run -> must be deduped.
            "#region-punjab": {
                "summary": "PR review request and a baseline report landed.",
                "mood": "calm",
                "people": [],
            },
        },
    },
]


# --- build_entry / schema ---------------------------------------------------

def test_build_entry_schema():
    """Entry has exactly the fields synthesize's slack tier renders (type/ts/source/who/insight)."""
    e = sr.build_entry("Kamil", "Ping him the PR link directly.", ts="2026-06-24T21:30:00Z")
    assert e == {
        "type": "social",
        "ts": "2026-06-24T21:30:00Z",
        "source": "slack-reflect",
        "who": "Kamil",
        "insight": "Ping him the PR link directly.",
    }, e
    # Must be valid JSON round-trippable (heredoc writes JSON lines).
    assert json.loads(json.dumps(e)) == e


def test_build_entry_empty_who_and_autots():
    """who may be empty (team-level lesson); ts auto-fills as ISO8601 Z."""
    e = sr.build_entry("", "Team prefers async PR review over channel pings.")
    assert e["who"] == ""
    assert e["type"] == "social" and e["source"] == "slack-reflect"
    assert e["ts"].endswith("Z") and "T" in e["ts"], e["ts"]


# --- recent_lessons dedup/context -------------------------------------------

def test_recent_lessons_renders_who_and_insight():
    archive = "\n".join([
        json.dumps(sr.build_entry("Iqra", "Owns ComplianceTracker reviews.")),
        json.dumps(sr.build_entry("", "Team ships offline-sync PRs in batches.")),
    ])
    out = sr.recent_lessons(archive)
    assert "- Iqra: Owns ComplianceTracker reviews." in out, out
    assert "- Team ships offline-sync PRs in batches." in out, out  # no "who:" prefix when empty


def test_recent_lessons_tolerates_blank_and_malformed():
    archive = "\n".join([
        "",
        "not json at all",
        json.dumps({"type": "social", "who": "X"}),     # no insight -> skipped
        json.dumps(sr.build_entry("Mahrah", "Shipped the baseline analysis.")),
        "   ",
    ])
    out = sr.recent_lessons(archive)
    assert out == "- Mahrah: Shipped the baseline analysis.", repr(out)


def test_recent_lessons_caps_to_limit_newest_last():
    archive = "\n".join(
        json.dumps(sr.build_entry(f"P{i}", f"insight {i}")) for i in range(10))
    out = sr.recent_lessons(archive, limit=3)
    lines = out.splitlines()
    assert len(lines) == 3, lines
    assert lines[-1] == "- P9: insight 9", lines  # newest last


# --- parse_intel_context ----------------------------------------------------

def test_parse_intel_flattens_people_and_facts():
    out = sr.parse_intel_context(INTEL_FIXTURE)
    assert "#region-punjab" in out
    assert "Iqra Zanib (working on ComplianceTracker PR #407)" in out, out
    assert "Mahrah (shipped Baseline Observation Analysis)" in out, out
    assert "Muavia Qureshi (blocked on cannot see permissions option)" in out, out
    assert "[mood: productive]" in out


def test_parse_intel_dedups_repeated_summary():
    """Same channel+summary across runs appears once, not echoed per run."""
    out = sr.parse_intel_context(INTEL_FIXTURE)
    assert out.count("PR review request and a baseline report landed.") == 1, out


def test_parse_intel_empty_yields_no_signal():
    """No usable signal -> '' so main() takes the 'write nothing' path."""
    assert sr.parse_intel_context([]) == ""
    assert sr.parse_intel_context([{"run": "x", "channels": {}}]) == ""
    assert sr.parse_intel_context("not a list") == ""
    assert sr.parse_intel_context(None) == ""


def test_parse_intel_recent_runs_window():
    """Only the last `recent_runs` runs (with channels) are considered."""
    many = [{"run": f"r{i}", "channels": {f"#c{i}": {"summary": f"s{i}", "people": []}}}
            for i in range(6)]
    out = sr.parse_intel_context(many, recent_runs=2)
    assert "#c5" in out and "#c4" in out
    assert "#c0" not in out and "#c3" not in out, out


def test_build_prompt_includes_intel_and_gates():
    """The prompt carries the intel digest and the two reflection gates."""
    intel = sr.parse_intel_context(INTEL_FIXTURE)
    p = sr.build_prompt(intel, lessons="- prior", wisdom="some wisdom")
    assert "Muavia Qureshi" in p
    assert "genuinely novel" in p and "change how I" in p          # gate 1 + gate 2
    assert "no lesson today" in p                                   # the no-op signal
    assert "memory/slack_learnings.jsonl" in p


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"\n{failed} TEST(S) FAILED")
        sys.exit(1)
    print(f"\nALL {len(tests)} SLACK-REFLECT TESTS PASSED")
