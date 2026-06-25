#!/usr/bin/env python3
"""
varys-self-healer.py — Varys's immune system.

Runs every 10 minutes via cron. Checks all critical Varys services,
reads their logs, detects errors, and uses Claude to diagnose + fix.

Services monitored:
  - varys-slack-listener.py  (Socket Mode daemon)
  - slack-poller.py          (30-min Slack reader)

On error/crash:
  1. Read logs for root cause
  2. Call Claude with full context: logs + source code
  3. Claude patches the file and restarts the service
  4. DM Shoaib on Slack: "🔧 Self-healed: [what broke] → [what was fixed]"

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
from varys_health import log_error, log_healed, log_needs_manual, log_health
from varys_eval_tracker import eval_self_heal
from varys_log import klog, klog_error

VARYS_DIR   = Path(__file__).parent.parent.parent
HOOKS_DIR   = Path(__file__).parent
SLACK_CFG   = Path.home() / ".claude" / "hooks" / ".slack"
HEAL_LOG    = Path("/tmp/varys-self-healer.log")
HEAL_STATE  = Path("/tmp/varys-healer-state.json")
HANDLED_LEDGER = Path("/tmp/varys-healer-handled.txt")  # dedup: errors already escalated
SHOAIB_DM    = os.environ.get("USER_SLACK_DM", "")  # set USER_SLACK_DM in ~/.agent-config.json

SERVICES = [
    {
        "name": "varys-slack-listener",
        "script": str(HOOKS_DIR / "varys-slack-listener.py"),
        "log": "/tmp/varys-slack-listener.log",
        "pid_file": "/tmp/varys-slack-listener.pid",
        # Heal THROUGH systemd (the unit owns this daemon: Restart=always) — never spawn a raw
        # process, which would race systemd and create a second, unmanaged listener. `restart`
        # is idempotent (starts if stopped). XDG_RUNTIME_DIR is needed for `systemctl --user`
        # from cron/headless contexts where the user DBus session isn't auto-exported.
        "start_cmd": "XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user restart varys-slack-listener.service",
        "check_process": "varys-slack-listener.py",
    },
    {
        "name": "slack-poller",
        "script": str(HOOKS_DIR / "slack-poller.py"),
        "log": "/tmp/varys-slack-poller.log",
        "pid_file": None,
        "start_cmd": None,  # poller is cron-driven, not a daemon
        "check_process": None,
    },
    {
        "name": "content-scheduler",
        "script": str(HOOKS_DIR / "content-scheduler.py"),
        "log": "/tmp/varys-content.log",
        "pid_file": None,
        "start_cmd": None,  # cron-driven, not a daemon
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
        "-d", json.dumps({"channel": SHOAIB_DM, "text": text}),
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
    # pgrep -f matches against full cmdlines, which can include THIS checker's own
    # process (and any cron-wrap/claude -p invocation that mentions the name) — a
    # self-match that produced false "down" alerts. Exclude our own PID, the parent
    # shell, and anything that is not a real python interpreter running the script.
    import os
    result = subprocess.run(["pgrep", "-af", name], capture_output=True, text=True)
    if result.returncode != 0:
        return False
    self_pids = {str(os.getpid()), str(os.getppid())}
    for line in result.stdout.splitlines():
        pid = line.split(maxsplit=1)[0] if line.strip() else ""
        if pid in self_pids:
            continue
        # require an actual interpreter running the script, not a shell/grep/wrapper
        if "python" in line and name in line:
            return True
    return False


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
    env["VARYS_PROMPT"] = prompt
    try:
        result = subprocess.run(
            ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$VARYS_PROMPT"'],
            capture_output=True, text=True,
            cwd=str(VARYS_DIR),
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

    prompt = f"""You are Varys's self-healing system. A critical service has errors.

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
        # State-change-only alerting + cooldown: only restart/DM when the service
        # TRANSITIONS up→down. Persisting "last_up" avoids flapping a "down→restarted"
        # DM every single 10-min cycle (the prior false-positive spam).
        pstate = {}
        if HEAL_STATE.exists():
            try: pstate = json.loads(HEAL_STATE.read_text())
            except Exception: pstate = {}
        svc_state = pstate.get(name, {})
        last_restart_at = svc_state.get("last_restart_at")
        if not running:
            # cooldown: don't re-restart/re-DM within 30 min of a prior restart
            recently_restarted = False
            if last_restart_at:
                try:
                    age_m = (datetime.utcnow() - datetime.fromisoformat(last_restart_at)).total_seconds() / 60
                    recently_restarted = age_m < 30
                except Exception:
                    recently_restarted = False
            if recently_restarted:
                log(f"{name} down but restarted <30m ago — cooldown, not re-alerting")
                return False
            log(f"⚠️  {name} is NOT running — restarting (first detection)")
            log_error(service=name, error=f"{name} process not found — was down", context="process check")
            if service.get("start_cmd"):
                start_service(service["start_cmd"])
                time.sleep(3)
                if is_process_running(check_proc):
                    svc_state["last_restart_at"] = datetime.utcnow().isoformat()
                    pstate[name] = svc_state
                    HEAL_STATE.write_text(json.dumps(pstate))
                    msg = f"🔧 *Varys self-healed*: `{name}` was down → restarted successfully"
                    log(f"Restart OK for {name}")
                    log_healed(service=name, root_cause="process was not running", fix="restarted via start_cmd")
                    if token:
                        slack_dm(token, msg)
                    return False
                else:
                    msg = f"⚠️ *Varys self-heal FAILED*: `{name}` won't start — check logs at `{log_path}`"
                    log(f"Restart FAILED for {name}")
                    if token:
                        slack_dm(token, msg)
                    return False

    # 2. Scan the local log for recent errors for this service
    # Only look at errors AFTER the last known heal for this service
    state = {}
    if HEAL_STATE.exists():
        try:
            state = json.loads(HEAL_STATE.read_text())
        except Exception:
            pass
    last_healed_at = state.get(name, {}).get("last_healed_at")
    if last_healed_at:
        from datetime import timezone
        healed_dt  = datetime.fromisoformat(last_healed_at)
        age_minutes = (datetime.utcnow() - healed_dt).total_seconds() / 60
        if age_minutes < 15:
            # Last heal was recent — skip, errors predate it
            log(f"✅ {name}: healthy (healed {round(age_minutes)}m ago)")
            return True

    log_tail     = read_log_tail(log_path, lines=80)
    recent_errors = extract_errors(log_tail)
    if not recent_errors:
        log(f"✅ {name}: healthy")
        return True

    log(f"🔴 {name}: found {len(recent_errors)} error(s) in local log in last 15 min")
    # Log detection to Notion immediately
    log_error(service=name,
              error="\n".join(recent_errors[:2])[:500],
              context=f"Found {len(recent_errors)} error(s) in last 15 min")

    # 3. ESCALATE-ONLY (no auto-edit/auto-commit/auto-restart on log errors).
    # The self-healer previously shelled `claude -p` to diagnose+edit code and then
    # killed/restarted the daemon every cycle. That re-acted on STALE errors (still in
    # the window) and committed unverified edits → churn + contradictory DMs. Now it
    # only escalates, deduped against a handled-ledger, with one DM per distinct error.
    import hashlib
    handled = set()
    if HANDLED_LEDGER.exists():
        try:
            handled = {l.strip() for l in HANDLED_LEDGER.read_text().splitlines() if l.strip()}
        except Exception:
            handled = set()
    sig = hashlib.sha1(("|".join(recent_errors[:2]))[:300].encode()).hexdigest()[:16]
    ledger_key = f"{name}:{sig}"
    if ledger_key in handled:
        log(f"{name}: errors already escalated (ledger {ledger_key}) — not re-alerting")
        return True
    try:
        with open(HANDLED_LEDGER, "a") as f:
            f.write(ledger_key + "\n")
    except Exception:
        pass

    root_cause = "\n".join(recent_errors[:2])[:400]
    log_needs_manual(service=name, root_cause=root_cause, attempted="escalate-only (no auto-fix)")
    eval_self_heal(service=name, root_cause=root_cause, fix="escalated to Shoaib", applied=False)
    msg = (
        f"⚠️ *Varys flagged errors in `{name}` — needs your eyes*\n"
        f"• *Recent error(s):* {root_cause[:300]}\n"
        f"• *Action:* escalated (self-healer no longer edits code automatically)\n"
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
    klog("healer_run", component="self-healer", services=[s["name"] for s in SERVICES])

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
            klog_error(context=f"healer-check-{service['name']}", exc=e, component="self-healer")

    if all_healthy:
        log("All services healthy.")
    else:
        log("Done — issues found and handled above.")


if __name__ == "__main__":
    main()
