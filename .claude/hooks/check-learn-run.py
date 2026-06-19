#!/usr/bin/env python3
"""
check-learn-run.py — Watchdog for the nightly varys-learn.sh self-improvement run.

The 2am varys-learn cron DMs Shoaib its confidence report on success. This watchdog
runs a few hours later and pings Shoaib ONLY when that run is missing, crashed, or
completed with warnings — so a silent failure of the daily loop never goes unnoticed
("nothing silently rots", orchestrator.md). On a clean run it stays quiet.

Cron (8am, after the 2am run): 0 8 * * * cd ~/varys && .claude/hooks/cron-wrap.sh check-learn-run python3 .claude/hooks/check-learn-run.py
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_config import cfg
try:
    from varys_log import klog
except Exception:
    klog = lambda *a, **kw: None

LOG_FILE   = Path("/tmp/varys-learn.log")
SLACK_CFG  = Path.home() / ".claude" / "hooks" / ".slack"
MAX_AGE_H  = 10  # 2am run checked at ~8am → ~6h; >10h means it didn't run


def _bot_token() -> str:
    for key in ("SLACK_BOT_TOKEN", "BOT_TOKEN"):
        if os.environ.get(key):
            return os.environ[key]
    if SLACK_CFG.exists():
        for line in SLACK_CFG.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() in ("BOT_TOKEN", "SLACK_BOT_TOKEN"):
                    return v.strip()
    return ""


def _dm(token: str, user_id: str, text: str) -> bool:
    """Open Shoaib's DM and post. Refuses any non-DM channel (stealth guarantee)."""
    try:
        req = urllib.request.Request(
            "https://slack.com/api/conversations.open",
            data=json.dumps({"users": user_id}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            opened = json.loads(r.read())
        dm_ch = (opened.get("channel") or {}).get("id", "")
        if not opened.get("ok") or not dm_ch.startswith("D"):
            return False
        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=json.dumps({"channel": dm_ch, "text": text}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return bool(json.loads(r.read()).get("ok"))
    except Exception:
        return False


def _latest_run_block(text: str) -> str:
    """The log is appended across runs; return the slice from the last 'Starting at'."""
    idx = text.rfind("[varys-learn] Starting at")
    return text[idx:] if idx >= 0 else text


def assess() -> tuple[str, str]:
    """Return (severity, message). severity: 'ok' | 'warn' | 'fail'."""
    if not LOG_FILE.exists():
        return "fail", "nightly self-improvement run NEVER ran — /tmp/varys-learn.log does not exist."
    age_h = (time.time() - LOG_FILE.stat().st_mtime) / 3600
    if age_h > MAX_AGE_H:
        return "fail", (f"nightly self-improvement run DID NOT RUN — varys-learn.log "
                        f"last touched {age_h:.0f}h ago (expected the 2am cron).")
    block = _latest_run_block(LOG_FILE.read_text())
    if "[varys-learn] Done at" not in block:
        tail = "\n".join(block.strip().splitlines()[-6:])
        return "fail", f"nightly run started but did NOT complete (no 'Done at'). Tail:\n```{tail}```"
    warns = [l for l in block.splitlines() if "WARN" in l or "FATAL" in l]
    if warns:
        return "warn", "nightly run completed WITH warnings:\n```" + "\n".join(warns[-5:]) + "```"
    return "ok", ""


def main() -> int:
    sev, msg = assess()
    klog("learn-watchdog", component="check-learn-run", severity=sev, detail=msg[:200])
    if sev == "ok":
        print("[check-learn-run] nightly run OK — staying quiet.")
        return 0
    token   = _bot_token()
    user_id = cfg("USER_SLACK_ID", "")
    icon    = "⚠️" if sev == "warn" else "🔴"
    text    = f"{icon} *Nightly self-improvement watchdog*\n{msg}\n🕷️ Varys"
    if token and user_id and _dm(token, user_id, text):
        print(f"[check-learn-run] {sev}: DMed Shoaib.")
    else:
        print(f"[check-learn-run] {sev}: {msg} (DM not sent — missing token/user or send failed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
