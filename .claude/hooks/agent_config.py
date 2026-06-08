#!/usr/bin/env python3
"""
agent_config.py — Central config loader for the personal agent template.

Reads ~/.agent-config.json (created by /setup wizard).
Falls back to environment variables, then to provided default.

Usage in any hook:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from agent_config import cfg

    HARNESS_DB = cfg("NOTION_HARNESS_DB_ID")
    USER_ID    = cfg("USER_SLACK_ID")
"""
import json
import os
from pathlib import Path

_CONFIG_PATH = Path.home() / ".agent-config.json"
_CACHE: dict | None = None


def cfg(key: str, default=None):
    """Return config value for key. Order: ~/.agent-config.json → env var → default."""
    global _CACHE
    if _CACHE is None:
        if _CONFIG_PATH.exists():
            try:
                _CACHE = json.loads(_CONFIG_PATH.read_text())
            except (json.JSONDecodeError, OSError):
                _CACHE = {}
        else:
            _CACHE = {}
    return _CACHE.get(key) or os.environ.get(key) or default


def cfg_all() -> dict:
    """Return a copy of the full config dict (triggers load if needed)."""
    cfg("_warmup")
    return dict(_CACHE)


def is_configured() -> bool:
    """Return True if /setup has been run (config file exists and has AGENT_NAME)."""
    return bool(cfg("AGENT_NAME"))
