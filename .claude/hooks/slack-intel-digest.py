#!/usr/bin/env python3
"""
slack-intel-digest.py — STEALTH twice-daily Slack intelligence digest.

Replaces slack-daily-digest.py. Runs on its own cron (twice/day), completely
independent of the @Varys mention pipeline (listener / slack_queue / orchestrator).

What it does:
  1. Dynamically lists EVERY channel Varys (the bot) is a member of — no hardcoded list.
  2. Reads each channel's history since the last run (bot token; read-only).
  3. Calls Claude per active channel → structured "who's working on what / blocked / shipped".
  4. Calls Claude once more → an executive summary across the org.
  5. DMs Shoaib ONE message: summary at top, per-channel/per-person detail below.

STEALTH — hard guarantee:
  The ONLY Slack write this script can make is the DM to Shoaib. It never posts,
  reacts, or replies in any channel. `_dm_shoaib()` is the single writer and it
  posts only to a DM channel (id starts with 'D') opened against Shoaib's user id —
  a swept channel id (C…) can never be a write target. Everything else is GET.

Cron (twice daily, ~09:00 + ~18:00 PKT):
  0 9  * * * cd ~/varys && python3 .claude/hooks/slack-intel-digest.py >> /tmp/varys-intel-digest.log 2>&1
  0 18 * * * cd ~/varys && python3 .claude/hooks/slack-intel-digest.py >> /tmp/varys-intel-digest.log 2>&1
To change the times: edit those two crontab lines (`crontab -e`), keep both pointed here.
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
try:
    from varys_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_CONFIG = Path.home() / ".claude" / "hooks" / ".slack"
# Durable across reboots (unlike /tmp) — lives beside the orchestrator's harness state,
# so last_run_ts survives and windows chain correctly instead of resetting to the 16h floor.
STATE_FILE   = Path.home() / ".varys-harness" / "intel-digest-state.json"
VARYS_DIR    = Path(__file__).parent.parent.parent
NOTION_CFG   = Path.home() / ".claude" / "hooks" / ".notion"
CONTEXT_FILE = Path.home() / ".varys-harness" / "intel-context.json"   # durable N-run rolling context
CONTEXT_KEEP = 14            # how many runs of structured context to retain
# 👥 People Intelligence DB — workspace-specific, so it comes from config, NEVER hardcoded.
# (cfg resolves ~/.agent-config.json → env → default; same key the rules use as {{config:NOTION_PEOPLE_DB_ID}}.)
PEOPLE_DB_ID = cfg("NOTION_PEOPLE_DB_ID", "")
MAX_PEOPLE   = 30            # cap people upserted per run
MAX_MSGS_PER_CHANNEL = 300   # cap context per channel to keep Claude calls bounded
HISTORY_FLOOR_HOURS  = 16    # first-run / state-loss ONLY: look back this far. 16h ≥ the 15h
                             # overnight gap between the 18:00 and 09:00 runs, so a deleted
                             # state file can't silently drop the overnight window.

CHANNEL_SCHEMA_HINT = """Return a JSON object with exactly these fields:
- summary: one sentence on what happened in this channel this window
- mood: one of "productive", "tense", "blocked", "quiet", "mixed"
- people: array of {name, working_on|null, blocked_on|null, shipped|null} — one per person who said something meaningful
- key_links: array of GitHub PR URLs / important links (empty array if none)
Return ONLY the JSON object, no other text."""


def log(msg):
    print(f"[intel-digest] {msg}", file=sys.stderr)


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


def _list(token: str, types: str, member_only: bool):
    """Paginate conversations.list. Returns {id: '#name'} or None on first-call failure."""
    out, cursor, any_ok = {}, None, False
    while True:
        params = {"types": types, "exclude_archived": "true", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        resp = slack_get(token, "conversations.list", params)
        if not resp.get("ok"):
            log(f"conversations.list({types}) error: {resp.get('error', 'unknown')}")
            return out if any_ok else None
        any_ok = True
        for c in resp.get("channels", []):
            if not member_only or c.get("is_member"):
                out[c["id"]] = f"#{c.get('name', c['id'])}"
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return out


def list_channels(bot_token: str, user_token: str | None):
    """Channels to sweep → {id: name}. With a user token we read EVERY public channel's history
    without the bot joining (proven: bot token returns not_in_channel; user token reads it fine),
    so coverage is the whole workspace, not just the 5 the bot was invited to. Private channels
    still require membership, so we add the ones the bot is in. No user token → fall back to the
    bot's own memberships (old behavior). Returns None on a HARD API failure so the caller can
    abort WITHOUT advancing the watermark."""
    # Enumeration always uses the bot token (the user token lacks channels:read). The user token's
    # value is reading HISTORY of channels the bot never joined — that happens in sweep_channel.
    if user_token:
        public = _list(bot_token, "public_channel", member_only=False)     # all public (sweep via user token)
        private = _list(bot_token, "private_channel", member_only=True)    # bot's private
        if public is None:
            return None
        return {**public, **(private or {})}
    return _list(bot_token, "public_channel,private_channel", member_only=True)


def sweep_channel(token: str, ch_id: str, ch_name: str, since_ts: str, fallback: str = None) -> list[dict]:
    """Read-only history sweep since `since_ts`. GET only. Tries `token` (user token — reads any
    public channel without joining); on not_in_channel/missing access retries once with `fallback`
    (bot token), which covers private channels the user token can't see."""
    messages, cursor = [], None
    tried_fallback = False
    while True:
        params = {"channel": ch_id, "oldest": since_ts, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        result = slack_get(token, "conversations.history", params)
        if not result.get("ok"):
            err = result.get("error", "")
            if fallback and not tried_fallback and err in ("not_in_channel", "channel_not_found", "missing_scope"):
                token, tried_fallback = fallback, True   # private channel → retry with bot token
                continue
            if err not in ("", "not_in_channel"):
                log(f"{ch_name}: {err or 'unknown'}")
            break
        for msg in result.get("messages", []):
            text = msg.get("text", "")
            ts   = msg.get("ts", "")
            if not text:
                continue
            uid = msg.get("user", "")
            if uid:
                messages.append({"uid": uid, "text": text, "ts": ts})
            elif msg.get("bot_id"):
                # Keep BOT messages too — PR Beacon / GitHub / CodeRabbit "PR ready / merged"
                # notices are the highest-signal "what shipped" data. Label with the bot name.
                bot_name = (msg.get("bot_profile") or {}).get("name") or msg.get("username") or "bot"
                messages.append({"uid": "", "name": bot_name, "text": text, "ts": ts})
        if len(messages) >= MAX_MSGS_PER_CHANNEL:
            break
        cursor = (result.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return messages[:MAX_MSGS_PER_CHANNEL]


MENTION_RE = re.compile(r"<@([UW][A-Z0-9]+)>")


def sub_mentions(text: str, name_map: dict) -> str:
    """Rewrite inline <@Uxxx> mentions to display names so the LLM never sees raw IDs."""
    return MENTION_RE.sub(lambda m: f"@{name_map.get(m.group(1), m.group(1))}", text)


def resolve_names(token: str, uids: set) -> dict:
    names = {}
    for uid in uids:
        resp = slack_get(token, "users.info", {"user": uid})
        if resp.get("ok"):
            p = resp["user"].get("profile", {})
            names[uid] = p.get("display_name") or p.get("real_name") or uid
        time.sleep(0.2)
    return names


def run_claude(prompt: str, timeout: int = 90) -> str:
    """Synthesis only. Spawned with VARYS_CONTENT_AGENT=1 so the drift hook hard-blocks
    any Slack send the model might attempt — synthesis can never post to a channel."""
    # ponytail: absolute path — cron's minimal PATH breaks nvm sourcing
    claude_bin = os.path.expanduser("~/.nvm/versions/node/v24.14.0/bin/claude")
    env = os.environ.copy()
    env["VARYS_PROMPT"] = prompt
    env["VARYS_CONTENT_AGENT"] = "1"
    try:
        result = subprocess.run(
            [claude_bin, "--dangerously-skip-permissions", "--print", "-p", prompt],
            capture_output=True, text=True,
            cwd=str(VARYS_DIR), timeout=timeout, env=env,
        )
        if result.returncode != 0:
            log(f"Claude exited {result.returncode}: {result.stderr.strip()[:200]}")
            return ""
        return result.stdout.strip()
    except Exception as e:
        log(f"Claude call failed: {e}")
        return ""


def _extract_json(raw: str):
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except Exception:
        return None


def summarise_channel(ch_name: str, messages: list[dict], name_map: dict) -> dict | None:
    lines = [f"{m.get('name') or name_map.get(m['uid'], m['uid'])}: {sub_mentions(m['text'], name_map)[:300]}" for m in messages]
    prompt = (
        f"You are reading recent Slack messages from {ch_name} at Taleemabad (EdTech company).\n\n"
        f"MESSAGES:\n{chr(10).join(lines)}\n\n{CHANNEL_SCHEMA_HINT}"
    )
    return _extract_json(run_claude(prompt))


def exec_summary(channel_summaries: dict) -> str:
    """One synthesis call → tight org-wide 'who's working on what' summary for the top of the DM."""
    if not channel_summaries:
        return "Quiet window — no notable channel activity."
    compact = {ch: {"summary": s.get("summary"),
                    "people": [{k: p.get(k) for k in ("name", "working_on", "blocked_on", "shipped")}
                               for p in s.get("people", [])]}
               for ch, s in channel_summaries.items()}
    prompt = (
        "You are Shoaib's chief-of-staff. Below is structured per-channel Slack activity at "
        "Taleemabad. Write a TIGHT executive summary (3-6 bullet lines, Slack markdown) of WHO is "
        "working on WHAT, what shipped, and who's blocked — across the whole org. Lead with the most "
        "important. No preamble, no header, just the bullets.\n\n"
        f"DATA:\n{json.dumps(compact, indent=1)[:6000]}"
    )
    out = run_claude(prompt, timeout=120).strip()
    return out or "Activity across channels (see details below)."


def build_dm(now_label: str, channel_summaries: dict, top: str) -> str:
    """Summary at top, detailed per-channel/per-person breakdown below."""
    lines = [f"*🕵️ Stealth intel digest — {now_label}*", "", "*Summary*", top, ""]

    shipped, blocked = [], []
    for ch, s in channel_summaries.items():
        for p in s.get("people", []):
            if p.get("shipped"):
                shipped.append(f"{p['name']} ({ch}): {p['shipped']}")
            if p.get("blocked_on"):
                blocked.append(f"{p['name']} ({ch}): {p['blocked_on']}")
    if blocked:
        lines += ["*⚠️ Blocked*"] + [f"  • {b}" for b in blocked[:8]] + [""]
    if shipped:
        lines += ["*✅ Shipped*"] + [f"  • {s}" for s in shipped[:8]] + [""]

    lines.append("*Details by channel*")
    mood_icon = {"productive": "🟢", "tense": "🟡", "blocked": "🔴", "quiet": "⚪", "mixed": "🔵"}
    for ch, s in sorted(channel_summaries.items()):
        icon = mood_icon.get(s.get("mood", ""), "⚪")
        lines.append(f"{icon} *{ch}* — {s.get('summary', '')}")
        for p in s.get("people", []):
            bits = []
            if p.get("working_on"): bits.append(f"working on {p['working_on']}")
            if p.get("blocked_on"): bits.append(f"blocked on {p['blocked_on']}")
            if p.get("shipped"):    bits.append(f"shipped {p['shipped']}")
            if bits:
                lines.append(f"     ◦ {p['name']}: {'; '.join(bits)}")

    links = []
    for s in channel_summaries.values():
        links.extend(s.get("key_links", []))
    if links:
        lines += ["", "*PRs / links*"] + [f"  • {l}" for l in links[:10]]
    return "\n".join(lines)


def _persist_context(channel_summaries: dict, now_label: str):
    """Durable N-run rolling context (~/.varys-harness/) so the digest builds memory across
    runs instead of forgetting everything but the watermark."""
    try:
        hist = []
        if CONTEXT_FILE.exists():
            hist = json.loads(CONTEXT_FILE.read_text())
            if not isinstance(hist, list):
                hist = []
        hist.append({"run": now_label, "channels": channel_summaries})
        CONTEXT_FILE.write_text(json.dumps(hist[-CONTEXT_KEEP:], indent=1))
        log(f"context persisted ({min(len(hist), CONTEXT_KEEP)}-run rolling)")
    except Exception as e:
        log(f"context persist failed: {e}")


def _aggregate_people(channel_summaries: dict, name_map: dict) -> list[dict]:
    """Collapse per-channel people into one record per person across all channels."""
    name_to_uid = {v: k for k, v in name_map.items()}
    people: dict[str, dict] = {}
    for ch, s in channel_summaries.items():
        for p in s.get("people", []):
            nm = (p.get("name") or "").strip()
            if not nm:
                continue
            rec = people.setdefault(nm, {"name": nm, "slack_id": name_to_uid.get(nm, ""),
                                         "channels": set(), "working_on": [], "blocked_on": [], "shipped": []})
            rec["channels"].add(ch)
            for k in ("working_on", "blocked_on", "shipped"):
                if p.get(k):
                    rec[k].append(p[k])
    out = []
    for r in people.values():
        r["channels"] = sorted(r["channels"])
        out.append(r)
    return out[:MAX_PEOPLE]


def _update_people_map(channel_summaries: dict, name_map: dict, today: str, notion_key: str):
    """Spawn a CONTAINED claude -p that upserts each active person into the People Intelligence
    DB via mcp__notion__ (cron has no MCP, so we delegate to an agent that does). The agent runs
    with VARYS_CONTENT_AGENT=1 → the drift hook blocks any Slack send; it can only touch Notion.
    Best-effort: never fails the digest (the DM already went out)."""
    if not notion_key or not PEOPLE_DB_ID:
        log("people-map: missing NOTION_API_KEY or NOTION_PEOPLE_DB_ID — skipping")
        return
    people = _aggregate_people(channel_summaries, name_map)
    if not people:
        return
    payload_file = Path("/tmp/varys-intel-people.json")
    payload_file.write_text(json.dumps(people, indent=1))
    prompt = f"""Update the People Intelligence DB from a Slack intel sweep. Use mcp__notion__ tools ONLY — never a raw API call, never Slack.

DB id: {PEOPLE_DB_ID}  (first fetch this database via mcp__notion__ to get its data source collection:// id, then query/create under that data source)
Exact fields: Name(title), "Slack ID"(text), Role(text), Team(text), "Recurring Topics"(text), "Current Mood"(select: Unknown/Good/Stressed/Blocked), "Interaction Count"(number), "Last Seen"(date), "Varys Notes"(text).

PEOPLE is a JSON array in the file {payload_file} — read it. For each person:
1. Find their page: query the data source by Name (and "Slack ID" if given).
2. If FOUND -> update: "Interaction Count" += 1; "Last Seen" = {today}; merge new items into "Recurring Topics" (comma-separated, dedupe); set Team/Role only if currently empty and inferable from their channels; then read the current "Varys Notes" and APPEND one line "{today}: <one line — what they worked on / shipped / are blocked on this window>" (keep all existing notes, never overwrite).
3. If NOT FOUND -> create a page: Name, "Slack ID" if given, Team/Role if inferable, "Recurring Topics", "Interaction Count"=1, "Last Seen"={today}, "Varys Notes"="{today}: <activity>".
Do not post to Slack. Finish with a one-line tally: "people-map: created N, updated M"."""
    claude_bin = os.path.expanduser("~/.nvm/versions/node/v24.14.0/bin/claude")
    env = os.environ.copy()
    env["VARYS_CONTENT_AGENT"] = "1"   # drift hook blocks Slack sends; Notion MCP still allowed
    env["NOTION_API_KEY"] = notion_key
    try:
        r = subprocess.run(
            [claude_bin, "--dangerously-skip-permissions", "--print", "-p", prompt],
            capture_output=True, text=True, cwd=str(VARYS_DIR), timeout=600, env=env,
        )
        out = (r.stdout or "").strip()
        tail = out.splitlines()[-1] if out else (r.stderr[:200] if r.stderr else "no output")
        log(f"people-map ({len(people)} people): {tail}")
    except Exception as e:
        log(f"people-map agent failed: {e}")
        klog_error("intel-people-map", e, component="intel")


def _dm_shoaib(bot_token: str, user_id: str, text: str) -> bool:
    """The ONLY Slack write in this script. Target is always Shoaib's DM (a 'D' channel
    opened against his user id) — never a swept channel id. This is the stealth guarantee."""
    # conversations.open is a POST, but we only ever target the user's DM.
    url  = "https://slack.com/api/conversations.open"
    data = json.dumps({"users": user_id}).encode()
    req  = urllib.request.Request(url, data=data,
        headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            opened = json.loads(r.read())
    except Exception as e:
        log(f"conversations.open failed: {e}")
        return False
    dm_ch = (opened.get("channel") or {}).get("id", "")
    if not opened.get("ok") or not dm_ch.startswith("D"):
        log(f"refusing to post: resolved channel {dm_ch!r} is not a DM")
        return False
    url  = "https://slack.com/api/chat.postMessage"
    data = json.dumps({"channel": dm_ch, "text": text}).encode()
    req  = urllib.request.Request(url, data=data,
        headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return bool(json.loads(r.read()).get("ok"))
    except Exception as e:
        log(f"DM post failed: {e}")
        return False


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def main():
    dry_run   = "--dry-run" in sys.argv
    slack_cfg  = load_config(SLACK_CONFIG)
    bot_token  = slack_cfg.get("BOT_TOKEN") or os.environ.get("BOT_TOKEN")
    user_token = slack_cfg.get("SLACK_USER_TOKEN") or os.environ.get("SLACK_USER_TOKEN")
    user_id    = cfg("USER_SLACK_ID", "")
    notion_key = load_config(NOTION_CFG).get("NOTION_API_KEY") or os.environ.get("NOTION_API_KEY")

    if not bot_token:
        log("FATAL: no BOT_TOKEN in ~/.claude/hooks/.slack")
        return 1
    if not user_id:
        log("FATAL: no USER_SLACK_ID in ~/.agent-config.json")
        return 1

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state    = load_state()
    since_ts = state.get("last_run_ts") or str((datetime.now() - timedelta(hours=HISTORY_FLOOR_HOURS)).timestamp())
    now_label = datetime.now().strftime("%a %d %b, %H:%M")
    log(f"Sweeping since {datetime.fromtimestamp(float(since_ts)).strftime('%Y-%m-%d %H:%M')}")

    if not user_token:
        log("no SLACK_USER_TOKEN — falling back to bot-membership channels only (limited coverage)")
    channels = list_channels(bot_token, user_token)
    if channels is None:
        log("ABORT: could not list channels (no network / bad token). NOT advancing watermark — "
            "this window will be retried on the next run (e.g. the post-listener startup catch-up).")
        klog_error("intel-digest-no-network", None, component="intel")
        return 1   # exit before any state write — the missed window is preserved
    log(f"Member channels: {len(channels)} → {', '.join(channels.values())}")

    channel_msgs, all_uids = {}, set()
    for ch_id, ch_name in channels.items():
        msgs = sweep_channel(user_token or bot_token, ch_id, ch_name, since_ts, fallback=bot_token)
        if msgs:
            channel_msgs[ch_name] = msgs
            all_uids |= {m["uid"] for m in msgs if m.get("uid")}
            for m in msgs:  # mentioned users, not just authors — else <@Uxxx> leaks into the digest
                all_uids |= set(MENTION_RE.findall(m["text"]))
            log(f"{ch_name}: {len(msgs)} messages")

    if not channel_msgs:
        log("No activity since last run — no digest sent.")
        if not dry_run:
            STATE_FILE.write_text(json.dumps({"last_run_ts": str(datetime.now().timestamp())}))
        return 0

    name_map = resolve_names(bot_token, all_uids)

    channel_summaries = {}
    for ch_name, msgs in channel_msgs.items():
        log(f"Summarising {ch_name} ({len(msgs)} msgs)...")
        s = summarise_channel(ch_name, msgs, name_map)
        if s:
            channel_summaries[ch_name] = s

    # Don't lie by omission: if channels were active but synthesis produced nothing,
    # that's a Claude/PATH failure under cron — say so, don't send a fake "quiet window".
    if channel_msgs and not channel_summaries:
        log("Synthesis produced 0 summaries for active channels — likely Claude/PATH failure")
        klog_error("intel-digest-synthesis-empty", None, component="intel",
                   active_channels=len(channel_msgs))
        dm = (f"*🕵️ Stealth intel digest — {now_label}*\n\n"
              f"⚠️ {len(channel_msgs)} channels were active but synthesis failed "
              f"(Claude returned nothing — check PATH/nvm under cron at /tmp/varys-intel-digest.log).")
    else:
        top = exec_summary(channel_summaries)
        dm  = build_dm(now_label, channel_summaries, top)

    if dry_run:
        log("DRY RUN — would DM Shoaib the following (NOT sent, nothing posted anywhere):")
        print("\n" + "─" * 60 + "\n" + dm + "\n" + "─" * 60)
        return 0

    ok = _dm_shoaib(bot_token, user_id, dm)
    log("DM sent" if ok else "DM FAILED")

    # Build memory: durable rolling context + people-map upsert (via contained MCP agent).
    _persist_context(channel_summaries, now_label)
    _update_people_map(channel_summaries, name_map, datetime.now().strftime("%Y-%m-%d"), notion_key)

    STATE_FILE.write_text(json.dumps({"last_run_ts": str(datetime.now().timestamp()),
                                      "last_run_label": now_label}))
    klog("intel-digest", component="intel", action="digest",
         channels=len(channel_summaries), dm_ok=ok)
    log("Done.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
