#!/usr/bin/env python3
"""
slack-poller: Runs every 30 min via cron.

1. Reads Slack channels → captures relevant messages
2. Writes new items to /tmp/varys-slack-inbox.json (Claude syncs to Notion via MCP)
3. Posts a summary DM to Shoaib: what was read, what was learned, what was done
4. On any fatal error → DMs Shoaib immediately

Cron:
  */30 * * * * python3 .claude/hooks/slack-poller.py >> /tmp/varys-slack.log 2>&1

Config:
  ~/.claude/hooks/.slack  →  SLACK_TOKEN=xoxp-...
                             BOT_TOKEN=xoxb-...
"""

import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_config import cfg
from varys_log import klog, klog_error, klog_poller
from varys_eval_tracker import eval_poller_summary, eval_self_question
try:
    from varys_harness_db import get_db, acquire_tick_lock, release_tick_lock
    _harness_db_available = True
except Exception:
    _harness_db_available = False

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_CONFIG    = Path.home() / ".claude" / "hooks" / ".slack"
INBOX_FILE      = Path("/tmp/agent-slack-inbox.json")
STATE_FILE      = Path("/tmp/varys-poller-state.json")
VARYS_INBOX_DIR = Path.home() / "varys-inbox"
WORKSPACE       = cfg("SLACK_WORKSPACE", "taleemabad-talk.slack.com")

SHOAIB_USER_ID = cfg("USER_SLACK_ID", "")
VARYS_TRIGGER_KEYWORDS = ["@shoaib_s_pr_beacon", "<@u0b0cq34bst>", "pr beacon", "@shoaib's pr beacon"]

LEARNING_CHANNELS = {
    "#engineering-learning", "#engineering-ai", "#growth-team",
    "#region-rawalpindi", "#tanzania-testing", "#digital-learning",
    "#digital-learning-schema-architects",
}

