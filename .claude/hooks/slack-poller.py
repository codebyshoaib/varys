#!/usr/bin/env python3
"""
slack-poller: Runs every 30 min via cron.

Reads Slack channels → writes new relevant messages to /tmp/kamil-slack-inbox.json
Claude reads that file at session start and writes to Notion via MCP.

On any fatal error → sends Kamal a Slack DM.

Cron:
  */30 * * * * python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/slack-poller.py >> /tmp/kamil-slack.log 2>&1

Config:
  ~/.claude/hooks/.slack  →  SLACK_TOKEN=xoxp-...
"""

import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_CONFIG   = Path.home() / ".claude" / "hooks" / ".slack"
INBOX_FILE     = Path("/tmp/kamil-slack-inbox.json")
KAMIL_INBOX_DIR = Path.home() / "kamil-inbox"

KAMAL_USER_ID = "U0AV1DX3WSE"
KAMIL_TRIGGER_KEYWORDS = ["@kamil", "kamil,", "hey kamil", "kamil:"]

MONITOR_CHANNELS = {
    "C0B0BP5RT8F": "#engineering-pr-review",
    "C0AGBDTPCHZ": "#engineering",
    "C0ATWHRCYS0": "#engineering-fullstack",
    "C0B211B5747": "#engineering-team",
    "C0ATBGETMDM": "#engineering-qa",
    "C0B0X1SGQD7": "#engineering-ai",
    "C0AUM8FFRPS": "#engineering-deployments",
    "C0AUM8DQ2KA": "#engineering-learning",
    "C0AU4DPFG21": "#presence",
    "C0AU5BWCHF0": "#missioncomms",
    "C0AG25N6ST1": "#orenda-general",
    "C0AV1U13GU8": "#team-digitalcoach",
    "C0ATSA4RH8F": "#team-lessonplan",
    "C0AUV5NP801": "#team-coachtraining",
    "C0AULFWSH4H": "#team-examgenerator",
    "C0ATPQZV27M": "#growth-team",
    "C0AV1812KJB": "#region-rawalpindi",
    "C0B2GUWBYDQ": "#tanzania-testing",
    "C0ATPEB8ZAT": "#digital-learning",
    "C0B02K9V6R0": "#digital-learning-schema-architects",
}


def load_config(path: Path) -> dict:
    config = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                config[k.strip()] = v.strip()
    return config


