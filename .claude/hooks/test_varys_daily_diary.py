#!/usr/bin/env python3
"""Tests for varys-daily-diary.py — day-filtering and diary/JSON split."""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

HOOKS = Path(__file__).parent
spec = importlib.util.spec_from_file_location("varys_daily_diary", HOOKS / "varys-daily-diary.py")
diary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diary)


def test_jsonl_for_day_filters_by_date_prefix():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "l.jsonl"
        p.write_text(
            json.dumps({"ts": "2026-06-25T10:00:00Z", "title": "keep", "takeaway": "a"}) + "\n" +
            json.dumps({"ts": "2026-06-24T10:00:00Z", "title": "drop", "takeaway": "b"}) + "\n" +
            json.dumps({"date": "2026-06-25", "title": "keep2", "takeaway": "c"}) + "\n"
        )
        rows = diary._jsonl_for_day(p, "2026-06-25", ("title", "takeaway"))
        titles = {r["title"] for r in rows}
        assert titles == {"keep", "keep2"}, titles


def test_jsonl_for_day_tolerates_malformed_lines():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "l.jsonl"
        p.write_text("not json\n" + json.dumps({"ts": "2026-06-25T01:00:00Z", "title": "ok"}) + "\n\n")
        rows = diary._jsonl_for_day(p, "2026-06-25", ("title",))
        assert len(rows) == 1 and rows[0]["title"] == "ok"


def test_jsonl_for_day_missing_file_returns_empty():
    assert diary._jsonl_for_day(Path("/nonexistent/x.jsonl"), "2026-06-25", ("title",)) == []


def test_parse_json_splits_diary_from_meta():
    out = ("My day was long.\nI shipped two things.\n"
           "{\"headline\": \"A long day\", \"shareable\": true, \"one_liner\": \"shipped two things\"}")
    text, meta = diary._parse_json(out)
    assert meta["shareable"] is True
    assert meta["headline"] == "A long day"
    assert "shipped two things" in text
    assert "headline" not in text   # JSON line must be stripped from the diary body


def test_parse_json_no_trailing_json_returns_all_text():
    text, meta = diary._parse_json("just a diary, no json line")
    assert meta == {} and text == "just a diary, no json line"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                print(f"FAIL {name}: {e}")
                failures += 1
    if failures:
        print(f"\n{failures} FAILURE(S)")
        sys.exit(1)
    print("\nALL DAILY-DIARY TESTS PASSED")
    sys.exit(0)
