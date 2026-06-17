#!/usr/bin/env python3
"""
varys-gap-watcher.py — Weekly capability gap promoter.

Reads capability_gaps from harness.db. For any gap_type with 2+ occurrences
in the last 7 days that isn't already in CAPABILITIES.md:
  1. Appends it to CAPABILITIES.md under CANNOT DO
  2. DMs Shoaib
  3. If priority score >= 4, creates a Notion Harness ticket

Run: weekly via cron (cron-wrap.sh)
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_config import cfg
try:
    from varys_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

VARYS_DIR       = Path(__file__).parent.parent.parent
CAPABILITIES_MD = VARYS_DIR / ".claude" / "rules" / "CAPABILITIES.md"
SLACK_CFG       = Path.home() / ".claude" / "hooks" / ".slack"
KAMAL_SLACK_ID  = cfg("USER_SLACK_ID", "")


def _load_bot_token() -> str:
    for key in ("SLACK_BOT_TOKEN", "BOT_TOKEN"):
        val = os.environ.get(key)
        if val:
            return val
    if SLACK_CFG.exists():
        for line in SLACK_CFG.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() in ("BOT_TOKEN", "SLACK_BOT_TOKEN"):
                    return v.strip()
    return ""


def _dm_kamal(bot_token: str, text: str) -> None:
    try:
        data = json.dumps({"users": KAMAL_SLACK_ID}).encode()
        req  = urllib.request.Request(
            "https://slack.com/api/conversations.open", data=data,
            headers={"Authorization": f"Bearer {bot_token}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())
        channel = result.get("channel", {}).get("id")
        if not channel:
            return
        data = json.dumps({"channel": channel, "text": text}).encode()
        req  = urllib.request.Request(
            "https://slack.com/api/chat.postMessage", data=data,
            headers={"Authorization": f"Bearer {bot_token}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            pass
    except Exception as e:
        klog_error("gap_watcher_dm_fail", component="gap-watcher", error=str(e))


def _already_in_capabilities(gap_type: str) -> bool:
    if not CAPABILITIES_MD.exists():
        return False
    return gap_type in CAPABILITIES_MD.read_text()


def _append_to_capabilities(gap_type: str, sample_requests: list[str]) -> None:
    samples = "; ".join(sample_requests[:2])
    entry = (
        f"| {gap_type} | Not yet implemented "
        f"(auto-detected from {len(sample_requests)} requests)"
        f" | Tell Shoaib: `@Varys I need {gap_type}` to trigger a build ticket |"
        f"  _(sample: {samples[:100]})_ |\n"
    )
    with open(CAPABILITIES_MD, "a") as f:
        f.write(entry)
    klog("gap_watcher_capabilities_updated", component="gap-watcher", gap_type=gap_type)


def _create_notion_ticket(gap_type: str, count: int, samples: list[str]) -> bool:
    """Create a beads issue to build the missing capability."""
    bd_bin = shutil.which("bd") or str(Path.home() / ".local" / "bin" / "bd")
    desc = f"Auto-detected gap ({count} hits). Samples: {'; '.join(samples[:2])}"
    try:
        r = subprocess.run(
            [bd_bin, "create", f"Build capability: {gap_type}",
             "-t", "task", "-d", desc, "-p", "1"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent.parent), timeout=10,
        )
        return r.returncode == 0
    except Exception as e:
        klog_error("gap_watcher_bd_fail", component="gap-watcher", error=str(e))
        return False


def run() -> None:
    from varys_harness_db import get_db, get_capability_gaps

    db   = get_db()
    gaps = get_capability_gaps(db, days=7, min_count=2)

    if not gaps:
        klog("gap_watcher_no_gaps", component="gap-watcher", action="scan_complete")
        return

    bot_token = _load_bot_token()
    promoted  = []

    for gap in gaps:
        gap_type = gap["gap_type"]
        count    = gap["count"]
        rejected = gap["rejected_count"]
        samples  = gap["sample_requests"]

        if _already_in_capabilities(gap_type):
            continue

        _append_to_capabilities(gap_type, samples)
        promoted.append(gap_type)

        priority       = rejected * 3 + count
        ticket_created = False
        if priority >= 4:
            ticket_created = _create_notion_ticket(gap_type, count, samples)

        if bot_token:
            ticket_line = " Created a Harness ticket to build it." if ticket_created else ""
            try:
                _dm_kamal(bot_token,
                    f"📚 *Capability gap learned:* `{gap_type}`\n"
                    f"Hit {count} times this week ({rejected} rejected).\n"
                    f"Added to my limits in `CAPABILITIES.md`.{ticket_line}\n"
                    f"Want me to start building it? 🤖 Varys")
            except Exception as e:
                klog_error("gap_watcher_dm_outer_fail", component="gap-watcher", error=str(e))

    if promoted:
        klog("gap_watcher_promoted", component="gap-watcher",
             promoted=promoted, count=len(promoted))


if __name__ == "__main__":
    run()
