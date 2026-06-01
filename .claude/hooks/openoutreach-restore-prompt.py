#!/usr/bin/env python3
"""
openoutreach-restore-prompt.py — Re-applies the value-first follow_up_agent.j2
patch after container restarts. Called by openoutreach-monitor.py on every run.

The container ships with a Discovery-based strategy template that generates
"How do you currently handle X?" messages. This script replaces it with a
value-first template that never opens with questions.

Usage:
    python3 openoutreach-restore-prompt.py        # check + restore if needed
    python3 openoutreach-restore-prompt.py --force # always re-apply

Returns exit code 0 always (errors are logged, not fatal).
"""

import subprocess
import sys
from pathlib import Path

CONTAINER      = "openoutreach"
CONTAINER_PATH = "/app/linkedin/templates/prompts/follow_up_agent.j2"
LOCAL_PATCH    = Path(__file__).parent / "openoutreach-follow-up-prompt.j2"
SENTINEL       = "NEVER ask discovery questions. NEVER open with a question."


def is_patch_applied() -> bool:
    """Check if the value-first patch is already in the container."""
    try:
        result = subprocess.run(
            ["docker", "exec", CONTAINER, "grep", "-q", SENTINEL, CONTAINER_PATH],
            capture_output=True, timeout=10
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[restore-prompt] Could not check container: {e}", flush=True)
        return False


def apply_patch() -> bool:
    """Copy the patched template into the container."""
    if not LOCAL_PATCH.exists():
        print(f"[restore-prompt] ERROR: local patch not found at {LOCAL_PATCH}", flush=True)
        return False
    try:
        result = subprocess.run(
            ["docker", "cp", str(LOCAL_PATCH), f"{CONTAINER}:{CONTAINER_PATH}"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            print("[restore-prompt] Patch applied successfully.", flush=True)
            return True
        else:
            print(f"[restore-prompt] docker cp failed: {result.stderr}", flush=True)
            return False
    except Exception as e:
        print(f"[restore-prompt] ERROR applying patch: {e}", flush=True)
        return False


def ensure_patched(force: bool = False) -> bool:
    """Check if patch is applied; apply it if not (or if forced)."""
    if not force and is_patch_applied():
        print("[restore-prompt] Patch already applied — no action needed.", flush=True)
        return True
    print("[restore-prompt] Patch missing — applying value-first template.", flush=True)
    return apply_patch()


if __name__ == "__main__":
    force = "--force" in sys.argv
    success = ensure_patched(force=force)
    sys.exit(0 if success else 1)
