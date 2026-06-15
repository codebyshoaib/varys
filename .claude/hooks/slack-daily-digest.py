#!/usr/bin/env python3
"""
slack-daily-digest.py — Daily 4:50 PM channel sweep.

For each channel with messages today, calls Claude once to produce a
structured summary: who worked on what, who's blocked, what shipped.
#presence is parsed directly (attendance signals, no Claude needed).
Builds a 7-day rolling context file and DMs Shoaib a useful digest.

Cron: 50 16 * * * cd ~/Taleemabad/varys-agent-v2 && python3 .claude/hooks/slack-daily-digest.py >> /tmp/varys-daily-digest.log 2>&1
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_config import cfg
from varys_log import klog, klog_error

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_CONFIG  = Path.home() / ".claude" / "hooks" / ".slack"
STATE_FILE    = Path("/tmp/varys-daily-digest-state.json")
CONTEXT_FILE  = Path.home() / "varys-inbox" / "channel-context.json"
VARYS_DIR     = Path(__file__).parent.parent.parent

PRESENCE_CHANNEL_ID = "C0AU4DPFG21"  # #presence — attendance only, no Claude

WORK_CHANNELS = {
    "C0B0BP5RT8F": "#engineering-pr-review",
    "C0AGBDTPCHZ": "#engineering",
    "C0ATWHRCYS0": "#engineering-fullstack",
    "C0B211B5747": "#engineering-team",
    "C0ATBGETMDM": "#engineering-qa",
    "C0B0X1SGQD7": "#engineering-ai",
    "C0AUM8FFRPS": "#engineering-deployments",
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

CHANNEL_SCHEMA = {
    "type": "object",
    "properties": {
        "summary":    {"type": "string", "description": "One sentence: what happened in this channel today"},
        "mood":       {"type": "string", "enum": ["productive", "tense", "blocked", "quiet", "mixed"]},
        "people":     {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name":        {"type": "string"},
                    "working_on":  {"type": ["string", "null"]},
                    "blocked_on":  {"type": ["string", "null"]},
                    "shipped":     {"type": ["string", "null"]}
                },
                "required": ["name"]
            }
        },
        "key_links":  {"type": "array", "items": {"type": "string"}}
    },
    "required": ["summary", "mood", "people", "key_links"]
}


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


def sweep_channel(token: str, ch_id: str, ch_name: str, since_ts: str) -> list[dict]:
    messages = []
    cursor   = None
    while True:
        params = {"channel": ch_id, "oldest": since_ts, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        result = slack_get(token, "conversations.history", params)
        if not result.get("ok"):
            log(f"{ch_name}: {result.get('error', 'unknown')}")
            break
        for msg in result.get("messages", []):
            uid  = msg.get("user", "")
            text = msg.get("text", "")
            ts   = msg.get("ts", "")
            if uid and text:
                messages.append({"uid": uid, "text": text, "ts": ts})
        cursor = (result.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return messages


def resolve_names(token: str, uids: set) -> dict:
    names = {}
    for uid in uids:
        resp = slack_get(token, "users.info", {"user": uid})
        if resp.get("ok"):
            p = resp["user"].get("profile", {})
            names[uid] = p.get("display_name") or p.get("real_name") or uid
        time.sleep(0.2)
    return names


def parse_attendance(messages: list[dict], name_map: dict) -> dict:
    """Extract on_leave / working_remote / in_office from #presence messages."""
    attendance = {"on_leave": [], "working_remote": [], "in_office": []}
    for msg in messages:
        text  = msg["text"].lower()
        name  = name_map.get(msg["uid"], msg["uid"])
        if any(w in text for w in ("sick leave", "on leave", "hospital", "hospitali", "food poisoning", "fever", "not feeling")):
            attendance["on_leave"].append(name)
        elif any(w in text for w in ("working remote", "work remote", "remotely", "working from home", "wfh")):
            attendance["working_remote"].append(name)
        elif any(w in text for w in ("in office", "in the office", "heading to", "around")):
            attendance["in_office"].append(name)
    return attendance


