#!/usr/bin/env python3
"""
kamil-gap-watcher.py — Read capability-gaps.jsonl, auto-propose when a gap hits 3x.

Called at end of every tick (after orchestrator-dispatch).
Reads .beads/capability-gaps.jsonl, counts occurrences per task_type,
DMs Kamal for any gap that has hit 3 occurrences and hasn't been proposed yet.

Proposed gaps are tracked in .beads/capability-gaps-proposed.json to avoid re-proposing.
"""

import json
import os
import sys
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from kamil_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

KAMIL_DIR    = Path(__file__).parent.parent.parent
GAPS_LOG     = KAMIL_DIR / ".beads" / "capability-gaps.jsonl"
PROPOSED_LOG = KAMIL_DIR / ".beads" / "capability-gaps-proposed.json"
SLACK_CFG    = Path.home() / ".claude" / "hooks" / ".slack"
KAMAL_SLACK_ID = "U0AV1DX3WSE"


def _load_bot_token():
    for key in ("SLACK_BOT_TOKEN", "BOT_TOKEN"):
        val = os.environ.get(key)
        if val:
            return val
    if SLACK_CFG.exists():
        for line in SLACK_CFG.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() in ("SLACK_BOT_TOKEN", "BOT_TOKEN"):
                    return v.strip()
    return None


def _dm_kamal(bot_token, text):
    """Open DM channel with Kamal and send a message."""
    data = json.dumps({"users": KAMAL_SLACK_ID}).encode()
    req  = urllib.request.Request(
        "https://slack.com/api/conversations.open",
        data=data,
        headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        result = json.loads(r.read())
    channel = result.get("channel", {}).get("id")
    if not channel:
        return
    data = json.dumps({"channel": channel, "text": text}).encode()
    req  = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=data,
        headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=10)


def main():
    if not GAPS_LOG.exists():
        print("[gap-watcher] No gaps log — skipping")
        return 0

    bot_token = _load_bot_token()
    proposed  = json.loads(PROPOSED_LOG.read_text()) if PROPOSED_LOG.exists() else {}

    gaps = []
    for line in GAPS_LOG.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                gaps.append(json.loads(line))
            except Exception:
                pass

    if not gaps:
        return 0

    counts = Counter(g["task_type"] for g in gaps)
    proposed_this_run = 0

    for task_type, count in counts.items():
        if count >= 3 and task_type not in proposed:
            latest = next((g for g in reversed(gaps) if g["task_type"] == task_type), {})
            msg = (
                f"⚡ *Capability Gap Proposal*\n"
                f"I've hit the same gap *{count} times* now:\n"
                f"• Task type: `{task_type}`\n"
                f"• What was missing: {latest.get('what_was_missing', 'unknown')[:200]}\n"
                f"• How I handled it: {latest.get('how_handled', 'improvised')[:150]}\n\n"
                f"Want me to build a dedicated agent/skill for this? Reply `yes build it` to proceed.\n"
                f"🤖 Kamil"
            )
            if bot_token:
                try:
                    _dm_kamal(bot_token, msg)
                    proposed[task_type] = {
                        "count": count,
                        "proposed_at": str(GAPS_LOG.stat().st_mtime),
                    }
                    proposed_this_run += 1
                    klog("gap-proposal-sent", component="gap-watcher",
                         task_type=task_type, count=count)
                except Exception as e:
                    klog_error("gap-proposal-dm", e)

    if proposed_this_run > 0:
        PROPOSED_LOG.write_text(json.dumps(proposed, indent=2))

    print(f"[gap-watcher] {proposed_this_run} new gap proposals sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
