#!/usr/bin/env python3
"""
Region Friction Coach — infers which teammate is blocked/stuck/lacking across
#region-punjab + #regionpunjab-internal (overlapping members, analysed together),
grounds each finding in the actual thread + repo code, and composes ONE message
that @-mentions each affected person with a concrete suggested unblock.

SAFETY: by default this only DMs Shoaib a PREVIEW of what it would post. It posts
to #regionpunjab-internal for real ONLY with --post (or REGION_COACH_AUTOPOST=1).
A bot publicly coaching named people is irreversible — preview-first until trusted.

Reuses the stealth digest's primitives (slack_get, resolve_names, sub_mentions,
run_claude, _extract_json) by loading it as a module — no reimplementation.

Usage:
  python3 region-friction-coach.py                 # analyse last 24h, DM Shoaib a preview
  python3 region-friction-coach.py --hours 48      # custom lookback
  python3 region-friction-coach.py --post          # also post to #regionpunjab-internal
"""
import importlib.util
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

HOOKS = Path(__file__).parent
sys.path.insert(0, str(HOOKS))

# Reuse the digest's primitives instead of duplicating them.
_spec = importlib.util.spec_from_file_location("intel_digest", HOOKS / "slack-intel-digest.py")
_d = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_d)
slack_get, resolve_names, sub_mentions = _d.slack_get, _d.resolve_names, _d.sub_mentions
run_claude, _extract_json, load_config = _d.run_claude, _d._extract_json, _d.load_config
SLACK_CONFIG = _d.SLACK_CONFIG

CHANNELS = ["region-punjab", "regionpunjab-internal"]
POST_CHANNEL = "regionpunjab-internal"          # where findings land (bot is a member)
REPO_HINT = "/home/shoaib/varys/repos/compliancetracker"   # Punjab work is ComplianceTracker
MIN_CONFIDENCE = 60
MAX_PEOPLE = 6
MAX_THREAD_REPLIES = 50


def log(msg):
    print(f"[friction-coach] {msg}", file=sys.stderr)


