#!/usr/bin/env python3
"""
poll-eng-slack.py — Poll engineering Slack channels for @Kamil mentions.

Called once per /loop tick AFTER tick lock is acquired.
Requires SLACK_USER_TOKEN (xoxp-) for search.messages API — bot token alone fails.

Two cases handled:
  1. NEW thread, no linked Notion ticket → create stub Notion ticket + link + event
  2. EXISTING linked ticket (Blocked state resume) → write message.tagged event

Event type produced:
  message.tagged — @Kamil mention in an engineering channel

Design rules:
  - Deterministic event ID: "slack-<channel_id>-<message_ts>"
  - INSERT OR IGNORE — re-polling same window is always safe
  - If this script exits non-zero: tick aborts, last_sync_at NOT updated
"""

import json
import os
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_harness_db import get_db, register_entity, link_entities, get_linked_entities
from kamil_notion import notion_request
try:
    from kamil_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_CFG  = Path.home() / ".claude" / "hooks" / ".slack"
NOTION_CFG = Path.home() / ".claude" / "hooks" / ".notion"
HARNESS_CFG = Path.home() / ".kamil-harness" / "config.json"

ENGINEERING_CHANNELS = [
    "C0AUM8DQ2KA",  # #engineering-learning
]
KAMIL_BOT_USER  = "U0B4L7RVA8L"
KAMIL_SLACK_ID  = "U0AV1DX3WSE"   # Kamal's personal Slack user ID (for @Kamil go detection)

NOTION_HARNESS_DB = "de10157da3e34ef58a74ea240f31fe98"


def _load_config() -> dict:
    cfg = {}
    if SLACK_CFG.exists():
        for line in SLACK_CFG.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    if NOTION_CFG.exists():
        for line in NOTION_CFG.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    if HARNESS_CFG.exists():
        cfg.update(json.loads(HARNESS_CFG.read_text()))
    for key in ("SLACK_BOT_TOKEN", "SLACK_USER_TOKEN", "NOTION_API_KEY"):
        if os.environ.get(key):
            cfg[key] = os.environ[key]
    return cfg


