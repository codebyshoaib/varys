#!/usr/bin/env python3
"""
slack-poller: Standalone script — run on a cron or manually.

Reads your Slack channels, finds new messages mentioning you,
new PRs posted, unread threads — then upserts them into Notion Slack Inbox.

Run:
  python3 ~/.claude/hooks/slack-poller.py

Or add to cron (runs every 30 min):
  */30 * * * * python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/slack-poller.py

Config files:
  ~/.claude/hooks/.notion   →  NOTION_API_KEY=secret_...
  ~/.claude/hooks/.slack    →  SLACK_TOKEN=xoxp-...

The Slack token needs these scopes:
  channels:history, channels:read, groups:history, groups:read,
  im:history, im:read, mpim:history, mpim:read, search:read, users:read
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
NOTION_CONFIG = Path.home() / ".claude" / "hooks" / ".notion"
SLACK_CONFIG  = Path.home() / ".claude" / "hooks" / ".slack"

DB_PAGE_SLACK_INBOX = "6d14f1b6b8cd4ff68fd40efdfc3f304e"

KAMAL_USER_ID = "U0AV1DX3WSE"
KAMIL_INBOX_DIR = Path.home() / "kamil-inbox"
KAMIL_TRIGGER_KEYWORDS = ["@kamil", "kamil,", "hey kamil", "kamil:"]

# Channels to monitor — Kamil is a sponge, reads everything
MONITOR_CHANNELS = {
    # Engineering core
    "C0B0BP5RT8F": "#engineering-pr-review",
    "C0AGBDTPCHZ": "#engineering",
    "C0ATWHRCYS0": "#engineering-fullstack",
    "C0B211B5747": "#engineering-team",
    "C0ATBGETMDM": "#engineering-qa",
    "C0B0X1SGQD7": "#engineering-ai",
    "C0AUM8FFRPS": "#engineering-deployments",
    # Learning — Mashhood drops gold here daily
    "C0AUM8DQ2KA": "#engineering-learning",
    # Presence / standup
    "C0AU4DPFG21": "#presence",
    # Org-wide
    "C0AU5BWCHF0": "#missioncomms",
    "C0AG25N6ST1": "#orenda-general",
    # Product teams — understand what Kamal's backend serves
    "C0AV1U13GU8": "#team-digitalcoach",
    "C0ATSA4RH8F": "#team-lessonplan",
    "C0AUV5NP801": "#team-coachtraining",
    "C0AULFWSH4H": "#team-examgenerator",
    # Growth + Rumi's channels — learn from the best agent in the org
    "C0ATPQZV27M": "#growth-team",
    "C0AV1812KJB": "#region-rawalpindi",
    "C0B2GUWBYDQ": "#tanzania-testing",
    # Digital learning schema
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
    """Call Slack API GET endpoint."""
    base = f"https://slack.com/api/{endpoint}"
    if params:
        base += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        base,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"[slack-poller] Slack API error ({endpoint}): {e}", file=sys.stderr)
        return {}


def notion_query(api_key: str, db_id: str, filter_body: dict = None) -> list:
    """Query Notion database."""
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    body = {"page_size": 100}
    if filter_body:
        body["filter"] = filter_body
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()).get("results", [])
    except Exception as e:
        print(f"[slack-poller] Notion query error: {e}", file=sys.stderr)
        return []


def notion_create_page(api_key: str, db_id: str, properties: dict) -> bool:
    """Create a page in a Notion database."""
    url = "https://api.notion.com/v1/pages"
    body = {
        "parent": {"database_id": db_id},
        "properties": properties,
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return "id" in result
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[slack-poller] Notion create error {e.code}: {body[:200]}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[slack-poller] Notion create error: {e}", file=sys.stderr)
        return False


def make_notion_text(value: str) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": value[:2000]}}]}


def make_notion_title(value: str) -> dict:
    return {"title": [{"type": "text", "text": {"content": value[:2000]}}]}


def make_notion_select(value: str) -> dict:
    return {"select": {"name": value}}


def make_notion_date(iso: str) -> dict:
    return {"date": {"start": iso}}


def get_existing_links(api_key: str) -> set:
    """Get all existing Slack message links already in Notion Inbox to avoid duplicates."""
    pages = notion_query(api_key, DB_PAGE_SLACK_INBOX)
    links = set()
    for page in pages:
        link_prop = page.get("properties", {}).get("Link", {})
        url = link_prop.get("url", "")
        if url:
            links.add(url)
    return links


def classify_message(text: str, from_id: str, channel_name: str = "") -> tuple[str, str]:
    """
    Classify a message → (Type, Status).
    Returns Notion select values.
    """
    text_lower = text.lower()

    # PR review requests
    if "github.com" in text_lower and "pull" in text_lower:
        return "PR Review Request", "Needs Action"

    # Direct mentions of Kamal
    if KAMAL_USER_ID in text:
        return "Mention", "Unread"

    # Learning material — Mashhood, Shoaib, Hassan sharing resources
    if channel_name in ("#engineering-learning", "#engineering-ai") and "http" in text_lower:
        return "FYI", "FYI"

    # Rumi posts — always worth reading
    if from_id == "U0B1XDPP8JC":
        return "FYI", "FYI"

    # Bug / crash reports
    if any(w in text_lower for w in ["bug", "crash", "oom", "error", "failing", "broken"]):
        return "Bug Report", "FYI"

    # Questions directed at Kamal
    if "?" in text and KAMAL_USER_ID in text:
        return "Question", "Needs Action"

    return "FYI", "FYI"


def poll_channel(token: str, api_key: str, channel_id: str, channel_name: str,
                 existing_links: set, since_ts: str) -> int:
    """Poll one channel for new messages. Returns count of new items added."""
    result = slack_get(token, "conversations.history", {
        "channel": channel_id,
        "oldest": since_ts,
        "limit": 20,
    })

    if not result.get("ok"):
        print(f"[slack-poller] Channel {channel_name} error: {result.get('error', 'unknown')}", file=sys.stderr)
        return 0

    messages = result.get("messages", [])
    added = 0

    for msg in messages:
        text = msg.get("text", "")
        from_id = msg.get("user", "")
        ts = msg.get("ts", "")
        permalink = f"https://taleemabad-talk.slack.com/archives/{channel_id}/p{ts.replace('.', '')}"

        # Skip if already in Notion
        if permalink in existing_links:
            continue

        # Kamil is a sponge — capture broadly based on channel type
        is_learning_channel = ch_name in (
            "#engineering-learning", "#engineering-ai", "#growth-team",
            "#region-rawalpindi", "#tanzania-testing", "#digital-learning",
            "#digital-learning-schema-architects",
        )
        is_relevant = (
            KAMAL_USER_ID in text                    # Kamal mentioned
            or "github.com" in text.lower()          # PR / repo link
            or from_id == KAMAL_USER_ID              # Kamal sent it
            or "<!channel>" in text                  # @channel broadcast
            or "<!subteam" in text                   # @eng-team etc
            # Learning channels: capture anything with a link or substance
            or (is_learning_channel and (
                "http" in text.lower()
                or len(text) > 100                   # substantive message
            ))
            # Rumi posts — always capture
            or from_id == "U0B1XDPP8JC"
        )

        if not is_relevant:
            continue

        # Kamil inbox — if message is directed at Kamil, queue it
        text_lower_check = text.lower()
        if any(kw in text_lower_check for kw in KAMIL_TRIGGER_KEYWORDS):
            write_to_kamil_inbox(text, channel_name, from_id, ts)
            # Still continue to log in Notion Slack Inbox as normal

        msg_type, status = classify_message(text, from_id)

        # Truncate long messages
        preview = text[:300].replace("\n", " ")

        # Convert ts to ISO date
        try:
            dt = datetime.fromtimestamp(float(ts))
            iso_date = dt.strftime("%Y-%m-%d")
        except Exception:
            iso_date = datetime.now().strftime("%Y-%m-%d")

        # Determine sender name (best effort from text)
        from_label = f"<@{from_id}>" if from_id else "Unknown"
        if from_id == KAMAL_USER_ID:
            from_label = "You (Kamal)"

        properties = {
            "Message": make_notion_title(preview or "(no text)"),
            "From": make_notion_text(from_label),
            "Channel": make_notion_text(channel_name),
            "Status": make_notion_select(status),
            "Type": make_notion_select(msg_type),
            "Link": {"url": permalink},
            "Received": make_notion_date(iso_date),
        }

        if notion_create_page(api_key, DB_PAGE_SLACK_INBOX, properties):
            added += 1
            print(f"[slack-poller] Added: [{msg_type}] {preview[:60]}...", file=sys.stderr)

    return added


def poll_dms(token: str, api_key: str, existing_links: set, since_ts: str) -> int:
    """Poll DMs for messages to/from Kamal."""
    result = slack_get(token, "conversations.list", {
        "types": "im",
        "limit": 20,
    })

    if not result.get("ok"):
        print(f"[slack-poller] DM list error: {result.get('error')}", file=sys.stderr)
        return 0

    added = 0
    channels = result.get("channels", [])

    for ch in channels:
        ch_id = ch.get("id", "")
        dm_result = slack_get(token, "conversations.history", {
            "channel": ch_id,
            "oldest": since_ts,
            "limit": 10,
        })

        if not dm_result.get("ok"):
            continue

        for msg in dm_result.get("messages", []):
            text = msg.get("text", "")
            from_id = msg.get("user", "")
            ts = msg.get("ts", "")

            # Only capture DMs TO Kamal (from others) or from Kamal that have a question/PR
            is_to_kamal = from_id != KAMAL_USER_ID
            if not is_to_kamal:
                continue

            permalink = f"https://taleemabad-talk.slack.com/archives/{ch_id}/p{ts.replace('.', '')}"
            if permalink in existing_links:
                continue

            msg_type, status = classify_message(text, from_id)
            preview = text[:300].replace("\n", " ")

            try:
                dt = datetime.fromtimestamp(float(ts))
                iso_date = dt.strftime("%Y-%m-%d")
            except Exception:
                iso_date = datetime.now().strftime("%Y-%m-%d")

            properties = {
                "Message": make_notion_title(preview or "(no text)"),
                "From": make_notion_text(f"<@{from_id}>"),
                "Channel": make_notion_text("DM"),
                "Status": make_notion_select(status),
                "Type": make_notion_select(msg_type),
                "Link": {"url": permalink},
                "Received": make_notion_date(iso_date),
            }

            if notion_create_page(api_key, DB_PAGE_SLACK_INBOX, properties):
                added += 1

    return added


def write_to_kamil_inbox(text: str, source_channel: str, from_id: str, ts: str):
    """Write a message directed at Kamil into the inbox queue."""
    KAMIL_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    safe_ts = ts.replace(".", "-")
    inbox_file = KAMIL_INBOX_DIR / f"{safe_ts}-slack.json"
    if inbox_file.exists():
        return  # already queued
    payload = {
        "id": f"{safe_ts}-slack",
        "source": "slack",
        "text": text,
        "cwd": "",
        "project": "",
        "channel": source_channel,
        "from_id": from_id,
        "timestamp": datetime.now().isoformat(),
    }
    inbox_file.write_text(json.dumps(payload, indent=2))
    print(f"[slack-poller] Kamil inbox: queued message from {from_id} in {source_channel}", file=sys.stderr)


def main():
    notion_cfg = load_config(NOTION_CONFIG)
    slack_cfg  = load_config(SLACK_CONFIG)

    api_key = notion_cfg.get("NOTION_API_KEY") or os.environ.get("NOTION_API_KEY")
    token   = slack_cfg.get("SLACK_TOKEN") or os.environ.get("SLACK_TOKEN")

    if not api_key:
        print("[slack-poller] ERROR: No NOTION_API_KEY in ~/.claude/hooks/.notion", file=sys.stderr)
        print("Create the file with: NOTION_API_KEY=secret_...", file=sys.stderr)
        return 1

    if not token:
        print("[slack-poller] ERROR: No SLACK_TOKEN in ~/.claude/hooks/.slack", file=sys.stderr)
        print("Create the file with: SLACK_TOKEN=xoxp-...", file=sys.stderr)
        print("Get token from: https://api.slack.com/apps → Your App → OAuth & Permissions", file=sys.stderr)
        return 1

    # Poll messages from last 4 hours (avoid duplicate flooding)
    since = datetime.now() - timedelta(hours=4)
    since_ts = str(since.timestamp())

    print(f"[slack-poller] Polling since {since.strftime('%Y-%m-%d %H:%M')} PKT", file=sys.stderr)

    # Get existing Notion Inbox links to avoid duplicates
    existing_links = get_existing_links(api_key)
    print(f"[slack-poller] {len(existing_links)} existing items in Notion Inbox", file=sys.stderr)

    total_added = 0

    # Poll all monitored channels
    for ch_id, ch_name in MONITOR_CHANNELS.items():
        count = poll_channel(token, api_key, ch_id, ch_name, existing_links, since_ts)
        total_added += count

    # Poll DMs
    total_added += poll_dms(token, api_key, existing_links, since_ts)

    print(f"[slack-poller] Done. Added {total_added} new items to Notion Inbox.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
