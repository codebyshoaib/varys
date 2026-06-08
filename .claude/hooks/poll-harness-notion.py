#!/usr/bin/env python3
"""
poll-harness-notion.py — Poll Kamil Harness Notion DB for new/updated tickets.

Called once per /loop tick AFTER tick lock is acquired.
Writes deterministic events to harness.db.

Event types produced:
  ticket.created  — new ticket assigned to Kamil (entity didn't exist before)
  comment.tagged  — comment on a Notion page containing @Kamil

Design rules:
  - Deterministic event IDs: "notion-<page_id>", "notion-comment-<comment_id>"
  - INSERT OR IGNORE — re-polling same window is always safe
  - 350ms between Notion API calls via kamil_notion.notion_request()
  - If this script exits non-zero: tick aborts, last_sync_at NOT updated
"""

import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_harness_db import get_db, register_entity
from kamil_notion import notion_request
try:
    from kamil_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

# ── Config ────────────────────────────────────────────────────────────────────
NOTION_CFG = Path.home() / ".claude" / "hooks" / ".notion"
HARNESS_CFG = Path.home() / ".kamil-harness" / "config.json"


def _load_config() -> dict:
    cfg = {}
    # From .notion file
    if NOTION_CFG.exists():
        for line in NOTION_CFG.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    # From harness config
    if HARNESS_CFG.exists():
        cfg.update(json.loads(HARNESS_CFG.read_text()))
    # Env overrides
    for key in ("NOTION_API_KEY", "NOTION_DATABASE_ID", "NOTION_AGENT_USER_ID"):
        if os.environ.get(key):
            cfg[key] = os.environ[key]
    # Fall back to agent_config for DB ID if not found in existing config files
    if not cfg.get("NOTION_DATABASE_ID"):
        try:
            import sys as _s2
            from pathlib import Path as _P2
            _s2.path.insert(0, str(_P2(__file__).parent))
            from agent_config import cfg as _acfg
            cfg["NOTION_DATABASE_ID"] = _acfg("NOTION_HARNESS_DB_ID", "de10157da3e34ef58a74ea240f31fe98")
        except Exception:
            cfg["NOTION_DATABASE_ID"] = "de10157da3e34ef58a74ea240f31fe98"
    return cfg


def _notion_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def poll_tickets(api_key: str, db_id: str, agent_user_id: str,
                 last_sync_at: str, db) -> list[dict]:
    """
    Query Notion DB for tickets modified since last_sync_at that are
    assigned to Kamil OR have any status set.
    Returns list of page dicts.
    """
    body = {
        "filter": {
            "and": [
                {
                    "timestamp": "last_edited_time",
                    "last_edited_time": {"after": last_sync_at},
                },
                {
                    "property": "Phase",
                    "select": {"is_not_empty": True},
                },
            ]
        },
        "page_size": 50,
    }

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"https://api.notion.com/v1/databases/{db_id}/query",
        data=data,
        headers=_notion_headers(api_key),
        method="POST",
    )
    _, body_bytes = notion_request(req)
    result = json.loads(body_bytes)
    return result.get("results", [])


def poll_comments(api_key: str, page_id: str, last_sync_at: str) -> list[dict]:
    """Fetch comments on a page, filter to those after last_sync_at containing @Kamil."""
    req = urllib.request.Request(
        f"https://api.notion.com/v1/comments?block_id={page_id}",
        headers=_notion_headers(api_key),
        method="GET",
    )
    _, body_bytes = notion_request(req)
    result = json.loads(body_bytes)
    comments = result.get("results", [])

    filtered = []
    for c in comments:
        created = c.get("created_time", "")
        if created > last_sync_at:
            # Check if any rich_text segment mentions @Kamil
            texts = []
            for rt in c.get("rich_text", []):
                texts.append(rt.get("plain_text", ""))
            if any("kamil" in t.lower() or "@kamil" in t.lower() for t in texts):
                filtered.append(c)
    return filtered


def _page_title(page: dict) -> str:
    props = page.get("properties", {})
    # Harness DB uses "Feature" as title property
    for name, prop in props.items():
        if prop.get("type") == "title":
            parts = prop.get("title", [])
            return "".join(p.get("plain_text", "") for p in parts)
    return page.get("id", "unknown")


def main() -> int:
    cfg = _load_config()
    api_key = cfg.get("NOTION_API_KEY")
    db_id = cfg.get("NOTION_DATABASE_ID", "de10157da3e34ef58a74ea240f31fe98")
    agent_user_id = cfg.get("NOTION_AGENT_USER_ID", "")

    if not api_key:
        print("[poll-notion] ERROR: No NOTION_API_KEY", file=sys.stderr)
        return 1

    db = get_db()
    last_sync_at = db.execute(
        "SELECT last_sync_at FROM sync_state WHERE id='global'"
    ).fetchone()[0]

    # Notion API rejects epoch (1970) — use 7 days ago as minimum
    from datetime import timezone, timedelta
    epoch = "1970-01-01T00:00:00Z"
    if last_sync_at == epoch:
        last_sync_at = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"[poll-notion] Polling since {last_sync_at}")

    try:
        pages = poll_tickets(api_key, db_id, agent_user_id, last_sync_at, db)
    except Exception as e:
        print(f"[poll-notion] ERROR querying Notion DB: {e}", file=sys.stderr)
        klog_error("poll-notion-query", e, component="orchestrator")
        return 1

    new_events = 0
    for page in pages:
        page_id = page["id"].replace("-", "")
        page_url = page.get("url", f"https://notion.so/{page_id}")
        title = _page_title(page)

        # Register entity (INSERT OR IGNORE — safe to re-register)
        entity_id = register_entity(db, "notion", page_id, "ticket", page_url)

        # Determine event type — new ticket if this entity was just registered
        event_id = f"notion-{page_id}"
        payload = json.dumps({"id": page_id, "title": title, "url": page_url})
        db.execute(
            "INSERT OR IGNORE INTO events "
            "(id, source, type, context_key, payload, status, received_at) "
            "VALUES (?, 'notion', 'ticket.created', ?, ?, 'pending', datetime('now'))",
            (event_id, entity_id, payload),
        )
        if db.execute("SELECT changes()").fetchone()[0] > 0:
            new_events += 1
            print(f"[poll-notion] ticket.created: {title[:60]}")
        db.commit()

        # Poll comments on this page
        try:
            comments = poll_comments(api_key, page_id, last_sync_at)
        except Exception:
            comments = []  # don't abort tick for comment fetch failure

        for comment in comments:
            comment_id = comment["id"].replace("-", "")
            event_id_c = f"notion-comment-{comment_id}"
            payload_c = json.dumps({"comment_id": comment_id, "page_id": page_id})
            db.execute(
                "INSERT OR IGNORE INTO events "
                "(id, source, type, context_key, payload, status, received_at) "
                "VALUES (?, 'notion', 'comment.tagged', ?, ?, 'pending', datetime('now'))",
                (event_id_c, entity_id, payload_c),
            )
            if db.execute("SELECT changes()").fetchone()[0] > 0:
                new_events += 1
                print(f"[poll-notion] comment.tagged on: {title[:40]}")
            db.commit()

    print(f"[poll-notion] Done. {len(pages)} pages, {new_events} new events.")
    klog("poll-notion", component="orchestrator", action="poll",
         pages=len(pages), new_events=new_events)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
