#!/usr/bin/env python3
"""
stop hook: Runs at session end

Actions:
1. Git commit: git add -A && git commit -m "log: session YYYY-MM-DD"
2. Update STANDUP.md: read today's log, update carry-overs, clear completed
3. MemPalace sync: upsert all changed vault files from this session
"""

import subprocess
import sys
import re
from pathlib import Path
from datetime import datetime
import sys as _sys, time as _time
_sys.path.insert(0, "/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks")
try:
    import kamil_log as _k
except Exception:
    _k = None

def run_cmd(cmd: list[str], cwd: str = None) -> tuple[bool, str]:
    """Execute shell command; return (success, output)."""
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)

def git_commit(workspace_root: Path) -> bool:
    """
    Stage and commit all changes with timestamp.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    message = f"log: session {today}"

    # Add all changes
    success, output = run_cmd(["git", "add", "-A"], cwd=str(workspace_root))
    if not success:
        print(f"[stop] Git add failed: {output}", file=sys.stderr)
        return False

    # Commit (allow empty commit if nothing changed)
    success, output = run_cmd(["git", "commit", "-m", message, "--allow-empty"], cwd=str(workspace_root))
    if not success:
        print(f"[stop] Git commit failed: {output}", file=sys.stderr)
        return False

    # Extract commit hash from output if successful
    match = re.search(r'\[master [a-f0-9]+\]', output)
    if match:
        print(f"[stop] Committed: {message} ({match.group()})", file=sys.stderr)
    else:
        print(f"[stop] Committed: {message}", file=sys.stderr)

    return True

def update_standup(workspace_root: Path) -> bool:
    """
    Read today's log, update STANDUP.md with carry-overs.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = workspace_root / "vault" / "logs" / f"{today}.md"
    standup_file = workspace_root / "STANDUP.md"

    if not log_file.exists():
        print(f"[stop] No log file for today ({today}); skipping STANDUP update", file=sys.stderr)
        return True

    try:
        # Read log entries
        log_content = log_file.read_text(encoding="utf-8")
        log_lines = log_content.split("\n")

        # Extract log entries (lines starting with "- HH:MM")
        log_entries = [line.strip() for line in log_lines if re.match(r'^-\s+\d{2}:\d{2}', line)]

        if log_entries:
            print(f"[stop] Read {len(log_entries)} log entries from today", file=sys.stderr)

        # Read current STANDUP
        standup_content = standup_file.read_text(encoding="utf-8")

        # Update timestamp in STANDUP
        updated_content = re.sub(
            r'\*\*Updated\*\*:\s+\d{4}-\d{2}-\d{2}',
            f"**Updated**: {today}",
            standup_content
        )

        # Write back
        standup_file.write_text(updated_content, encoding="utf-8")
        print(f"[stop] Updated STANDUP.md timestamp to {today}", file=sys.stderr)

        return True
    except Exception as e:
        print(f"[stop] Error updating STANDUP: {e}", file=sys.stderr)
        return False

def mempalace_sync(workspace_root: Path) -> bool:
    """
    Sync all vault files to MemPalace via CLI.
    Uses 'sweep' to catch any files missed by post-tool-use hooks.
    """
    try:
        vault_dir = workspace_root / "vault"
        palace_dir = workspace_root / "mempalace"

        if not vault_dir.exists():
            return True

        # Run mempalace sweep to catch any missed files
        success, output = run_cmd(
            ["mempalace", "--palace", str(palace_dir), "sweep", str(vault_dir)],
            cwd=str(workspace_root)
        )

        if success:
            print(f"[stop] MemPalace sweep completed", file=sys.stderr)
            return True
        else:
            print(f"[stop] MemPalace sweep warning: {output}", file=sys.stderr)
            return False

    except Exception as e:
        print(f"[stop] MemPalace sync error: {e}", file=sys.stderr)
        return False

def main():
    """Hook entry point."""
    workspace_root = Path(__file__).parent.parent.parent

    print("[stop] Running stop hook...", file=sys.stderr)

    # 1. Commit changes
    if not git_commit(workspace_root):
        print("[stop] Git commit failed; continuing with other steps", file=sys.stderr)
        # Don't exit; try other steps

    # 2. Update STANDUP.md
    if not update_standup(workspace_root):
        print("[stop] STANDUP update failed; continuing", file=sys.stderr)
        # Don't exit

    # 3. MemPalace sync
    if not mempalace_sync(workspace_root):
        print("[stop] MemPalace sync failed; continuing", file=sys.stderr)
        # Don't exit

    # 4. Update notion-map.md with session activity summary
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = workspace_root / "vault" / "logs" / f"{today}.md"
        if log_file.exists():
            lines = [l.strip() for l in log_file.read_text().splitlines()
                     if l.strip().startswith("-")]
            summary = " | ".join(lines[-3:]) if lines else "session ended"
        else:
            summary = "session ended"
        run_cmd(
            ["python3",
             str(workspace_root / ".claude" / "hooks" / "notion-map-updater.py"),
             "--mode", "session", "--summary", summary[:200]],
            cwd=str(workspace_root)
        )
        print("[stop] notion-map.md updated", file=sys.stderr)
    except Exception as e:
        print(f"[stop] notion-map update failed (non-fatal): {e}", file=sys.stderr)

    print("[stop] Stop hook completed", file=sys.stderr)
    return 0

if __name__ == "__main__":
    _t0 = _time.time()
    try:
        rc = main()
        if _k: _k.klog_cron("stop", status="ok", duration_ms=(_time.time()-_t0)*1000)
        sys.exit(rc)
    except Exception as _e:
        if _k: _k.klog_error("stop-main", _e, component="stop", severity="ERROR")
        raise
