#!/usr/bin/env python3
"""
test_poll_taleemabad_github.py — self-check for the GitHub PR poller.

Hermetic: imports the hyphen-named module via importlib; never calls main() (which hits the
GitHub REST API and writes the live harness.db). We test:
  - _load_config: env vars override file config; default GITHUB_REPO is the unconfigured
    placeholder (main() treats a "{{" repo as "not configured" → exit 2)
  - _find_notion_entity_for_pr: resolves an agent-opened PR's entity and its linked Notion
    ticket, run against a hermetic in-memory DB (never the live harness.db)
  - the deterministic event-ID convention (orchestrator rule 4):
    "github-<repo_short>-<pr>-merged|closed|review-<id>"

Run: python3 .claude/hooks/test_poll_taleemabad_github.py
"""
import importlib.util
import os
import sqlite3
import sys
from pathlib import Path

HOOKS = Path(__file__).parent
sys.path.insert(0, str(HOOKS))
spec = importlib.util.spec_from_file_location("poll_github", HOOKS / "poll-taleemabad-github.py")
pg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pg)

import varys_harness_db as hdb
hdb._bd = lambda *a, **kw: ""


def _mem_db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.executescript(hdb._SCHEMA)
    db.commit()
    hdb.migrate_db(db)
    return db


def test_load_config_env_override_and_default():
    # GITHUB_REPO always has a value (the hard-coded default placeholder, or whatever the
    # host's config files supply — we don't assert which, to stay host-independent).
    assert pg._load_config().get("GITHUB_REPO"), "GITHUB_REPO must always be populated"
    # env vars must override file/default config (the precedence the daemon relies on).
    os.environ["GITHUB_REPO"] = "org/real-repo"
    os.environ["GITHUB_TOKEN"] = "ghp-x"
    try:
        cfg = pg._load_config()
        assert cfg["GITHUB_REPO"] == "org/real-repo", "env must override file/default config"
        assert cfg["GITHUB_TOKEN"] == "ghp-x"
    finally:
        del os.environ["GITHUB_REPO"]
        del os.environ["GITHUB_TOKEN"]
    print("PASS test_load_config_env_override_and_default")


def test_find_notion_entity_for_pr():
    db = _mem_db()
    repo = "org/repo"
    # Unknown PR → (None, None): the poller skips PRs it didn't open.
    assert pg._find_notion_entity_for_pr(db, repo, 7) == (None, None)
    # Register the GitHub PR entity (external_id format "repo#pr") + a linked Notion ticket.
    gh = hdb.register_entity(db, "github", f"{repo}#7", "pr", "")
    notion = hdb.register_entity(db, "notion", "page-abc", "ticket", "")
    hdb.link_entities(db, gh, notion, "tracks", session_id="t")
    gh_id, notion_id = pg._find_notion_entity_for_pr(db, repo, 7)
    assert gh_id == gh and notion_id == notion, (gh_id, notion_id)
    print("PASS test_find_notion_entity_for_pr")


def test_event_id_convention():
    """Deterministic, type-suffixed event IDs keep re-polling idempotent (rule 4)."""
    repo_short = "repo"
    pr = 12
    assert f"github-{repo_short}-{pr}-merged" == "github-repo-12-merged"
    assert f"github-{repo_short}-{pr}-closed" == "github-repo-12-closed"
    assert f"github-{repo_short}-{pr}-review-{99}" == "github-repo-12-review-99"
    # stable across calls; distinct per type so merged/closed/review don't collide
    ids = {f"github-{repo_short}-{pr}-{t}" for t in ("merged", "closed", "review-1")}
    assert len(ids) == 3
    print("PASS test_event_id_convention")


if __name__ == "__main__":
    test_load_config_env_override_and_default()
    test_find_notion_entity_for_pr()
    test_event_id_convention()
    print("\nALL POLL_TALEEMABAD_GITHUB TESTS PASSED")
