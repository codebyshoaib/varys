#!/usr/bin/env python3
"""
kamil-evolution-agent.py — Fire the evolution agent when 3+ new failures since last run.

Tracks last run timestamp in ~/.kamil-harness/evolution-last-run.txt.
Called by: orchestrator-dispatch.py each tick, or manually.
"""
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from kamil_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

KAMIL_DIR             = Path(__file__).parent.parent.parent
FAILURES_FILE         = KAMIL_DIR / ".beads" / "failures.jsonl"
LAST_RUN_FILE         = Path.home() / ".kamil-harness" / "evolution-last-run.txt"
AGENTS_DIR            = KAMIL_DIR / ".claude" / "agents"
NEW_FAILURE_THRESHOLD = 3


def _count_new_failures() -> int:
    """Count failures.jsonl entries since last evolution run."""
    if not FAILURES_FILE.exists():
        return 0
    last_run = datetime.min
    if LAST_RUN_FILE.exists():
        try:
            last_run = datetime.fromisoformat(LAST_RUN_FILE.read_text().strip())
        except ValueError:
            pass
    count = 0
    for line in FAILURES_FILE.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            ts_str = entry.get("ts", "")
            if ts_str:
                # Normalize to naive UTC — all timestamps in this system are UTC
                ts = datetime.fromisoformat(ts_str.replace("Z", "").split("+")[0].split("-00")[0])
                if ts > last_run and entry.get("type") != "evolution-applied":
                    count += 1
        except (json.JSONDecodeError, ValueError):
            continue
    return count


def _spawn_evolution_agent() -> bool:
    agent_file = AGENTS_DIR / "kamil-evolution-agent.md"
    if not agent_file.exists():
        klog_error("evolution-agent-missing", Exception("agent file not found"),
                   component="evolution-agent")
        return False
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    prompt = (
        "You are Kamil's kamil-evolution-agent. "
        f"Failures file: {FAILURES_FILE}. "
        "Read the recent failures, identify patterns, apply fixes within the fence. "
        "DM Kamal (U0AV1DX3WSE) with each change made. "
        f"Harness DB: {Path.home() / '.kamil-harness' / 'harness.db'}"
    )
    tmp = Path(tempfile.mktemp(suffix=".txt"))
    tmp.write_text(prompt)
    try:
        result = subprocess.run(
            ["bash", "-c",
             f'{nvm} && claude --dangerously-skip-permissions --print -p "$(cat {tmp})"'],
            cwd=str(KAMIL_DIR), capture_output=True, text=True, timeout=600,
        )
        klog("evolution-agent-run", component="evolution-agent",
             returncode=result.returncode)
        return result.returncode == 0
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    new_count = _count_new_failures()
    print(f"[evolution-agent] {new_count} new failure(s) since last run.")
    if new_count < NEW_FAILURE_THRESHOLD:
        print(f"[evolution-agent] Below threshold ({NEW_FAILURE_THRESHOLD}). Skipping.")
        return 0
    print("[evolution-agent] Threshold reached. Firing evolution agent.")
    success = _spawn_evolution_agent()
    if success:
        LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
        LAST_RUN_FILE.write_text(datetime.utcnow().isoformat())
        klog("evolution-agent-complete", component="evolution-agent", new_failures=new_count)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
