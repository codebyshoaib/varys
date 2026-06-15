#!/usr/bin/env python3
"""
slack-daily-digest.py — Daily 4:50 PM channel sweep.

Reads all messages from monitored channels since yesterday's digest,
extracts who said what, infers mood/work state per person, updates
the People Intelligence DB, and appends a context snapshot to a
rolling daily context file.

Cron: 50 16 * * * cd ~/Taleemabad/varys-agent-v2 && python3 .claude/hooks/slack-daily-digest.py >> /tmp/varys-daily-digest.log 2>&1
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_config import cfg
from varys_log import klog, klog_error
from varys_notion import notion_request

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_CONFIG = Path.home() / ".claude" / "hooks" / ".slack"
STATE_FILE   = Path("/tmp/varys-daily-digest-state.json")
CONTEXT_FILE = Path.home() / "varys-inbox" / "channel-context.json"

PEOPLE_DB_ID = "c976d58ea4e34b0585f245529cdc4528"
PEOPLE_DS_ID = "c00daef1-c072-4263-b23d-e1b5e2ba596c"

WORKSPACE = cfg("SLACK_WORKSPACE", "taleemabad-talk.slack.com")

MONITOR_CHANNELS = {
    "C0B0BP5RT8F": "#engineering-pr-review",
    "C0AGBDTPCHZ": "#engineering",
    "C0ATWHRCYS0": "#engineering-fullstack",
    "C0B211B5747": "#engineering-team",
    "C0ATBGETMDM": "#engineering-qa",
    "C0B0X1SGQD7": "#engineering-ai",
    "C0AUM8FFRPS": "#engineering-deployments",
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

# ponytail: mood inference is intentionally heuristic — good enough, no ML needed
STRESS_WORDS   = {"blocked", "broken", "crash", "urgent", "asap", "stuck", "failing", "error", "oom", "critical"}
POSITIVE_WORDS = {"thanks", "done", "shipped", "merged", "fixed", "lgtm", "approved", "great"}


def log(msg):
    print(f"[daily-digest] {msg}", file=sys.stderr)


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
        log(f"Slack GET error ({endpoint}): {e}")
        return {}


def slack_post(token: str, endpoint: str, payload: dict) -> dict:
    url  = f"https://slack.com/api/{endpoint}"
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log(f"Slack POST error ({endpoint}): {e}")
        return {}


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def infer_mood(texts: list[str]) -> str:
    combined = " ".join(texts).lower()
    stress   = sum(1 for w in STRESS_WORDS   if w in combined)
    positive = sum(1 for w in POSITIVE_WORDS if w in combined)
    if stress > positive:
        return "stressed"
    if positive > stress:
        return "positive"
    return "neutral"


def resolve_user_names(token: str, user_ids: set) -> dict:
    """Batch-resolve Slack user IDs → display names."""
    names = {}
    for uid in user_ids:
        resp = slack_get(token, "users.info", {"user": uid})
        if resp.get("ok"):
            profile = resp.get("user", {}).get("profile", {})
            names[uid] = profile.get("display_name") or profile.get("real_name") or uid
        time.sleep(0.2)  # be kind to Slack rate limits
    return names


def sweep_channel(token: str, ch_id: str, ch_name: str, since_ts: str) -> list[dict]:
    """Collect all messages in a channel since since_ts."""
    messages = []
    cursor   = None
    while True:
        params = {"channel": ch_id, "oldest": since_ts, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        result = slack_get(token, "conversations.history", params)
        if not result.get("ok"):
            log(f"{ch_name}: {result.get('error', 'unknown error')}")
            break
        for msg in result.get("messages", []):
            uid  = msg.get("user", "")
            text = msg.get("text", "")
            ts   = msg.get("ts", "")
            if not uid or not text:
                continue
            messages.append({"uid": uid, "text": text, "ts": ts, "channel": ch_name})
        meta = result.get("response_metadata", {})
        cursor = meta.get("next_cursor")
        if not cursor:
            break
    return messages


def lookup_notion_person(name: str, notion_token: str) -> str | None:
    """Search People DB for a page matching this name, return page_id or None."""
    url  = "https://api.notion.com/v1/databases/{}/query".format(PEOPLE_DB_ID)
    body = json.dumps({
        "filter": {
            "property": "Name",
            "title": {"contains": name[:20]}
        }
    }).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Authorization":  f"Bearer {notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type":   "application/json",
        },
        method="POST",
    )
    try:
        status, body_bytes = notion_request(req)
        data = json.loads(body_bytes)
        results = data.get("results", [])
        return results[0]["id"] if results else None
    except Exception as e:
        log(f"Notion lookup error for {name}: {e}")
        return None


def update_notion_person(page_id: str, name: str, mood: str,
                          topics: list[str], today: str, notion_token: str):
    url  = f"https://api.notion.com/v1/pages/{page_id}"
    props = {
        "Current Mood":    {"select": {"name": mood.capitalize()}},
        "date:Last Seen:start": {"date": {"start": today}},
        "Recurring Topics": {"rich_text": [{"text": {"content": ", ".join(topics[:5])}}]},
    }
    body = json.dumps({"properties": props}).encode()
    req  = urllib.request.Request(
        url, data=body,
        headers={
            "Authorization":  f"Bearer {notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type":   "application/json",
        },
        method="PATCH",
    )
    try:
        notion_request(req)
    except Exception as e:
        log(f"Notion update error for {page_id}: {e}")


def create_notion_person(name: str, uid: str, mood: str,
                          topics: list[str], today: str, notion_token: str):
    url  = "https://api.notion.com/v1/pages"
    body = json.dumps({
        "parent":     {"database_id": PEOPLE_DB_ID},
        "properties": {
            "Name":             {"title": [{"text": {"content": name}}]},
            "Slack ID":         {"rich_text": [{"text": {"content": uid}}]},
            "Current Mood":     {"select": {"name": mood.capitalize()}},
            "Relationship":     {"select": {"name": "Distant"}},
            "Interaction Count":{"number": 1},
            "Recurring Topics": {"rich_text": [{"text": {"content": ", ".join(topics[:5])}}]},
            "date:Last Seen:start": {"date": {"start": today}},
            "Varys Notes":      {"rich_text": [{"text": {"content": f"[{today}] First seen via daily digest"}}]},
        },
    }).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Authorization":  f"Bearer {notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type":   "application/json",
        },
        method="POST",
    )
    try:
        notion_request(req)
    except Exception as e:
        log(f"Notion create error for {name}: {e}")


def extract_topics(texts: list[str]) -> list[str]:
    """Simple keyword extraction — no ML, good enough."""
    import re
    stopwords = {"the", "a", "an", "is", "in", "on", "at", "to", "for", "of",
                 "and", "or", "but", "it", "this", "that", "was", "are", "has",
                 "have", "i", "you", "we", "they", "be", "with", "from", "not",
                 "can", "will", "just", "also", "been"}
    freq = {}
    for text in texts:
        for word in re.findall(r"[a-z]{4,}", text.lower()):
            if word not in stopwords:
                freq[word] = freq.get(word, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:10]]


def build_summary_dm(person_updates: list[dict], total_msgs: int,
                     channels_swept: int, today: str) -> str:
    lines = [f"*📊 Daily digest — {today}*"]
    lines.append(f"Swept {channels_swept} channels · {total_msgs} messages\n")

    stressed = [p for p in person_updates if p["mood"] == "stressed"]
    positive = [p for p in person_updates if p["mood"] == "positive"]
    active   = sorted(person_updates, key=lambda p: -p["msg_count"])[:5]

    if stressed:
        names = ", ".join(p["name"] for p in stressed[:3])
        lines.append(f"⚠️ Stressed signals: {names}")
    if positive:
        names = ", ".join(p["name"] for p in positive[:3])
        lines.append(f"✅ Positive vibes: {names}")

    lines.append(f"\n*Most active:*")
    for p in active:
        topics = ", ".join(p["topics"][:3]) if p["topics"] else "misc"
        lines.append(f"  • {p['name']} ({p['msg_count']} msgs) — {topics}")

    return "\n".join(lines)


def main():
    slack_cfg     = load_config(SLACK_CONFIG)
    token         = slack_cfg.get("SLACK_USER_TOKEN") or slack_cfg.get("SLACK_TOKEN") or os.environ.get("SLACK_TOKEN")
    bot_token     = slack_cfg.get("BOT_TOKEN")   or os.environ.get("BOT_TOKEN")
    notion_token  = os.environ.get("NOTION_API_KEY") or slack_cfg.get("NOTION_API_KEY")
    user_slack_id = cfg("USER_SLACK_ID", "")

    if not token:
        log("FATAL: No SLACK_TOKEN")
        return 1

    state    = load_state()
    today    = datetime.now().strftime("%Y-%m-%d")
    # Read since last digest, or 24h ago if first run
    since_ts = state.get("last_run_ts") or str((datetime.now() - timedelta(hours=24)).timestamp())
    log(f"Sweeping since {datetime.fromtimestamp(float(since_ts)).strftime('%Y-%m-%d %H:%M')}")

    # ── Sweep all channels ────────────────────────────────────────────────────
    all_msgs: list[dict] = []
    for ch_id, ch_name in MONITOR_CHANNELS.items():
        msgs = sweep_channel(token, ch_id, ch_name, since_ts)
        log(f"{ch_name}: {len(msgs)} messages")
        all_msgs.extend(msgs)

    if not all_msgs:
        log("No messages today — nothing to digest")
        save_state({"last_run_ts": str(datetime.now().timestamp()), "last_run_date": today})
        return 0

    # ── Group by person ───────────────────────────────────────────────────────
    by_person: dict[str, list[str]] = {}
    by_person_channels: dict[str, set] = {}
    for msg in all_msgs:
        uid = msg["uid"]
        if uid == user_slack_id:
            continue  # skip Shoaib's own messages
        by_person.setdefault(uid, []).append(msg["text"])
        by_person_channels.setdefault(uid, set()).add(msg["channel"])

    # Resolve names
    user_ids  = set(by_person.keys())
    log(f"Resolving {len(user_ids)} unique users")
    name_map  = resolve_user_names(token, user_ids)

    # ── Per-person analysis + Notion update ──────────────────────────────────
    person_updates = []
    for uid, texts in by_person.items():
        name   = name_map.get(uid, uid)
        mood   = infer_mood(texts)
        topics = extract_topics(texts)
        channels_active = list(by_person_channels.get(uid, set()))

        person_updates.append({
            "uid":      uid,
            "name":     name,
            "mood":     mood,
            "topics":   topics,
            "channels": channels_active,
            "msg_count": len(texts),
        })
        log(f"{name}: {len(texts)} msgs, mood={mood}, topics={topics[:3]}")

        # Update or create Notion People Intelligence entry
        if notion_token:
            page_id = lookup_notion_person(name, notion_token)
            if page_id:
                update_notion_person(page_id, name, mood, topics, today, notion_token)
            else:
                create_notion_person(name, uid, mood, topics, today, notion_token)

    # ── Write rolling context snapshot ───────────────────────────────────────
    CONTEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
    context_data = {
        "date":            today,
        "total_messages":  len(all_msgs),
        "channels_swept":  len(MONITOR_CHANNELS),
        "people":          person_updates,
    }
    # Keep last 7 days of snapshots in one file
    history = []
    if CONTEXT_FILE.exists():
        try:
            history = json.loads(CONTEXT_FILE.read_text())
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []
    history = [h for h in history if h.get("date") != today]  # replace today if re-run
    history.append(context_data)
    history = history[-7:]  # ponytail: keep 7 days, not infinite
    CONTEXT_FILE.write_text(json.dumps(history, indent=2))
    log(f"Context snapshot written ({len(person_updates)} people)")

    # ── Summary DM to Shoaib ──────────────────────────────────────────────────
    if bot_token:
        dm_resp = slack_post(bot_token, "conversations.open", {"users": user_slack_id})
        if dm_resp.get("ok"):
            dm_ch  = dm_resp["channel"]["id"]
            summary = build_summary_dm(person_updates, len(all_msgs), len(MONITOR_CHANNELS), today)
            slack_post(bot_token, "chat.postMessage", {"channel": dm_ch, "text": summary})
            log("Summary DM sent")

    save_state({"last_run_ts": str(datetime.now().timestamp()), "last_run_date": today})
    log("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