def slack_get(token: str, endpoint: str, params: dict = None) -> dict:
    base = f"https://slack.com/api/{endpoint}"
    if params:
        base += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(base, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log(f"Slack API error ({endpoint}): {e}")
        return {}


def slack_dm_kamal(token: str, message: str):
    """Send Kamal a DM on Slack."""
    # Open DM channel
    open_resp = slack_post(token, "conversations.open", {"users": KAMAL_USER_ID})
    if not open_resp.get("ok"):
        log(f"Could not open DM: {open_resp.get('error')}")
        return
    channel_id = open_resp.get("channel", {}).get("id")
    if not channel_id:
        return
    result = slack_post(token, "chat.postMessage", {
        "channel": channel_id,
        "text": message,
    })
    if result.get("ok"):
        log("Slack DM sent to Kamal.")
    else:
        log(f"Slack DM failed: {result.get('error')}")


def slack_post(token: str, endpoint: str, payload: dict) -> dict:
    url = f"https://slack.com/api/{endpoint}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log(f"Slack POST error ({endpoint}): {e}")
        return {}


def log(msg: str):
    print(f"[slack-poller] {msg}", file=sys.stderr)


def load_inbox() -> list:
    """Load existing inbox items to avoid duplicates."""
    if INBOX_FILE.exists():
        try:
            return json.loads(INBOX_FILE.read_text())
        except Exception:
            return []
    return []


def save_inbox(items: list):
    INBOX_FILE.write_text(json.dumps(items, indent=2))


def classify_message(text: str, from_id: str, channel_name: str = "") -> tuple:
    text_lower = text.lower()
    if "github.com" in text_lower and "pull" in text_lower:
        return "PR Review Request", "Needs Action"
    if KAMAL_USER_ID in text:
        return "Mention", "Unread"
    if channel_name in ("#engineering-learning", "#engineering-ai") and "http" in text_lower:
        return "FYI", "FYI"
    if from_id == "U0B1XDPP8JC":  # Rumi
        return "FYI", "FYI"
    if any(w in text_lower for w in ["bug", "crash", "oom", "error", "failing", "broken"]):
        return "Bug Report", "FYI"
    if "?" in text and KAMAL_USER_ID in text:
        return "Question", "Needs Action"
    return "FYI", "FYI"


def poll_channel(token: str, channel_id: str, channel_name: str,
                 existing_permalinks: set, since_ts: str) -> list:
    result = slack_get(token, "conversations.history", {
        "channel": channel_id,
        "oldest": since_ts,
        "limit": 20,
    })
    if not result.get("ok"):
        log(f"Channel {channel_name} error: {result.get('error', 'unknown')}")
        return []

    new_items = []
    learning_channels = {
        "#engineering-learning", "#engineering-ai", "#growth-team",
        "#region-rawalpindi", "#tanzania-testing", "#digital-learning",
        "#digital-learning-schema-architects",
    }

    for msg in result.get("messages", []):
        text    = msg.get("text", "")
        from_id = msg.get("user", "")
        ts      = msg.get("ts", "")
        permalink = f"https://taleemabad-talk.slack.com/archives/{channel_id}/p{ts.replace('.', '')}"

        if permalink in existing_permalinks:
            continue

        is_relevant = (
            KAMAL_USER_ID in text
            or "github.com" in text.lower()
            or from_id == KAMAL_USER_ID
            or "<!channel>" in text
            or "<!subteam" in text
            or from_id == "U0B1XDPP8JC"
            or (channel_name in learning_channels and (
                "http" in text.lower() or len(text) > 100
            ))
        )
        if not is_relevant:
            continue

        # Queue for Kamil inbox if directed at Kamil
        text_lower = text.lower()
        if any(kw in text_lower for kw in KAMIL_TRIGGER_KEYWORDS):
            write_to_kamil_inbox(text, channel_name, from_id, ts)

        msg_type, status = classify_message(text, from_id, channel_name)
        preview = text[:300].replace("\n", " ")

        try:
            dt = datetime.fromtimestamp(float(ts))
            iso_date = dt.strftime("%Y-%m-%d")
        except Exception:
            iso_date = datetime.now().strftime("%Y-%m-%d")

        from_label = f"<@{from_id}>" if from_id else "Unknown"
        if from_id == KAMAL_USER_ID:
            from_label = "You (Kamal)"

        new_items.append({
            "permalink": permalink,
            "message":   preview or "(no text)",
            "from":      from_label,
            "channel":   channel_name,
            "status":    status,
            "type":      msg_type,
            "received":  iso_date,
            "notion_synced": False,
        })
        log(f"Captured: [{msg_type}] {preview[:60]}")

    return new_items


def poll_dms(token: str, existing_permalinks: set, since_ts: str) -> list:
    result = slack_get(token, "conversations.list", {"types": "im", "limit": 20})
    if not result.get("ok"):
        log(f"DM list error: {result.get('error')}")
        return []

    new_items = []
    for ch in result.get("channels", []):
        ch_id = ch.get("id", "")
        dm_result = slack_get(token, "conversations.history", {
            "channel": ch_id,
            "oldest": since_ts,
            "limit": 10,
        })
        if not dm_result.get("ok"):
            continue

        for msg in dm_result.get("messages", []):
            text    = msg.get("text", "")
            from_id = msg.get("user", "")
            ts      = msg.get("ts", "")

            if from_id == KAMAL_USER_ID:
                continue

            permalink = f"https://taleemabad-talk.slack.com/archives/{ch_id}/p{ts.replace('.', '')}"
            if permalink in existing_permalinks:
                continue

            msg_type, status = classify_message(text, from_id)
            preview = text[:300].replace("\n", " ")

            try:
                dt = datetime.fromtimestamp(float(ts))
                iso_date = dt.strftime("%Y-%m-%d")
            except Exception:
                iso_date = datetime.now().strftime("%Y-%m-%d")

            new_items.append({
                "permalink": permalink,
                "message":   preview or "(no text)",
                "from":      f"<@{from_id}>",
                "channel":   "DM",
                "status":    status,
                "type":      msg_type,
                "received":  iso_date,
                "notion_synced": False,
            })

    return new_items


def write_to_kamil_inbox(text: str, source_channel: str, from_id: str, ts: str):
    KAMIL_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    safe_ts = ts.replace(".", "-")
    inbox_file = KAMIL_INBOX_DIR / f"{safe_ts}-slack.json"
    if inbox_file.exists():
        return
    payload = {
        "id": f"{safe_ts}-slack",
        "source": "slack",
        "text": text,
        "channel": source_channel,
        "from_id": from_id,
        "timestamp": datetime.now().isoformat(),
    }
    inbox_file.write_text(json.dumps(payload, indent=2))
    log(f"Kamil inbox: queued message from {from_id} in {source_channel}")


def main():
    slack_cfg = load_config(SLACK_CONFIG)
    token = slack_cfg.get("SLACK_TOKEN") or os.environ.get("SLACK_TOKEN")

    if not token:
        msg = "⚠️ Kamil slack-poller DEAD: No SLACK_TOKEN found in ~/.claude/hooks/.slack — Slack sync is broken."
        log(msg)
        # Can't DM without a token — just log and exit
        return 1

    since = datetime.now() - timedelta(hours=4)
    since_ts = str(since.timestamp())
    log(f"Polling since {since.strftime('%Y-%m-%d %H:%M')} PKT")

    try:
        existing_items = load_inbox()
        existing_permalinks = {item["permalink"] for item in existing_items}
        log(f"{len(existing_items)} existing items in local inbox")

        new_items = []
        for ch_id, ch_name in MONITOR_CHANNELS.items():
            new_items.extend(poll_channel(token, ch_id, ch_name, existing_permalinks, since_ts))

        new_items.extend(poll_dms(token, existing_permalinks, since_ts))

        # Keep last 200 items to avoid file bloat
        all_items = existing_items + new_items
        all_items = all_items[-200:]
        save_inbox(all_items)

        log(f"Done. Added {len(new_items)} new items. Total in inbox: {len(all_items)}.")
        return 0

    except Exception as e:
        error_msg = f"⚠️ Kamil slack-poller crashed at {datetime.now().strftime('%Y-%m-%d %H:%M')} PKT\nError: {e}\nSlack sync is broken — check /tmp/kamil-slack.log"
        log(f"FATAL: {e}")
        slack_dm_kamal(token, error_msg)
        return 1


if __name__ == "__main__":
    sys.exit(main())