def run_claude(prompt: str, timeout: int = 90) -> str:
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    env = os.environ.copy()
    env["VARYS_PROMPT"] = prompt
    try:
        result = subprocess.run(
            ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$VARYS_PROMPT"'],
            capture_output=True, text=True,
            cwd=str(VARYS_DIR), timeout=timeout, env=env,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception as e:
        log(f"Claude call failed: {e}")
        return ""


def summarise_channel(ch_name: str, messages: list[dict], name_map: dict) -> dict | None:
    """Call Claude once to summarise what happened in this channel today."""
    lines = []
    for msg in messages:
        name = name_map.get(msg["uid"], msg["uid"])
        lines.append(f"{name}: {msg['text'][:300]}")

    prompt = f"""You are reading today's Slack messages from {ch_name} at Taleemabad (an EdTech company).

MESSAGES:
{chr(10).join(lines)}

Return a JSON object with exactly these fields:
- summary: one sentence describing what happened in this channel today
- mood: one of "productive", "tense", "blocked", "quiet", "mixed"
- people: array of objects, one per person who said something meaningful. Each object:
  - name: their name
  - working_on: what they're building/doing (null if not clear)
  - blocked_on: what's blocking them (null if not blocked)
  - shipped: what they finished/merged/deployed (null if nothing)
- key_links: array of GitHub PR URLs or important links found in the messages (empty array if none)

Be specific. If someone posted a GitHub PR link, extract it. If someone said they're blocked on a review, say so.
Return ONLY the JSON object, no other text."""

    raw = run_claude(prompt)
    if not raw:
        return None

    # Extract JSON from output
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        log(f"{ch_name}: no JSON in Claude output")
        return None
    try:
        return json.loads(match.group())
    except Exception as e:
        log(f"{ch_name}: JSON parse failed: {e}")
        return None


def build_dm(today: str, attendance: dict, channel_summaries: dict) -> str:
    lines = [f"*📊 Daily digest — {today}*\n"]

    # Attendance block
    if attendance["on_leave"]:
        lines.append(f"🏥 On leave: {', '.join(attendance['on_leave'])}")
    if attendance["working_remote"]:
        lines.append(f"🏠 Remote: {', '.join(attendance['working_remote'])}")
    lines.append("")

    # Channel summaries — only channels with signal
    tense    = [(ch, s) for ch, s in channel_summaries.items() if s.get("mood") in ("tense", "blocked")]
    active   = [(ch, s) for ch, s in channel_summaries.items() if s.get("mood") == "productive"]
    shipped  = []
    blocked  = []
    for ch, s in channel_summaries.items():
        for p in s.get("people", []):
            if p.get("shipped"):
                shipped.append(f"{p['name']} ({ch}): {p['shipped']}")
            if p.get("blocked_on"):
                blocked.append(f"{p['name']} ({ch}): {p['blocked_on']}")

    if blocked:
        lines.append("*⚠️ Blocked:*")
        for b in blocked[:4]:
            lines.append(f"  • {b}")
        lines.append("")

    if shipped:
        lines.append("*✅ Shipped:*")
        for s in shipped[:4]:
            lines.append(f"  • {s}")
        lines.append("")

    lines.append("*Channels:*")
    for ch, s in channel_summaries.items():
        mood_icon = {"productive": "🟢", "tense": "🟡", "blocked": "🔴", "quiet": "⚪", "mixed": "🔵"}.get(s.get("mood", ""), "⚪")
        lines.append(f"  {mood_icon} *{ch}* — {s.get('summary', '')}")

    links = []
    for s in channel_summaries.values():
        links.extend(s.get("key_links", []))
    if links:
        lines.append(f"\n*PRs/Links:*")
        for link in links[:5]:
            lines.append(f"  • {link}")

    return "\n".join(lines)


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def main():
    slack_cfg     = load_config(SLACK_CONFIG)
    token         = slack_cfg.get("SLACK_USER_TOKEN") or slack_cfg.get("SLACK_TOKEN") or os.environ.get("SLACK_TOKEN")
    bot_token     = slack_cfg.get("BOT_TOKEN")        or os.environ.get("BOT_TOKEN")
    user_slack_id = cfg("USER_SLACK_ID", "")

    if not token:
        log("FATAL: No SLACK_TOKEN")
        return 1

    state    = load_state()
    today    = datetime.now().strftime("%Y-%m-%d")
    since_ts = state.get("last_run_ts") or str((datetime.now() - timedelta(hours=24)).timestamp())
    log(f"Sweeping since {datetime.fromtimestamp(float(since_ts)).strftime('%Y-%m-%d %H:%M')}")

    # ── Collect all messages ──────────────────────────────────────────────────
    all_uids: set = set()
    presence_msgs = sweep_channel(token, PRESENCE_CHANNEL_ID, "#presence", since_ts)
    log(f"#presence: {len(presence_msgs)} messages")
    all_uids |= {m["uid"] for m in presence_msgs}

    channel_msgs: dict[str, list] = {}
    for ch_id, ch_name in WORK_CHANNELS.items():
        msgs = sweep_channel(token, ch_id, ch_name, since_ts)
        if msgs:
            channel_msgs[ch_name] = msgs
            all_uids |= {m["uid"] for m in msgs}
            log(f"{ch_name}: {len(msgs)} messages")

    # ── Resolve names once ────────────────────────────────────────────────────
    log(f"Resolving {len(all_uids)} users")
    name_map = resolve_names(token, all_uids - {user_slack_id})

    # ── Attendance from #presence ─────────────────────────────────────────────
    attendance = parse_attendance(presence_msgs, name_map)
    log(f"Attendance — leave: {len(attendance['on_leave'])}, remote: {len(attendance['working_remote'])}, office: {len(attendance['in_office'])}")

    # ── Summarise each work channel with Claude ───────────────────────────────
    channel_summaries: dict[str, dict] = {}
    for ch_name, msgs in channel_msgs.items():
        log(f"Summarising {ch_name} ({len(msgs)} msgs)...")
        summary = summarise_channel(ch_name, msgs, name_map)
        if summary:
            channel_summaries[ch_name] = summary
            log(f"  → {summary.get('mood')} — {summary.get('summary', '')[:80]}")

    # ── Write rolling context file ────────────────────────────────────────────
    CONTEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "date":       today,
        "attendance": attendance,
        "channels":   channel_summaries,
    }
    history = []
    if CONTEXT_FILE.exists():
        try:
            history = json.loads(CONTEXT_FILE.read_text())
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []
    history = [h for h in history if h.get("date") != today]
    history.append(snapshot)
    history = history[-7:]
    CONTEXT_FILE.write_text(json.dumps(history, indent=2))
    log(f"Context written — {len(channel_summaries)} channels, 7-day rolling")

    # ── DM Shoaib ─────────────────────────────────────────────────────────────
    if bot_token and channel_summaries:
        dm_resp = slack_post(bot_token, "conversations.open", {"users": user_slack_id})
        if dm_resp.get("ok"):
            dm_ch   = dm_resp["channel"]["id"]
            summary = build_dm(today, attendance, channel_summaries)
            slack_post(bot_token, "chat.postMessage", {"channel": dm_ch, "text": summary})
            log("DM sent")

    save_state({"last_run_ts": str(datetime.now().timestamp()), "last_run_date": today})
    log("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
