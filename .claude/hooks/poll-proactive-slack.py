#!/usr/bin/env python3
"""
poll-proactive-slack.py — Watch configured channels for signals Kamil should act on.

Runs every tick as the 4th poller. Reads proactive-channels.md for config.
Inserts events into harness.db for any message matching watch keywords
that isn't already tied to an existing session/event.

Deterministic event ID: slack-<channel_id>-<message_ts>
INSERT OR IGNORE is always safe.

Event types produced:
  message.proactive        — match found in watch-mode channel
  message.proactive_banter — human-mode channel awareness item
"""

import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_harness_db import get_db, get_last_sync_at, set_last_sync_at
try:
    from kamil_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

KAMIL_DIR    = Path(__file__).parent.parent.parent
RULES_DIR    = KAMIL_DIR / ".claude" / "rules"
CHANNELS_CFG = RULES_DIR / "proactive-channels.md"
SLACK_CFG    = Path.home() / ".claude" / "hooks" / ".slack"
KAMAL_SLACK_ID = "U0AV1DX3WSE"


def _load_token():
    """Load SLACK_USER_TOKEN from env or config file."""
    for key in ("SLACK_USER_TOKEN", "SLACK_BOT_TOKEN", "USER_TOKEN", "BOT_TOKEN"):
        val = os.environ.get(key)
        if val:
            return val
    if SLACK_CFG.exists():
        for line in SLACK_CFG.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() in ("SLACK_USER_TOKEN", "USER_TOKEN"):
                    return v.strip()
    return None


def _parse_channels_config():
    """Parse proactive-channels.md into list of {name, mode, keywords}."""
    if not CHANNELS_CFG.exists():
        return []
    channels = []
    for line in CHANNELS_CFG.read_text().splitlines():
        line = line.strip()
        # Skip empty lines, markdown headers (but not channel lines with |), and separators
        if not line or line == "---":
            continue
        if line.startswith("Format") or line.startswith("Modes") or line.startswith("- `"):
            continue
        # Channel lines start with # but contain | — check for | to distinguish from markdown headers
        if line.startswith("#") and "|" not in line:
            continue
        # Now split config lines (e.g., "#engineering-general | watch | broken,failing,error")
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 2:
            channel_name = parts[0].lstrip("#")
            mode         = parts[1].strip()
            keywords     = [k.strip().lower() for k in parts[2].split(",")] if len(parts) > 2 and parts[2].strip() else []
            channels.append({"name": channel_name, "mode": mode, "keywords": keywords})
    return channels


def _slack_get(token, endpoint, params):
    """Make a GET request to Slack API."""
    url = f"https://slack.com/api/{endpoint}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _resolve_channel_id(token, name):
    """Resolve channel name to ID."""
    data = _slack_get(token, "conversations.list", {"limit": 200, "types": "public_channel,private_channel"})
    for ch in data.get("channels", []):
        if ch.get("name") == name:
            return ch["id"]
    return None


def _message_matches(text, keywords):
    """Check if text contains any keyword (case-insensitive)."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def main():
    user_token = _load_token()
    if not user_token:
        print("[proactive-poll] No user token — skipping", file=sys.stderr)
        return 0

    db       = get_db()
    channels = _parse_channels_config()
    if not channels:
        print("[proactive-poll] No channels configured", file=sys.stderr)
        db.close()
        return 0

    # Look back from last_sync_at to now (600s = 10 min margin)
    last_sync = get_last_sync_at(db)
    dt = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
    oldest = str(int(dt.timestamp()))

    inserted = 0

    for ch_cfg in channels:
        # Skip read-only/banter channels unless in specific mode
        if ch_cfg["mode"] == "read-only" and not ch_cfg["keywords"]:
            continue

        ch_id = _resolve_channel_id(user_token, ch_cfg["name"])
        if not ch_id:
            print(f"[proactive-poll] WARNING: Could not resolve channel {ch_cfg['name']}", file=sys.stderr)
            continue

        try:
            data = _slack_get(user_token, "conversations.history",
                              {"channel": ch_id, "oldest": oldest, "limit": 50})
        except Exception as e:
            klog_error("proactive-poll-fetch", e, channel=ch_cfg["name"], component="orchestrator")
            print(f"[proactive-poll] ERROR fetching {ch_cfg['name']}: {e}", file=sys.stderr)
            continue

        if not data.get("ok"):
            print(f"[proactive-poll] ERROR: conversations.history failed for {ch_cfg['name']}: {data.get('error')}", file=sys.stderr)
            continue

        for msg in data.get("messages", []):
            text    = msg.get("text", "")
            ts      = msg.get("ts", "")
            user_id = msg.get("user", "")

            # Skip bot messages and system messages
            if msg.get("bot_id") or msg.get("subtype"):
                continue

            if ch_cfg["mode"] == "banter":
                # Log all messages as awareness items
                event_id = f"slack-{ch_id}-{ts}"
                db.execute(
                    "INSERT OR IGNORE INTO events "
                    "(id, source, type, context_key, payload, status, received_at) "
                    "VALUES (?, 'slack', 'message.proactive_banter', ?, ?, 'pending', datetime('now'))",
                    (event_id, event_id,
                     json.dumps({"channel": ch_id, "ts": ts, "text": text[:500], "user": user_id}))
                )
                inserted += db.execute("SELECT changes()").fetchone()[0]
                continue

            if ch_cfg["mode"] == "watch" and ch_cfg["keywords"]:
                if not _message_matches(text, ch_cfg["keywords"]):
                    continue
                # Skip if already handled as @Kamil mention
                if f"<@{KAMAL_SLACK_ID}>" in text or "kamil" in text.lower():
                    continue

                event_id = f"slack-{ch_id}-{ts}"
                db.execute(
                    "INSERT OR IGNORE INTO events "
                    "(id, source, type, context_key, payload, status, received_at) "
                    "VALUES (?, 'slack', 'message.proactive', ?, ?, 'pending', datetime('now'))",
                    (event_id, event_id,
                     json.dumps({"channel": ch_id, "ts": ts, "text": text[:500],
                                 "user": user_id, "channel_name": ch_cfg["name"]}))
                )
                inserted += db.execute("SELECT changes()").fetchone()[0]

    db.commit()
    db.close()
    print(f"[proactive-poll] {inserted} new proactive events inserted")
    klog("proactive-poll-complete", component="orchestrator", inserted=inserted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
