#!/usr/bin/env python3
"""
test_session_start.py — self-check for the SessionStart briefing builder.

Hermetic: imports the hyphen-named module via importlib and monkeypatches EVERY network /
DB / subprocess boundary (Notion fetchers, the brain.db read is best-effort) so no HTTP
call, no token read, and no `bd`/subprocess fan-out happens. main() is never called.

COVERAGE NOTE: this hook is mostly I/O assembly. Its one genuinely pure transform is
load_slack_inbox (filter to unsynced items, newest 20), which we test against a temp inbox
file. build_system_message is then smoke-tested: with all I/O stubbed it must still produce
the identity header + the Notion-MCP fetch instructions and never raise.

Run: python3 .claude/hooks/test_session_start.py
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

HOOKS = Path(__file__).parent
sys.path.insert(0, str(HOOKS))
spec = importlib.util.spec_from_file_location("session_start", HOOKS / "session-start.py")
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)


def test_load_slack_inbox_filters_unsynced_and_caps():
    items = [{"message": f"m{i}", "notion_synced": (i % 2 == 0)} for i in range(50)]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(items, f)
        tmp = Path(f.name)
    orig = ss.INBOX_FILE
    try:
        ss.INBOX_FILE = tmp
        out = ss.load_slack_inbox()
        # only unsynced (odd i) survive, capped at 20, newest-first slice
        assert all(not it["notion_synced"] for it in out), "synced items must be filtered out"
        assert len(out) == 20, f"must cap at 20, got {len(out)}"
        # missing file → [] (never raises)
        ss.INBOX_FILE = HOOKS / "definitely-not-a-real-file.json"
        assert ss.load_slack_inbox() == []
    finally:
        ss.INBOX_FILE = orig
        tmp.unlink(missing_ok=True)
    print("PASS test_load_slack_inbox_filters_unsynced_and_caps")


def test_build_system_message_smoke():
    """With all I/O stubbed, the briefing still builds and carries identity + MCP fetch block."""
    orig = (ss.load_slack_inbox, ss._fetch_work_log, ss._fetch_open_prs, ss._fetch_auto_tickets)
    ss.load_slack_inbox = lambda: []
    ss._fetch_work_log = lambda: []
    ss._fetch_open_prs = lambda: []
    ss._fetch_auto_tickets = lambda: []
    try:
        msg = ss.build_system_message()
        assert isinstance(msg, str) and msg
        assert "## YOU ARE" in msg, "identity header missing"
        assert "Notion MCP" in msg, "MCP fetch instructions missing"
        assert "Slack Inbox" in msg
    finally:
        (ss.load_slack_inbox, ss._fetch_work_log, ss._fetch_open_prs,
         ss._fetch_auto_tickets) = orig
    print("PASS test_build_system_message_smoke")


if __name__ == "__main__":
    test_load_slack_inbox_filters_unsynced_and_caps()
    test_build_system_message_smoke()
    print("\nALL SESSION_START TESTS PASSED")
