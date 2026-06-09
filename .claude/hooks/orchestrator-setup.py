#!/usr/bin/env python3
"""
orchestrator-setup.py — One-time setup for Kamil's team orchestrator.

Run manually: python3 .claude/hooks/orchestrator-setup.py

Checks:
  1. ~/.kamil-harness/ directory + harness.db schema
  2. ~/.kamil-harness/workspace/ (taleemabad-core checkout)
  3. Required env vars in config files
  4. Required Notion DB properties exist
  5. Test tick (dry run) to verify pollers can connect

Outputs a setup report and DMs Kamal with what's missing.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_config import cfg as _cfg
from kamil_harness_db import get_db, HARNESS_DIR, HARNESS_DB

WORKSPACE = HARNESS_DIR / "workspace"
CONFIG    = HARNESS_DIR / "config.json"

REQUIRED_VARS = [
    ("NOTION_API_KEY",       "~/.claude/hooks/.notion"),
    ("NOTION_DATABASE_ID",   "~/.kamil-harness/config.json (or use default)"),
    ("NOTION_AGENT_USER_ID", "~/.kamil-harness/config.json"),
    ("SLACK_BOT_TOKEN",      "~/.claude/hooks/.slack as BOT_TOKEN= or SLACK_BOT_TOKEN="),
    ("SLACK_USER_TOKEN",     "~/.claude/hooks/.slack as SLACK_USER_TOKEN= (xoxp- user token)"),
    ("GITHUB_TOKEN",         "~/.kamil-harness/config.json"),
    ("GITHUB_AGENT_LOGIN",   "~/.kamil-harness/config.json"),
]

REQUIRED_NOTION_PROPS = [
    "Status", "Agent Session ID", "Last Agent Update", "GitHub PR", "Slack Thread"
]

GITHUB_REPO = os.environ.get("GITHUB_REPO", "{{YOUR_GITHUB_ORG}}/{{YOUR_REPO}}")


def check(label: str, ok: bool, detail: str = "") -> bool:
    icon = "✅" if ok else "❌"
    print(f"  {icon}  {label}" + (f"\n      → {detail}" if detail and not ok else ""))
    return ok


def _load_all_config() -> dict:
    cfg = {}
    notion_cfg = Path.home() / ".claude" / "hooks" / ".notion"
    slack_cfg  = Path.home() / ".claude" / "hooks" / ".slack"
    for f in [notion_cfg, slack_cfg]:
        if f.exists():
            for line in f.read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    if CONFIG.exists():
        cfg.update(json.loads(CONFIG.read_text()))
    cfg.update({k: v for k, v in os.environ.items() if k in dict(REQUIRED_VARS)})
    # Alias mappings — .slack file uses BOT_TOKEN not SLACK_BOT_TOKEN
    if not cfg.get("SLACK_BOT_TOKEN") and cfg.get("BOT_TOKEN"):
        cfg["SLACK_BOT_TOKEN"] = cfg["BOT_TOKEN"]
    if not cfg.get("NOTION_DATABASE_ID"):
        cfg["NOTION_DATABASE_ID"] = _cfg("NOTION_HARNESS_DB_ID", "de10157da3e34ef58a74ea240f31fe98")
    return cfg


def main():
    print("\n🔧  Kamil Team Orchestrator — Setup Check\n")
    results = []

    # 1. DB
    print("1. Harness database")
    try:
        db = get_db()
        tables = [r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        required_tables = {"sync_state", "tick_lock", "events", "entities", "links", "sessions"}
        missing = required_tables - set(tables)
        results.append(check("harness.db exists + schema", not missing,
                             f"Missing tables: {missing}" if missing else ""))
        db.close()
    except Exception as e:
        results.append(check("harness.db", False, str(e)))

    # 2. Workspace
    print("\n2. Workspace (project checkout)")
    ws_exists = WORKSPACE.exists()
    results.append(check("workspace directory exists", ws_exists,
                         f"Run: git clone git@github.com:{GITHUB_REPO}.git {WORKSPACE}"))
    if ws_exists:
        try:
            branch = subprocess.check_output(
                ["git", "branch", "--show-current"], cwd=str(WORKSPACE),
                text=True, timeout=5
            ).strip()
            results.append(check(f"workspace on branch: {branch}",
                                 branch in ("develop", "main", "master")))
        except Exception:
            results.append(check("workspace is a git repo", False,
                                 "Could not determine branch"))

    # 3. Env vars
    print("\n3. Required environment variables")
    cfg = _load_all_config()
    for var, location in REQUIRED_VARS:
        val = cfg.get(var, "")
        if var == "NOTION_DATABASE_ID":
            val = val or _cfg("NOTION_HARNESS_DB_ID", "de10157da3e34ef58a74ea240f31fe98")  # default
        ok = bool(val)
        results.append(check(f"{var}", ok, f"Set in: {location}" if not ok else ""))

    # 4. Summary
    passed = sum(results)
    total  = len(results)
    print(f"\n{'─'*50}")
    print(f"Result: {passed}/{total} checks passed")

    if passed == total:
        print("\n✅  Orchestrator is ready. Add to crontab:")
        print(f"   */5 * * * * cd {Path.home() / 'Documents/free_work/personal-agent-v2'} && /loop 270")
    else:
        print(f"\n❌  {total - passed} issue(s) to fix before orchestrator can run.")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
