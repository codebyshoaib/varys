#!/usr/bin/env python3
"""Morning nudge: remind Shoaib to run his daily interview/eng-sync drill.

The drill itself (interview-drill skill) needs him present to answer OUT LOUD, so
this only nudges — it never "completes" a drill he didn't do. Surfaces his weakest
logged topics so the reminder is concrete, not generic.
"""
import importlib.util
import json
import os
import urllib.request
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
DRILL_DIR = Path.home() / ".claude" / "interview-drill"

# Reuse the Slack config plumbing the other hooks share.
_spec = importlib.util.spec_from_file_location("intel_digest", HOOKS / "slack-intel-digest.py")
_d = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_d)


def post_message(bot_token, channel_id, text):
    data = json.dumps({"channel": channel_id, "text": text, "unfurl_links": False}).encode()
    req = urllib.request.Request("https://slack.com/api/chat.postMessage", data=data,
        headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read()).get("ok", False)


def weak_topics(limit=2):
    """Most-recent distinct topics scored <=3 in the log. Defensive: [] if no/bad log."""
    log = DRILL_DIR / "log.jsonl"
    if not log.exists():
        return []
    weak = OrderedDict()  # topic -> keeps newest by overwrite, we read oldest->newest
    for line in log.read_text().splitlines():
        try:
            rec = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(rec, dict) and rec.get("score", 5) <= 3 and rec.get("topic"):
            weak[rec["topic"]] = True
            weak.move_to_end(rec["topic"])
    return list(weak)[-limit:][::-1]


def main():
    cfg = _d.load_config(_d.SLACK_CONFIG)
    bot_token = cfg.get("BOT_TOKEN") or os.environ.get("SLACK_BOT_TOKEN")
    user_id = os.environ.get("USER_SLACK_ID") or _d.cfg("USER_SLACK_ID", "")
    if not bot_token or not user_id:
        print("FATAL: missing BOT_TOKEN or USER_SLACK_ID")
        return 1

    weak = weak_topics()
    focus = f"\n\nDue for review: *{'*, *'.join(weak)}*." if weak else ""
    day = datetime.now().strftime("%a %d %b")
    msg = (
        f"🕷️ *Morning, {day} — your daily rep is ready.*{focus}\n\n"
        "Run `/interview-drill` when you can *speak out loud* (15 min). "
        "Answer each one aloud first, then type — the out-loud part is the training. "
        "Ends with a 30-second eng-sync rehearsal.\n\n"
        "_Skip a day and the streak resets. Small reps beat cramming._"
    )
    ok = post_message(bot_token, user_id, msg)
    print("nudge sent" if ok else "nudge FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