def resolve_channel_ids(token, names):
    """Map channel names → ids across public + private (bot's memberships)."""
    want, found, cursor = {n.lstrip("#") for n in names}, {}, None
    while want:
        params = {"types": "public_channel,private_channel", "exclude_archived": "true", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        r = slack_get(token, "conversations.list", params)
        if not r.get("ok"):
            log(f"conversations.list: {r.get('error')}")
            break
        for c in r.get("channels", []):
            if c.get("name") in want:
                found[c["name"]] = c["id"]
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return found


def sweep_with_threads(token, ch_id, ch_name, since_ts, fallback=None):
    """History since `since_ts` WITH thread replies inlined (threads are where blockers unfold).
    Tries `token` (user token reads public channels unjoined); falls back to bot token for private."""
    msgs, cursor, tried_fb = [], None, False
    while True:
        params = {"channel": ch_id, "oldest": since_ts, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        r = slack_get(token, "conversations.history", params)
        if not r.get("ok"):
            err = r.get("error", "")
            if fallback and not tried_fb and err in ("not_in_channel", "channel_not_found", "missing_scope"):
                token, tried_fb = fallback, True
                continue
            if err not in ("", "not_in_channel"):
                log(f"{ch_name}: {err or 'unknown'}")
            break
        for m in r.get("messages", []):
            if m.get("text"):
                msgs.append(m)
            if m.get("reply_count", 0) and m.get("thread_ts"):
                rr = slack_get(token, "conversations.replies",
                               {"channel": ch_id, "ts": m["thread_ts"], "limit": MAX_THREAD_REPLIES})
                for rm in rr.get("messages", [])[1:]:   # [0] is the parent, already added
                    if rm.get("text"):
                        msgs.append(rm)
                time.sleep(0.2)
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return msgs


def msg_author(m):
    if m.get("user"):
        return m["user"]
    return ""


def build_transcript(channel_msgs, name_map):
    """One readable, time-ordered transcript across both channels, mentions resolved."""
    out = []
    for ch_name, msgs in channel_msgs.items():
        out.append(f"\n===== #{ch_name} =====")
        for m in sorted(msgs, key=lambda x: x.get("ts", "")):
            uid = msg_author(m)
            who = name_map.get(uid, uid) if uid else \
                ((m.get("bot_profile") or {}).get("name") or m.get("username") or "bot")
            out.append(f"{who}: {sub_mentions(m.get('text', ''), name_map)[:500]}")
    return "\n".join(out)


VARYS_VOICE = """Write as VARYS — Master of Whisperers. Measured, precise, soft-spoken but pointed.
Lead with the fact, never flatter ("Great work!" is beneath him), never pad. Dry wit only if it
lands naturally — the joke is in the understatement, never forced, never slapstick. Address the
person plainly and with respect; you are easing their load, not scolding them. No corporate
HR-speak, no exclamation marks. For an INCIDENT or data-loss finding, drop the wit entirely —
blunt, specific, forward-looking, never blaming. The closing line is a quiet, concrete offer."""


def _solution_policy(user_id):
    return f"""Tailor the relief to WHO the person is — this is not optional:
- SHOAIB (slack_id = {user_id}) is the king Varys serves. ONLY for him may you offer to take the
  work on directly — "leave it with me", "pass it to me". Varys does that chore himself.
- EVERYONE ELSE: Varys does NOT do their job for them. He hands them leverage they own and run.
  Offer a concrete tool, automation, or process THAT PERSON operates. Never "Varys will do it".

Relief patterns for non-Shoaib people, by friction type:
- Drowning in PR-review pings (or "I've reviewed everything and am still pinged") → propose they
  stand up a RULE-BASED auto first-pass reviewer they own: define the review rules once, have it
  listen to GitHub (or Slack) for new PRs, auto-run the first pass — APPROVE if clean, otherwise
  post inline comments on the exact lines for the author to fix. They then only see PRs a human
  must actually judge. This is the relief for review overload.
- Caused or hit an INCIDENT / regression / DATA issue (rows overwritten or deleted, migration not
  applied, prod broke) → not blame: a SAFEGUARD so it cannot recur — a guard that refuses to
  overwrite non-null fields, a dry-run + backup before bulk writes, an idempotency/confirm step.
  Ground it in the actual repo file/route.
- Genuinely blocked waiting on a person/decision → name exactly who or what unblocks them."""


def analyze(transcript, roster, user_id):
    prompt = f"""You are VARYS, Shoaib's agent, reviewing the last 24h of two overlapping Slack
channels for the Punjab region team at Taleemabad (EdTech). Be EXHAUSTIVE, not conservative —
surface EVERY team member with real friction this window (up to 6), not just the obvious one or two.

Friction includes, and is NOT limited to:
1. BLOCKED / WAITING — stuck on a review, reply, decision, or access.
2. OVERLOADED — repeatedly tagged for the same work, especially PR reviews. MANY review-request
   messages from or to one person, or someone saying they've done "all the reviews" yet keep being
   pinged, IS overload. Catch it even though they never said the word "blocked".
3. INCIDENT / REGRESSION — someone shipped or merged a change that caused a problem (data
   overwritten or deleted, a migration not applied, prod broke). They are not "stuck", but this is
   real friction and they need a safeguard. CATCH THESE — e.g. a user-management merge that
   overwrites 40 users' contact numbers is exactly this category.
4. CONFUSED / GOING IN CIRCLES — repeating an ask, can't pin a bug, missing context.

{_solution_policy(user_id)}

{VARYS_VOICE}

For EACH genuinely-stuck person, investigate the root cause before suggesting anything.
Most of this work is the ComplianceTracker app. You MAY read its code to ground your suggestion:
  {REPO_HINT}
Use Read/Grep/Glob/Bash (read-only) to find the actual file, query, route, or schema involved.
A suggestion that names a real file/function/PR/command beats generic advice ("pair up", "escalate").

ROSTER (use the EXACT slack_id for each person):
{roster}

TRANSCRIPT:
{transcript}

Return ONLY a JSON object, no other text:
{{
  "affected": [
    {{
      "name": "display name",
      "slack_id": "U... (exact, from roster)",
      "friction": "one sentence in Varys's voice: what they're actually stuck on or buried under",
      "root_cause": "the underlying cause you found (cite a file/PR/line if you grounded it) — plain, for Shoaib's eyes",
      "suggested_solution": "in VARYS's voice: a concrete, specific offer of relief they can act on. Posted publicly tagging them — measured, respectful, no blame, no exclamation marks, 1-3 sentences. If they're overloaded, offer Varys taking the first review pass.",
      "confidence": 0-100,
      "evidence": "the message(s)/thread that show the friction"
    }}
  ]
}}
Only include a person if you are >= {MIN_CONFIDENCE} confident they are genuinely stuck AND you have
a specific solution. If nobody is genuinely stuck, return {{"affected": []}}."""
    raw = run_claude(prompt, timeout=600)
    try:
        (Path.home() / ".varys-harness" / "friction-coach-raw.txt").write_text(raw or "<EMPTY>")
    except Exception:
        pass
    parsed = _extract_json(raw)
    return parsed or {"affected": []}


def compose_message(affected, day_label):
    lines = [
        f"*A few whispers from the Punjab channels — {day_label}*",
        "My little birds noticed some of you carrying more than you should. "
        "Not a nudge to do more — an offer to make the load lighter. Ignore any that miss the mark.",
        "",
    ]
    for p in affected:
        mention = f"<@{p['slack_id']}>" if str(p.get("slack_id", "")).startswith(("U", "W")) else p.get("name", "someone")
        lines.append(f"{mention} — {p['friction'].strip()}")
        lines.append(f"   _{p['suggested_solution'].strip()}_")
        lines.append("")
    lines.append("— Varys 🕷️")
    return "\n".join(lines).rstrip()


def post_message(bot_token, channel_id, text):
    data = json.dumps({"channel": channel_id, "text": text, "unfurl_links": False}).encode()
    req = urllib.request.Request("https://slack.com/api/chat.postMessage", data=data,
        headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read())
        if not res.get("ok"):
            log(f"post failed: {res.get('error')}")
        return bool(res.get("ok"))
    except Exception as e:
        log(f"post failed: {e}")
        return False


def main():
    hours = 24
    if "--hours" in sys.argv:
        hours = int(sys.argv[sys.argv.index("--hours") + 1])
    do_post = "--post" in sys.argv or os.environ.get("REGION_COACH_AUTOPOST") == "1"

    cfg = load_config(SLACK_CONFIG)
    bot_token = cfg.get("BOT_TOKEN") or os.environ.get("SLACK_BOT_TOKEN")
    user_token = cfg.get("SLACK_USER_TOKEN") or os.environ.get("SLACK_USER_TOKEN")
    user_id = os.environ.get("USER_SLACK_ID") or _d.cfg("USER_SLACK_ID", "")
    if not bot_token or not user_id:
        log("FATAL: missing BOT_TOKEN or USER_SLACK_ID")
        return 1

    since_ts = str((datetime.now() - timedelta(hours=hours)).timestamp())
    day_label = datetime.now().strftime("%a %d %b")
    chan_ids = resolve_channel_ids(bot_token, CHANNELS)
    log(f"channels: {chan_ids}")

    channel_msgs, all_uids = {}, set()
    for name in CHANNELS:
        cid = chan_ids.get(name)
        if not cid:
            log(f"channel #{name} not found / bot not in it — skipping")
            continue
        msgs = sweep_with_threads(user_token or bot_token, cid, name, since_ts, fallback=bot_token)
        channel_msgs[name] = msgs
        for m in msgs:
            if m.get("user"):
                all_uids.add(m["user"])
            all_uids |= set(_d.MENTION_RE.findall(m.get("text", "")))
        log(f"#{name}: {len(msgs)} messages (incl. thread replies)")

    if not any(channel_msgs.values()):
        log("no activity in window — nothing to coach")
        return 0

    name_map = resolve_names(bot_token, all_uids)
    transcript = build_transcript(channel_msgs, name_map)
    roster = "\n".join(f"- {nm} → {uid}" for uid, nm in sorted(name_map.items(), key=lambda x: x[1]))

    log("analysing (deep, repo-grounded)...")
    result = analyze(transcript, roster, user_id)
    affected = [p for p in result.get("affected", [])
                if p.get("suggested_solution") and int(p.get("confidence", 0)) >= MIN_CONFIDENCE][:MAX_PEOPLE]

    if not affected:
        _d._dm_shoaib(bot_token, user_id,
                      f"*Punjab channels — {day_label}*\nThe channels are calm. My little birds found "
                      f"no one truly stuck over the last {hours}h. — Varys 🕷️")
        log("no confident frictions — sent 'all clear' DM")
        return 0

    channel_text = compose_message(affected, day_label)
    try:  # durable audit trail of the last run (for review / debugging)
        (Path.home() / ".varys-harness" / "friction-coach-last.json").write_text(
            json.dumps({"at": day_label, "hours": hours, "affected": affected,
                        "message": channel_text}, indent=1))
    except Exception:
        pass

    if do_post:
        ok = post_message(bot_token, chan_ids[POST_CHANNEL], channel_text)
        _d._dm_shoaib(bot_token, user_id,
                      f"{'✅ Posted to' if ok else '⚠️ FAILED to post to'} #{POST_CHANNEL}:\n\n{channel_text}")
        log(f"posted to channel: {ok}")
    else:
        detail = "\n".join(
            f"• *{p['name']}* (conf {p.get('confidence')}): {p.get('root_cause', '').strip()}\n   evidence: {p.get('evidence', '').strip()[:200]}"
            for p in affected)
        preview = (
            f"*🧭 Region Friction Coach — PREVIEW (not posted)*\n"
            f"Would post the message below to #{POST_CHANNEL}. Re-run with `--post` "
            f"(or set REGION_COACH_AUTOPOST=1) to send it for real.\n"
            f"\n*Why each (your eyes only):*\n{detail}\n"
            f"\n———  message that would post  ———\n{channel_text}")
        _d._dm_shoaib(bot_token, user_id, preview)
        log(f"DM'd preview of {len(affected)} findings to Shoaib")
    return 0


if __name__ == "__main__":
    sys.exit(main())
