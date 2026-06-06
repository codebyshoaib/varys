# tests/test_self_evolution_e2e.py
"""
End-to-end smoke test for the self-evolution loop.
Uses a real (temp) brain.db but mocks Notion and Slack API calls.
"""
import importlib.util
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, ".claude/hooks")

# Load kamil-apply-learnings (hyphenated filename — can't use normal import)
_spec = importlib.util.spec_from_file_location(
    "kamil_apply_learnings",
    Path(".claude/hooks/kamil-apply-learnings.py"),
)
kal = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kal)


def _make_brain_db(path: str) -> None:
    """Create a minimal brain.db with one learning entity and facts."""
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE entities (
        id TEXT PRIMARY KEY, type TEXT, name TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    db.execute("""CREATE TABLE facts (
        id TEXT PRIMARY KEY, subject_id TEXT, predicate TEXT, object_val TEXT,
        source TEXT, session_id TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    db.execute("INSERT INTO entities VALUES ('learn-test-1', 'learning', '[tech] adversarial agents', datetime('now'))")
    db.execute("INSERT INTO facts VALUES ('f1', 'learn-test-1', 'key_insight',     'Use multiple agents to verify each other',              'test', '', datetime('now'))")
    db.execute("INSERT INTO facts VALUES ('f2', 'learn-test-1', 'lesson_learned',  'Silent failures are invisible without adversarial checks','test', '', datetime('now'))")
    db.execute("INSERT INTO facts VALUES ('f3', 'learn-test-1', 'one_line_summary','Adversarial multi-agent design catches what single agents miss', 'test', '', datetime('now'))")
    db.commit()
    db.close()


def test_full_loop_no_real_apis():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    _make_brain_db(db_path)

    fake_gaps = [
        {
            "title":        "Add adversarial checker",
            "what_to_build": "Spawn a verifier agent after each output.",
            "why":           "Silent failures are invisible without adversarial checks",
            "priority":      "P1",
            "effort":        "medium",
        },
    ]

    with patch.object(kal, "BRAIN_DB", Path(db_path)), \
         patch.object(kal, "analyse_gaps",                    return_value=fake_gaps), \
         patch.object(kal, "_fetch_existing_ticket_titles",   return_value=set()), \
         patch.object(kal, "create_harness_ticket",           return_value="fake-page-id-001"), \
         patch.object(kal, "slack_dm") as mock_slack:

        kal.run(days=1, notify_slack=True)

        mock_slack.assert_called_once()
        msg = mock_slack.call_args[0][1]
        assert "adversarial checker" in msg.lower()
        assert "silent failures" in msg.lower()

    Path(db_path).unlink(missing_ok=True)
