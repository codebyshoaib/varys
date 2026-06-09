#!/usr/bin/env python3
"""
poll-taleemabad-github.py — Poll taleemabad-core GitHub PRs on agent branches.

Called once per /loop tick AFTER tick lock is acquired.
IMPORTANT: Only processes PRs that already have an entity in harness.db.
           The agent creates the entity when it opens a PR in Step B.
           This script does NOT process all PRs — only agent-opened ones.

Event types produced:
  pr.review_commented — review comment on an agent-opened PR
  pr.merged           — agent PR merged → will set Notion Status=Done
  pr.closed           — agent PR closed (not merged) → Status=Blocked

Design rules:
  - Deterministic event IDs: "github-taleemabad-core-<pr_num>-<type>"
  - INSERT OR IGNORE — re-polling is always safe
  - If this script exits non-zero: tick aborts, last_sync_at NOT updated
"""

import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_harness_db import get_db, get_linked_entities
try:
    from kamil_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

HARNESS_CFG = Path.home() / ".kamil-harness" / "config.json"
SLACK_CFG   = Path.home() / ".claude" / "hooks" / ".slack"


def _load_config() -> dict:
    cfg = {"GITHUB_REPO": "{{YOUR_GITHUB_ORG}}/{{YOUR_REPO}}"}
    if HARNESS_CFG.exists():
        cfg.update(json.loads(HARNESS_CFG.read_text()))
    if SLACK_CFG.exists():
        for line in SLACK_CFG.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    for key in ("GITHUB_TOKEN", "GITHUB_REPO", "GITHUB_AGENT_LOGIN"):
        if os.environ.get(key):
            cfg[key] = os.environ[key]
    return cfg


def _gh_request(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _find_notion_entity_for_pr(db, repo: str, pr_num: int) -> tuple[str | None, str | None]:
    """Return (github_entity_id, notion_entity_id) for a PR if it's agent-opened."""
    external_id = f"{repo}#{pr_num}"
    row = db.execute(
        "SELECT id FROM entities WHERE source='github' AND external_id=?",
        (external_id,),
    ).fetchone()
    if not row:
        return None, None

    gh_entity_id = row[0]
    linked = get_linked_entities(db, gh_entity_id)
    for e in linked:
        if e["source"] == "notion" and e["type"] == "ticket":
            return gh_entity_id, e["id"]
    return gh_entity_id, None


def main() -> int:
    cfg   = _load_config()
    token = cfg.get("GITHUB_TOKEN")
    repo  = cfg.get("GITHUB_REPO", "{{YOUR_GITHUB_ORG}}/{{YOUR_REPO}}")
    agent_login = cfg.get("GITHUB_AGENT_LOGIN", "")

    if not token:
        print("[poll-github] ERROR: GITHUB_TOKEN required", file=sys.stderr)
        return 1

    db = get_db()
    last_sync_at = db.execute(
        "SELECT last_sync_at FROM sync_state WHERE id='global'"
    ).fetchone()[0]

    print(f"[poll-github] Polling {repo} PRs since {last_sync_at}")

    # Fetch recently updated PRs (both open and closed)
    try:
        prs = _gh_request(
            f"https://api.github.com/repos/{repo}/pulls"
            f"?state=all&sort=updated&direction=desc&per_page=30",
            token,
        )
    except Exception as e:
        print(f"[poll-github] ERROR fetching PRs: {e}", file=sys.stderr)
        klog_error("poll-github-fetch", e, component="orchestrator")
        return 1

    new_events = 0
    for pr in prs:
        pr_num     = pr["number"]
        updated_at = pr.get("updated_at", "")
        pr_url     = pr.get("html_url", "")
        state      = pr.get("state", "")
        merged     = pr.get("merged_at") is not None
        pr_login   = pr.get("user", {}).get("login", "")

        # Only process PRs updated since last_sync_at
        if updated_at <= last_sync_at:
            continue

        # Only process agent-opened PRs (entity must exist in harness.db)
        gh_entity_id, notion_entity_id = _find_notion_entity_for_pr(db, repo, pr_num)
        if not gh_entity_id:
            # Not an agent PR — skip silently
            continue

        repo_short = repo.split("/")[-1]

        # PR merged
        if merged and state == "closed":
            event_id = f"github-{repo_short}-{pr_num}-merged"
            payload  = json.dumps({"pr_number": pr_num, "url": pr_url, "state": "merged"})
            db.execute(
                "INSERT OR IGNORE INTO events "
                "(id, source, type, context_key, payload, status, received_at) "
                "VALUES (?, 'github', 'pr.merged', ?, ?, 'pending', datetime('now'))",
                (event_id, notion_entity_id or gh_entity_id, payload),
            )
            if db.execute("SELECT changes()").fetchone()[0] > 0:
                new_events += 1
                print(f"[poll-github] pr.merged: #{pr_num}")

        # PR closed (not merged)
        elif not merged and state == "closed":
            event_id = f"github-{repo_short}-{pr_num}-closed"
            payload  = json.dumps({"pr_number": pr_num, "url": pr_url, "state": "closed"})
            db.execute(
                "INSERT OR IGNORE INTO events "
                "(id, source, type, context_key, payload, status, received_at) "
                "VALUES (?, 'github', 'pr.closed', ?, ?, 'pending', datetime('now'))",
                (event_id, notion_entity_id or gh_entity_id, payload),
            )
            if db.execute("SELECT changes()").fetchone()[0] > 0:
                new_events += 1
                print(f"[poll-github] pr.closed: #{pr_num}")

        # Check review comments on open PRs
        elif state == "open":
            try:
                comments = _gh_request(
                    f"https://api.github.com/repos/{repo}/pulls/{pr_num}/reviews",
                    token,
                )
            except Exception:
                comments = []

            for review in comments:
                submitted_at = review.get("submitted_at", "")
                if submitted_at <= last_sync_at:
                    continue
                reviewer = review.get("user", {}).get("login", "")
                if reviewer == agent_login:
                    continue  # skip agent's own reviews
                review_id = review.get("id", "")
                event_id  = f"github-{repo_short}-{pr_num}-review-{review_id}"
                payload   = json.dumps({
                    "pr_number": pr_num, "url": pr_url,
                    "review_id": review_id, "reviewer": reviewer,
                    "state": review.get("state", ""),
                    "body": review.get("body", "")[:500],
                })
                db.execute(
                    "INSERT OR IGNORE INTO events "
                    "(id, source, type, context_key, payload, status, received_at) "
                    "VALUES (?, 'github', 'pr.review_commented', ?, ?, 'pending', datetime('now'))",
                    (event_id, notion_entity_id or gh_entity_id, payload),
                )
                if db.execute("SELECT changes()").fetchone()[0] > 0:
                    new_events += 1
                    print(f"[poll-github] pr.review_commented: #{pr_num} by {reviewer}")

        db.commit()

    print(f"[poll-github] Done. {new_events} new events.")
    klog("poll-github", component="orchestrator", action="poll", new_events=new_events)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
