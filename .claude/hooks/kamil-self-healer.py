#!/usr/bin/env python3
"""
kamil-self-healer.py — Kamil's immune system.

Runs every 10 minutes via cron. Checks all critical Kamil services,
reads their logs, detects errors, and uses Claude to diagnose + fix.

Services monitored:
  - kamil-slack-listener.py  (Socket Mode daemon)
  - slack-poller.py          (30-min Slack reader)

On error/crash:
  1. Read logs for root cause
  2. Call Claude with full context: logs + source code
  3. Claude patches the file and restarts the service
  4. DM Kamal on Slack: "🔧 Self-healed: [what broke] → [what was fixed]"

On healthy:
  - Just logs a heartbeat line, no DM (no noise)
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_health import log_error, log_healed, log_needs_manual, log_health

KAMIL_DIR   = Path(__file__).parent.parent.parent
HOOKS_DIR   = Path(__file__).parent
SLACK_CFG   = Path.home() / ".claude" / "hooks" / ".slack"
HEAL_LOG    = Path("/tmp/kamil-self-healer.log")
KAMAL_DM    = "D0B415M06SK"

SERVICES = [
    {
        "name": "kamil-slack-listener",
        "script": str(HOOKS_DIR / "kamil-slack-listener.py"),
        "log": "/tmp/kamil-slack-listener.log",
        "pid_file": "/tmp/kamil-slack-listener.pid",
        "start_cmd": f"cd {KAMIL_DIR} && python3 .claude/hooks/kamil-slack-listener.py >> /tmp/kamil-slack-listener.log 2>&1 &",
        "check_process": "kamil-slack-listener.py",
    },
    {
        "name": "slack-poller",
        "script": str(HOOKS_DIR / "slack-poller.py"),
        "log": "/tmp/kamil-slack-poller.log",
        "pid_file": None,
        "start_cmd": None,  # poller is cron-driven, not a daemon
        "check_process": None,
    },
]

# Error patterns that signal a real problem (not just noise)
ERROR_PATTERNS = [
    r"Traceback \(most recent call last\)",
    r"Error:",
    r"Exception:",
    r"CRITICAL",
    r"socket\.error",
    r"ConnectionError",
    r"SlackApiError",
    r"JSONDecodeError",
    r"PermissionError",
    r"FileNotFoundError",
]

ERROR_RE = re.compile("|".join(ERROR_PATTERNS), re.IGNORECASE)


def log(msg: str):
    ts   = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(HEAL_LOG, "a") as f:
        f.write(line + "\n")


def load_slack_token() -> str | None:
    if not SLACK_CFG.exists():
        return None
    for line in SLACK_CFG.read_text().splitlines():
        line = line.strip()
        if line.startswith("BOT_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def slack_dm(token: str, text: str):
    subprocess.run([
        "curl", "-s", "-X", "POST",
        "https://slack.com/api/chat.postMessage",
        "-H", f"Authorization: Bearer {token}",
        "-H", "Content-Type: application/json",
        "-d", json.dumps({"channel": KAMAL_DM, "text": text}),
    ], capture_output=True)


def read_log_tail(log_path: str, lines: int = 80) -> str:
    p = Path(log_path)
    if not p.exists():
        return "(no log file)"
    try:
        result = subprocess.run(["tail", "-n", str(lines), log_path],
                                 capture_output=True, text=True)
        return result.stdout
    except Exception as e:
        return f"(error reading log: {e})"


def extract_errors(log_tail: str) -> list[str]:
    """Return lines near each error pattern (context window ±3 lines)."""
    lines = log_tail.splitlines()
    error_lines = []
    for i, line in enumerate(lines):
        if ERROR_RE.search(line):
            start = max(0, i - 3)
            end   = min(len(lines), i + 4)
            block = "\n".join(lines[start:end])
            if block not in error_lines:
                error_lines.append(block)
    return error_lines


def is_process_running(name: str) -> bool:
    result = subprocess.run(["pgrep", "-f", name], capture_output=True)
    return result.returncode == 0


def get_pid_from_file(pid_file: str) -> int | None:
    p = Path(pid_file)
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except Exception:
        return None


def kill_process(name: str):
    subprocess.run(["pkill", "-f", name], capture_output=True)
    time.sleep(1)


def start_service(start_cmd: str):
    subprocess.Popen(
        ["bash", "-c", start_cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(3)


def run_claude(prompt: str, timeout: int = 180) -> str:
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    env = os.environ.copy()
    env["KAMIL_PROMPT"] = prompt
    try:
        result = subprocess.run(
            ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$KAMIL_PROMPT"'],
            capture_output=True, text=True,
            cwd=str(KAMIL_DIR),
            timeout=timeout, env=env,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return f"claude error: {result.stderr.strip()[:200]}"
    except subprocess.TimeoutExpired:
        return "claude timeout"
    except Exception as e:
        return f"claude exception: {e}"


def diagnose_and_fix(service: dict, error_blocks: list[str]) -> str:
    """
    Ask Claude to read the error, understand the source, patch the file.
    Returns a human-readable summary of what was done.
    """
    errors_text = "\n\n---\n".join(error_blocks[:5])  # top 5 error blocks
    script_path = service["script"]

    try:
        source = Path(script_path).read_text()
    except Exception as e:
        source = f"(could not read source: {e})"

    prompt = f"""You are Kamil's self-healing system. A critical service has errors.

## SERVICE
File: {script_path}

## ERRORS FROM LOG (last 80 lines)
{errors_text}

## SOURCE CODE
```python
{source[:6000]}
```