MONITOR_CHANNELS = {
    "C0B0BP5RT8F": "#engineering-pr-review",
    "C0AGBDTPCHZ": "#engineering",
    "C0ATWHRCYS0": "#engineering-fullstack",
    "C0B211B5747": "#engineering-team",
    "C0ATBGETMDM": "#engineering-qa",
    "C0B0X1SGQD7": "#engineering-ai",
    "C0AUM8FFRPS": "#engineering-deployments",
    ""  # set your channel IDs in ~/.agent-config.json: "#engineering-learning",
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_config(path: Path) -> dict:
    config = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                config[k.strip()] = v.strip()
    return config


def log(msg: str):
    print(f"[slack-poller] {msg}", file=sys.stderr)


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
    url = f"https://slack.com/api/{endpoint}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log(f"Slack POST error ({endpoint}): {e}")
        return {}


def open_dm(token: str) -> str | None:
    """Open a DM channel with Shoaib, return channel ID."""
    resp = slack_post(token, "conversations.open", {"users": SHOAIB_USER_ID})
    if resp.get("ok"):
        return resp.get("channel", {}).get("id")
    log(f"Could not open DM: {resp.get('error')}")
    return None


def send_dm(token: str, channel_id: str, text: str, blocks: list = None):
    payload = {"channel": channel_id, "text": text}
    if blocks:
        payload["blocks"] = blocks
    result = slack_post(token, "chat.postMessage", payload)
    if not result.get("ok"):
        log(f"DM send failed: {result.get('error')}")


def load_inbox() -> list:
    if INBOX_FILE.exists():
        try:
            return json.loads(INBOX_FILE.read_text())
        except Exception:
            return []
    return []


def save_inbox(items: list):
    INBOX_FILE.write_text(json.dumps(items, indent=2))


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def classify_message(text: str, from_id: str, channel_name: str = "") -> tuple:
    text_lower = text.lower()
    if "github.com" in text_lower and "pull" in text_lower:
        return "PR Review Request", "Needs Action"
    if SHOAIB_USER_ID in text:
        return "Mention", "Unread"
    if channel_name in LEARNING_CHANNELS and "http" in text_lower:
        return "FYI", "FYI"
    if from_id == "U0B1XDPP8JC":  # Rumi
        return "FYI", "FYI"
    if any(w in text_lower for w in ["bug", "crash", "oom", "error", "failing", "broken"]):
        return "Bug Report", "FYI"
    if "?" in text and SHOAIB_USER_ID in text:
        return "Question", "Needs Action"
    return "FYI", "FYI"


def extract_links(text: str) -> list:
    """Pull URLs out of a Slack message."""
    import re
    # Slack wraps URLs like <https://...> or <https://...|display text>
    return re.findall(r"<(https?://[^|>]+)[|>]", text)


# ── Polling ───────────────────────────────────────────────────────────────────

def poll_channel(token: str, channel_id: str, channel_name: str,
                 existing_permalinks: set, since_ts: str) -> list:
    result = slack_get(token, "conversations.history", {
        "channel": channel_id,
        "oldest": since_ts,
        "limit": 30,
    })
    if not result.get("ok"):
        log(f"Channel {channel_name} error: {result.get('error', 'unknown')}")
        return []

    new_items = []
    for msg in result.get("messages", []):
        text    = msg.get("text", "")
        from_id = msg.get("user", "")
        ts      = msg.get("ts", "")
        permalink = f"https://{WORKSPACE}/archives/{channel_id}/p{ts.replace('.', '')}"

        if permalink in existing_permalinks:
            continue

        is_relevant = (
            SHOAIB_USER_ID in text
            or "github.com" in text.lower()
            or from_id == SHOAIB_USER_ID
            or "<!channel>" in text
            or "<!subteam" in text
            or from_id == "U0B1XDPP8JC"
            or (channel_name in LEARNING_CHANNELS and (
                "http" in text.lower() or len(text) > 100
            ))
        )
        if not is_relevant:
            continue

        if any(kw in text.lower() for kw in VARYS_TRIGGER_KEYWORDS):
            write_to_varys_inbox(text, channel_name, from_id, ts)

        msg_type, status = classify_message(text, from_id, channel_name)
        preview = text[:300].replace("\n", " ")
        links   = extract_links(text)

        try:
            iso_date = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
        except Exception:
            iso_date = datetime.now().strftime("%Y-%m-%d")

        from_label = f"<@{from_id}>" if from_id else "Unknown"
        if from_id == SHOAIB_USER_ID:
            from_label = "You (Shoaib)"

        new_items.append({
            "permalink":      permalink,
            "message":        preview or "(no text)",
            "from":           from_label,
            "from_id":        from_id,
            "channel":        channel_name,
            "status":         status,
            "type":           msg_type,
            "received":       iso_date,
            "links":          links,
            "notion_synced":  False,
        })

    return new_items


def poll_dms(token: str, existing_permalinks: set, since_ts: str) -> list:
    result = slack_get(token, "conversations.list", {"types": "im", "limit": 20})
    if not result.get("ok"):
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

            if from_id == SHOAIB_USER_ID:
                continue

            permalink = f"https://{WORKSPACE}/archives/{ch_id}/p{ts.replace('.', '')}"
            if permalink in existing_permalinks:
                continue

            msg_type, status = classify_message(text, from_id)
            preview = text[:300].replace("\n", " ")

            try:
                iso_date = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
            except Exception:
                iso_date = datetime.now().strftime("%Y-%m-%d")

            new_items.append({
                "permalink":     permalink,
                "message":       preview or "(no text)",
                "from":          f"<@{from_id}>",
                "from_id":       from_id,
                "channel":       "DM",
                "status":        status,
                "type":          msg_type,
                "received":      iso_date,
                "links":         extract_links(text),
                "notion_synced": False,
            })

    return new_items


def write_to_varys_inbox(text: str, source_channel: str, from_id: str, ts: str):
    VARYS_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    safe_ts   = ts.replace(".", "-")
    inbox_file = VARYS_INBOX_DIR / f"{safe_ts}-slack.json"
    if inbox_file.exists():
        return
    payload = {
        "id":        f"{safe_ts}-slack",
        "source":    "slack",
        "text":      text,
        "channel":   source_channel,
        "from_id":   from_id,
        "timestamp": datetime.now().isoformat(),
    }
    inbox_file.write_text(json.dumps(payload, indent=2))
    log(f"Varys inbox queued: {from_id} in {source_channel}")


# ── Self-question exploration ─────────────────────────────────────────────────

SELF_QUESTIONS_PAGE = "365d8747b3b181b281b8ef5820e15881"
QUESTION_INDEX_FILE = Path("/tmp/varys-question-index.txt")

def explore_self_question(bot_token: str, dm_channel: str):
    """
    When Slack is quiet, pick the next unanswered question from the
    Self-Questions page, research it with real data, update the page,
    and DM Shoaib the finding.
    """
    # Rotate through question index
    idx = 0
    if QUESTION_INDEX_FILE.exists():
        try:
            idx = int(QUESTION_INDEX_FILE.read_text().strip())
        except Exception:
            idx = 0

    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    env = os.environ.copy()

    today = datetime.now().strftime('%Y-%m-%d')
    time_now = datetime.now().strftime('%H:%M')

    prompt = f"""You are Varys — Shoaib's autonomous AI agent. Slack is quiet. Use this time well.

## YOUR JOB THIS CYCLE
Pick question #{idx} from the "Next Questions to Explore" checklist on this Notion page:
{SELF_QUESTIONS_PAGE}

Fetch that page first with mcp__claude_ai_Notion__notion-fetch to read the current questions.
Pick the #{idx % 8} item from the "Next Questions to Explore" section (wrap around if needed).

## RESEARCH IT
Use real data sources:
- Notion MCP → for Shoaib's PRs, Work Log, Harness, Team People
- Slack Inbox file → /tmp/varys-slack-inbox.json
- GitHub → `gh pr list --repo taleemabad/taleemabad-core --limit 10` or relevant repo
- Web search → if it's a technical or external question

## AFTER RESEARCHING
1. Write a 2-3 sentence answer based on what you actually found (not guesses)
2. Update the Self-Questions Notion page:
   - Move the question from "Next Questions to Explore" to the relevant section
   - Add "**Answer ({today}):** [your finding]" under it
   - Add 1-2 new questions to the queue based on what you discovered
   Use mcp__claude_ai_Notion__notion-update-page with update_content command.

3. Output ONLY a Slack-formatted DM message (2-4 lines):
   "🧠 *[question topic]* — [1 line finding]
   [1 line of context or implication]
   _Asked myself: [the new question I just added to the queue]_"

Today: {today} PKT
Time: {time_now}
Question index: {idx}"""

    env["VARYS_PROMPT"] = prompt
    try:
        result = subprocess.run(
            ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$VARYS_PROMPT"'],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent.parent),
            timeout=180, env=env,
        )
        finding = result.stdout.strip() if result.returncode == 0 else ""
    except Exception as e:
        finding = ""
        log(f"explore_self_question error: {e}")

    # Advance index
    QUESTION_INDEX_FILE.write_text(str(idx + 1))

    # Score: did Claude use a real tool? Check for Notion/GitHub/Slack references in answer
    tool_keywords = ["notion", "github", "slack-inbox", "gh pr", "mcp__", "found", "checked"]
    tool_used     = any(kw in finding.lower() for kw in tool_keywords)
    followup      = "asked myself" in finding.lower() or "new question" in finding.lower()
    eval_self_question(
        question       = f"Question #{idx}",
        answer         = finding[:300] if finding else "(no answer)",
        tool_used      = tool_used,
        spawned_followup = followup,
    )

    if finding and len(finding) > 20:
        send_dm(bot_token, dm_channel, finding)
        log(f"Self-question explored: {finding[:80]}")
    else:
        send_dm(bot_token, dm_channel,
                f"*🕷️ {datetime.now().strftime('%H:%M')} —* Slack quiet. Researching open questions... check Notion Self-Questions page for updates.")


# ── Summary DM ────────────────────────────────────────────────────────────────

def build_summary_dm(new_items: list, total_inbox: int, run_ts: str) -> str:
    now = datetime.now().strftime("%H:%M")

    # Nothing actionable — return empty string, caller will run self-question instead
    if not new_items:
        return ""

    # Only surface items that actually need eyes: mentions, PRs, bugs, DMs
    priority = [i for i in new_items if i["type"] in ("Mention", "PR Review Request", "Bug Report", "Question")]
    learned  = [i for i in new_items if i["channel"] in LEARNING_CHANNELS and i["links"]]

    # Only FYIs — also trigger self-question
    if not priority and not learned:
        return ""

    lines = [f"*🕷️ {now} — {len(priority) + len(learned)} things worth your eyes*\n"]

    for item in priority[:5]:
        t       = item["type"]
        frm     = item["from"]
        channel = item["channel"]
        msg     = item["message"][:90].rstrip()
        link    = item["permalink"]

        if t == "Mention":
            lines.append(f"📣 *{frm}* mentioned you in {channel}")
            lines.append(f'   _"{msg}"_')
            lines.append(f"   → Reply or: _\"Varys reply to [name] tell them...\"_")
            lines.append(f"   <{link}|Open>")
        elif t == "PR Review Request":
            lines.append(f"🔀 *New PR* in {channel} from {frm}")
            lines.append(f'   _"{msg}"_')
            lines.append(f"   → Say _\"Varys review that PR\"_ and I'll do it")
            lines.append(f"   <{link}|Open>")
        elif t == "Bug Report":
            lines.append(f"🐛 *Bug/error* in {channel}")
            lines.append(f'   _"{msg}"_')
            lines.append(f"   <{link}|Open>")
        elif t == "Question":
            lines.append(f"❓ *{frm}* asked something in {channel}")
            lines.append(f'   _"{msg}"_')
            lines.append(f"   <{link}|Open>")
        lines.append("")

    if learned:
        first = learned[0]
        link  = first["links"][0] if first["links"] else ""
        lines.append(f"📚 *{first['from']}* shared in {first['channel']}")
        if link:
            lines.append(f"   {link}")
        if len(learned) > 1:
            lines.append(f"   _(+{len(learned)-1} more links)_")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Tick lock — prevent re-entrant cron runs (harness-v2 pattern)
    _db = None
    if _harness_db_available:
        try:
            _db = get_db()
            if not acquire_tick_lock(_db, "slack-poller"):
                log("Tick already running — skipping this cron run")
                return 0
        except Exception as e:
            log(f"WARNING: tick lock unavailable ({e}) — proceeding without lock")
            _db = None

    try:
        return _main_body()
    finally:
        if _db:
            try:
                release_tick_lock(_db)
                _db.close()
            except Exception:
                pass


def _main_body() -> int:
    slack_cfg = load_config(SLACK_CONFIG)
    token     = slack_cfg.get("SLACK_TOKEN") or os.environ.get("SLACK_TOKEN")
    bot_token = slack_cfg.get("BOT_TOKEN")   or os.environ.get("BOT_TOKEN")

    if not token:
        log("FATAL: No SLACK_TOKEN — cannot poll Slack or DM Shoaib.")
        return 1

    since    = datetime.now() - timedelta(hours=4)
    since_ts = str(since.timestamp())
    run_ts   = datetime.now().isoformat()
    log(f"Polling since {since.strftime('%Y-%m-%d %H:%M')} PKT")

    try:
        existing_items      = load_inbox()
        existing_permalinks = {item["permalink"] for item in existing_items}
        log(f"{len(existing_items)} existing items in local inbox")

        new_items = []
        for ch_id, ch_name in MONITOR_CHANNELS.items():
            new_items.extend(poll_channel(token, ch_id, ch_name, existing_permalinks, since_ts))

        new_items.extend(poll_dms(token, existing_permalinks, since_ts))

        all_items = (existing_items + new_items)[-200:]
        save_inbox(all_items)
        save_state({"last_run": run_ts, "last_count": len(new_items)})

        log(f"Done. Added {len(new_items)} new items. Total: {len(all_items)}.")

        # Break down by type for telemetry
        by_type = {}
        for item in new_items:
            by_type[item["type"]] = by_type.get(item["type"], 0) + 1
        klog_poller(new_items=len(new_items), total_inbox=len(all_items),
                    channels_read=len(MONITOR_CHANNELS), by_type=by_type)

        # Post summary DM or explore a self-question if quiet
        dm_token   = bot_token or token
        dm_channel = open_dm(dm_token)
        if dm_channel:
            summary = build_summary_dm(new_items, len(all_items), run_ts)
            if summary:
                result = slack_post(dm_token, "chat.postMessage",
                                    {"channel": dm_channel, "text": summary})
                log("Summary DM sent to Shoaib.")
                msg_ts = result.get("ts", "") if result.get("ok") else ""
                eval_poller_summary(summary=summary, new_items=len(new_items),
                                    channel=dm_channel, ts=msg_ts)
            else:
                # Slack is quiet — use this time to explore a self-question
                log("Slack quiet — exploring self-question.")
                load1, _, _ = os.getloadavg()
                if load1 < 2.0:
                    explore_self_question(dm_token, dm_channel)
                else:
                    log(f"Skipping self-question — system load too high ({load1:.1f})")
        else:
            log("Could not open DM channel.")

        return 0

    except Exception as e:
        klog_error(context="poller_run", exc=e)
        error_msg = (
            f"⚠️ *Varys slack-poller CRASHED*\n"
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')} PKT\n"
            f"Error: `{e}`\n"
            f"Slack sync is broken. Check `/tmp/varys-slack.log`."
        )
        log(f"FATAL: {e}")
        try:
            dm_token   = bot_token or token
            dm_channel = open_dm(dm_token)
            if dm_channel:
                send_dm(dm_token, dm_channel, error_msg)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