def _slack_search(user_token: str, oldest_ts: str) -> list[dict]:
    """Search all engineering channels for @Kamil mentions since oldest_ts."""
    params = urllib.parse.urlencode({
        "query": "in:#engineering-learning",
        "sort": "timestamp",
        "sort_dir": "asc",
        "count": 50,
    })
    req = urllib.request.Request(
        f"https://slack.com/api/search.messages?{params}",
        headers={"Authorization": f"Bearer {user_token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())

    if not data.get("ok"):
        raise RuntimeError(f"search.messages failed: {data.get('error')}")

    messages = data.get("messages", {}).get("matches", [])
    # Filter: engineering channel + newer than oldest_ts + mentions Kamil
    filtered = []
    for m in messages:
        ch = m.get("channel", {}).get("id", "")
        ts = m.get("ts", "0")
        text = m.get("text", "").lower()
        mentions_kamil = (
            "u0b4l7rva8l" in text or   # bot user ID mention
            "@kamil" in text or
            "kamil" in text
        )
        if ch in ENGINEERING_CHANNELS and float(ts) > float(oldest_ts) and mentions_kamil:
            filtered.append(m)
    return filtered


def _create_stub_notion_ticket(api_key: str, channel_id: str, ts: str,
                                text_preview: str) -> str | None:
    """Create a minimal Notion stub ticket for a Slack-originated task. Returns page_id."""
    thread_url = f"https://slack.com/archives/{channel_id}/p{ts.replace('.', '')}"
    stub_title = f"From Slack: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
    body = {
        "parent": {"database_id": NOTION_HARNESS_DB},
        "properties": {
            "Feature": {"title": [{"text": {"content": stub_title}}]},
            "Phase": {"select": {"name": "Research"}},
        },
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        _, resp_bytes = notion_request(req)
        result = json.loads(resp_bytes)
        return result.get("id", "").replace("-", "")
    except Exception as e:
        print(f"[poll-slack] ERROR creating stub ticket: {e}", file=sys.stderr)
        return None


def _find_linked_notion_entity(db, slack_entity_id: str) -> str | None:
    """Return Notion ticket entity_id linked to this Slack thread, if any."""
    linked = get_linked_entities(db, slack_entity_id)
    for e in linked:
        if e["source"] == "notion" and e["type"] == "ticket":
            return e["id"]
    return None


def main() -> int:
    cfg = _load_config()
    user_token = cfg.get("SLACK_USER_TOKEN")
    bot_token  = cfg.get("SLACK_BOT_TOKEN") or cfg.get("BOT_TOKEN")
    api_key    = cfg.get("NOTION_API_KEY")

    if not user_token:
        print("[poll-slack] ERROR: SLACK_USER_TOKEN required for search.messages", file=sys.stderr)
        return 1
    if not api_key:
        print("[poll-slack] ERROR: NOTION_API_KEY required to create stub tickets", file=sys.stderr)
        return 1

    db = get_db()
    last_sync_at = db.execute(
        "SELECT last_sync_at FROM sync_state WHERE id='global'"
    ).fetchone()[0]
    # Convert ISO to Slack ts format (unix timestamp)
    from datetime import timezone
    dt = datetime.fromisoformat(last_sync_at.replace("Z", "+00:00"))
    oldest_slack_ts = str(dt.timestamp())

    print(f"[poll-slack] Searching @Kamil mentions since {last_sync_at}")

    try:
        messages = _slack_search(user_token, oldest_slack_ts)
    except Exception as e:
        print(f"[poll-slack] ERROR: {e}", file=sys.stderr)
        klog_error("poll-slack-search", e, component="orchestrator")
        return 1

    new_events = 0
    for msg in messages:
        channel_id = msg.get("channel", {}).get("id", "")
        ts         = msg.get("ts", "")
        thread_ts  = msg.get("thread_ts") or ts
        text       = msg.get("text", "")[:200]
        user       = msg.get("user", "")

        # Skip Kamil's own messages
        if user == KAMIL_BOT_USER:
            continue

        slack_external_id = f"{channel_id}/{thread_ts}"
        thread_url = f"https://slack.com/archives/{channel_id}/p{thread_ts.replace('.', '')}"

        # Register Slack thread entity
        slack_entity_id = register_entity(db, "slack", slack_external_id,
                                          "thread", thread_url)

        # Check if there's already a linked Notion ticket (Blocked-state resume)
        notion_entity_id = _find_linked_notion_entity(db, slack_entity_id)

        if not notion_entity_id:
            # Case 1: New thread — create stub Notion ticket
            page_id = _create_stub_notion_ticket(api_key, channel_id, thread_ts, text)
            if not page_id:
                continue  # failed to create stub — skip this message

            page_url = f"https://notion.so/{page_id}"
            notion_entity_id = register_entity(db, "notion", page_id, "ticket", page_url)
            link_entities(db, slack_entity_id, notion_entity_id,
                          "originated_from", "poll-slack")
            print(f"[poll-slack] Created stub ticket for Slack thread {thread_ts[:10]}")
        else:
            print(f"[poll-slack] Resuming blocked ticket for thread {thread_ts[:10]}")

        # Write deterministic event
        event_id = f"slack-{channel_id}-{ts}"
        payload  = json.dumps({"channel": channel_id, "ts": ts, "text": text, "user": user})
        db.execute(
            "INSERT OR IGNORE INTO events "
            "(id, source, type, context_key, payload, status, received_at) "
            "VALUES (?, 'slack', 'message.tagged', ?, ?, 'pending', datetime('now'))",
            (event_id, notion_entity_id, payload),
        )
        if db.execute("SELECT changes()").fetchone()[0] > 0:
            new_events += 1

        # Detect "@Kamil go" — triggers Phase 2 worker for awaiting_approval sessions
        text_lower = msg.get("text", "").lower()
        if "go" in text_lower and (
            "kamil" in text_lower or
            f"<@{KAMIL_SLACK_ID}>" in msg.get("text", "")
        ):
            go_thread_ts = msg.get("thread_ts") or msg.get("ts")
            ext_id       = f"{channel_id}/{go_thread_ts}"
            linked_ctx   = db.execute(
                "SELECT e.id FROM entities e "
                "JOIN links l ON l.entity_a = e.id OR l.entity_b = e.id "
                "JOIN entities e2 ON (l.entity_a = e2.id OR l.entity_b = e2.id) "
                "WHERE e2.source='slack' AND e2.external_id=? AND e.source='notion'",
                (ext_id,)
            ).fetchone()
            if linked_ctx:
                context_key = linked_ctx[0]
                waiting = db.execute(
                    "SELECT id FROM sessions WHERE context_key=? AND status='awaiting_approval'",
                    (context_key,)
                ).fetchone()
                if waiting:
                    go_event_id = f"slack-go-{channel_id}-{msg.get('ts', '')}"
                    db.execute(
                        "INSERT OR IGNORE INTO events "
                        "(id, source, type, context_key, payload, status, received_at) "
                        "VALUES (?, 'slack', 'message.go_signal', ?, ?, 'pending', datetime('now'))",
                        (go_event_id, context_key,
                         json.dumps({"session_id": waiting[0], "channel": channel_id,
                                     "thread_ts": go_thread_ts}))
                    )
                    if db.execute("SELECT changes()").fetchone()[0] > 0:
                        print(f"[poll-slack] go_signal queued for context_key={context_key}")
                        new_events += 1

        db.commit()

    print(f"[poll-slack] Done. {len(messages)} messages, {new_events} new events.")
    klog("poll-slack", component="orchestrator", action="poll",
         messages=len(messages), new_events=new_events)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