## YOUR JOB
1. Diagnose the root cause (one sentence)
2. Write the minimal fix — edit {script_path} in place using the Edit tool or Write tool
3. Do NOT break existing functionality
4. After fixing, reply with this exact format:
   ROOT_CAUSE: <one sentence>
   FIX: <one sentence describing what you changed>
   STATUS: fixed

If you cannot determine a safe fix, reply:
   ROOT_CAUSE: <one sentence>
   FIX: none — needs manual review
   STATUS: unresolved

Fix it now."""

    log(f"Calling Claude to diagnose {service['name']}...")
    result = run_claude(prompt, timeout=180)
    log(f"Claude response: {result[:200]}")
    return result


def check_service(service: dict, token: str | None) -> bool:
    """
    Check one service. Returns True if healthy, False if there was a problem.
    """
    name = service["name"]
    log_path = service["log"]
    check_proc = service.get("check_process")

    # 1. Check if process is running (for daemons only)
    if check_proc:
        running = is_process_running(check_proc)
        if not running:
            log(f"⚠️  {name} is NOT running — restarting")
            log_error(service=name, error=f"{name} process not found — was down", context="process check")
            if service.get("start_cmd"):
                start_service(service["start_cmd"])
                time.sleep(3)
                if is_process_running(check_proc):
                    msg = f"🔧 *Kamil self-healed*: `{name}` was down → restarted successfully"
                    log(f"Restart OK for {name}")
                    log_healed(service=name, root_cause="process was not running", fix="restarted via start_cmd")
                    if token:
                        slack_dm(token, msg)
                    return False
                else:
                    msg = f"⚠️ *Kamil self-heal FAILED*: `{name}` won't start — check logs at `{log_path}`"
                    log(f"Restart FAILED for {name}")
                    if token:
                        slack_dm(token, msg)
                    return False

    # 2. Check logs for recent errors (last 15 minutes)
    log_tail = read_log_tail(log_path, lines=80)
    error_blocks = extract_errors(log_tail)

    # Only consider errors from the last 15 minutes
    # (rough filter: look for recent timestamp patterns)
    recent_errors = []
    now = datetime.now()
    for block in error_blocks:
        # Extract timestamps like [HH:MM:SS] from blocks
        ts_matches = re.findall(r'\[(\d{2}:\d{2}:\d{2})\]', block)
        if ts_matches:
            for ts_str in ts_matches:
                try:
                    ts = datetime.strptime(ts_str, "%H:%M:%S").replace(
                        year=now.year, month=now.month, day=now.day
                    )
                    if (now - ts).total_seconds() < 900:  # 15 min
                        recent_errors.append(block)
                        break
                except Exception:
                    pass
        else:
            # No timestamp — include it (conservative)
            recent_errors.append(block)

    if not recent_errors:
        log(f"✅ {name}: healthy")
        return True

    log(f"🔴 {name}: found {len(recent_errors)} error block(s) in recent logs")
    # Log detection to Notion immediately
    log_error(service=name,
              error="\n".join(recent_errors[:2])[:500],
              context=f"Found {len(recent_errors)} error block(s) in last 15 min of logs")

    # 3. Call Claude to diagnose and fix
    claude_result = diagnose_and_fix(service, recent_errors)

    # Parse Claude's response
    root_cause = "unknown"
    fix_desc   = "unknown"
    status     = "unknown"

    for line in claude_result.splitlines():
        if line.startswith("ROOT_CAUSE:"):
            root_cause = line.split(":", 1)[1].strip()
        elif line.startswith("FIX:"):
            fix_desc = line.split(":", 1)[1].strip()
        elif line.startswith("STATUS:"):
            status = line.split(":", 1)[1].strip()

    if status == "fixed" and check_proc and service.get("start_cmd"):
        # Restart service after fix
        log(f"Fix applied — restarting {name}")
        kill_process(check_proc)
        time.sleep(2)
        start_service(service["start_cmd"])
        time.sleep(3)
        restarted = is_process_running(check_proc)
        restart_note = "restarted ✅" if restarted else "restart FAILED ⚠️"
        log_healed(service=name, root_cause=root_cause, fix=fix_desc)

        msg = (
            f"🔧 *Kamil self-healed*: `{name}`\n"
            f"• *Root cause:* {root_cause}\n"
            f"• *Fix:* {fix_desc}\n"
            f"• *Service:* {restart_note}"
        )
    else:
        log_needs_manual(service=name, root_cause=root_cause, attempted=fix_desc)
        msg = (
            f"⚠️ *Kamil found errors in `{name}` but could not auto-fix*\n"
            f"• *Root cause:* {root_cause}\n"
            f"• *Attempted fix:* {fix_desc}\n"
            f"• *Status:* {status}\n"
            f"• Check logs: `{log_path}`"
        )

    log(f"Slack DM: {msg[:120]}")
    if token:
        slack_dm(token, msg)
    return False


def check_healer_log_size():
    """Rotate heal log if >500KB."""
    if HEAL_LOG.exists() and HEAL_LOG.stat().st_size > 500_000:
        HEAL_LOG.rename(HEAL_LOG.with_suffix(".log.bak"))
        log("Rotated heal log")


def main():
    check_healer_log_size()
    log("=== Self-healer run ===")

    token = load_slack_token()
    if not token:
        log("No Slack token — DM alerts disabled")

    all_healthy = True
    for service in SERVICES:
        try:
            healthy = check_service(service, token)
            if not healthy:
                all_healthy = False
        except Exception as e:
            log(f"Healer error checking {service['name']}: {e}")

    if all_healthy:
        log("All services healthy.")
    else:
        log("Done — issues found and handled above.")


if __name__ == "__main__":
    main()
