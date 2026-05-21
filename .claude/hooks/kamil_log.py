"""
kamil_log.py — Shared Axiom logging for all Kamil hooks.

Usage:
    from kamil_log import klog
    klog("message_received", intent="chat", sender="Kamal", text="hello")
    klog("socket_stale", stale_minutes=8.2)
    klog("error", error="timeout", context="handle_pr_review")

All events land in the 'kamil-logs' Axiom dataset.
Query at: https://app.axiom.co
"""

import datetime
import json
import os
import sys
import traceback
import urllib.request
from pathlib import Path

_AXIOM_CONFIG = Path.home() / ".claude" / "hooks" / ".axiom"
_FALLBACK_LOG = Path("/tmp/kamil-axiom-fallback.jsonl")


def _load_config() -> dict:
    cfg = {}
    if _AXIOM_CONFIG.exists():
        for line in _AXIOM_CONFIG.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


def klog(event: str, **fields):
    """
    Send a structured event to Axiom.
    Falls back to local JSONL file if Axiom is unavailable.
    Never raises — logging must never break the main flow.
    """
    cfg     = _load_config()
    token   = cfg.get("AXIOM_TOKEN") or os.environ.get("AXIOM_TOKEN", "")
    dataset = cfg.get("AXIOM_DATASET", "kamil-logs")

    payload = {
        # Axiom expects plain UTC ISO string without timezone suffix
        "_time": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "event": event,
        **fields,
    }

    # Always write to local fallback first (instant, never fails)
    try:
        with open(_FALLBACK_LOG, "a") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        pass

    if not token:
        return

    try:
        import axiom_py
        client = axiom_py.Client(token)
        client.ingest_events(dataset=dataset, events=[payload])
    except Exception as e:
        # Silent — fallback file already has it
        pass


def klog_error(context: str, exc: Exception = None, **fields):
    """Log an exception with full traceback."""
    klog(
        "error",
        context=context,
        error=str(exc) if exc else "unknown",
        traceback=traceback.format_exc() if exc else "",
        **fields,
    )
