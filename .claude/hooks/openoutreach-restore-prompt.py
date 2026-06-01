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


def ensure_web_server() -> bool:
    """Start Django admin web server if not running. Uses --noreload so it survives file changes."""
    try:
        result = subprocess.run(
            ["docker", "exec", CONTAINER, "sh", "-c",
             "ls /proc/*/cmdline 2>/dev/null | xargs -I{} sh -c 'cat {} 2>/dev/null | tr \"\\0\" \" \"' 2>/dev/null | grep -q 'runserver'"],
            capture_output=True, timeout=10
        )
        if result.returncode != 0:
            subprocess.Popen(
                ["docker", "exec", "-d", CONTAINER, "sh", "-c",
                 "cd /app && python manage.py runserver 0.0.0.0:8000 --noreload >> /tmp/django.log 2>&1"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            print("[restore-prompt] Started Django web server (admin at :8001).", flush=True)
        return True
    except Exception as e:
        print(f"[restore-prompt] Could not ensure web server: {e}", flush=True)
        return False


if __name__ == "__main__":
    force = "--force" in sys.argv
    ensure_patched(force=force)
    ensure_web_server()
    sys.exit(0)
