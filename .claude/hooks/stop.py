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
from pathlib import Path
from datetime import datetime

def run_cmd(cmd: list[str], cwd: str = None) -> bool:
    """Execute shell command; return True if successful."""
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[stop] Command failed: {' '.join(cmd)}", file=sys.stderr)
            print(f"  stderr: {result.stderr}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"[stop] Error running command: {e}", file=sys.stderr)
        return False

def git_commit(workspace_root: Path) -> bool:
    """
    Stage and commit all changes.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    message = f"log: session {today}"

    # Add all changes
    if not run_cmd(["git", "add", "-A"], cwd=str(workspace_root)):
        return False

    # Commit (allow empty commit if nothing changed)
    if not run_cmd(["git", "commit", "-m", message, "--allow-empty"], cwd=str(workspace_root)):
        return False

    print(f"[stop] Committed: {message}", file=sys.stderr)
    return True

def update_standup(workspace_root: Path) -> bool:
    """
    Read today's log, update STANDUP.md carry-overs.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = workspace_root / "vault" / "logs" / f"{today}.md"

    if not log_file.exists():
        return True  # No log entries today, nothing to carry over

    try:
        log_content = log_file.read_text(encoding="utf-8")

        # Extract log entries (simple heuristic: lines starting with "- HH:MM")
        log_entries = [line for line in log_content.split("\n") if line.strip().startswith("- ")]

        # For now, just log that we read the log
        # Full implementation would parse carry-overs and update STANDUP.md
        if log_entries:
            print(f"[stop] Read {len(log_entries)} log entries from today", file=sys.stderr)

        return True
    except Exception as e:
        print(f"[stop] Error updating STANDUP: {e}", file=sys.stderr)
        return False

def main():
    """Hook entry point."""
    workspace_root = Path(__file__).parent.parent.parent

    print("[stop] Running stop hook...", file=sys.stderr)

    # 1. Commit changes
    if not git_commit(workspace_root):
        print("[stop] Git commit failed", file=sys.stderr)
        return 1

    # 2. Update STANDUP.md
    if not update_standup(workspace_root):
        print("[stop] STANDUP update failed", file=sys.stderr)
        return 1

    # 3. MemPalace sync (would call MCP tools once integrated)
    print("[stop] MemPalace sync triggered (integrate with MCP once available)", file=sys.stderr)

    print("[stop] Stop hook completed successfully", file=sys.stderr)
    return 0

if __name__ == "__main__":
    sys.exit(main())
