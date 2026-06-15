#!/usr/bin/env python3
"""
poll-work-state.py — Every 30min cron.
Captures Shoaib's active work state: branch + PRs + commits + Harness tickets.
Output: /tmp/varys-work-state.json  ← read by session-start.py at every session.
"""
import json, os, subprocess, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_config import cfg
try:
    from varys_log import klog_cron, klog_error
except Exception:
    klog_cron = klog_error = lambda *a, **kw: None

OUTPUT    = Path("/tmp/varys-work-state.json")
CORE_PATH = Path(cfg("TALEEMABAD_CORE_PATH", str(Path.home() / "Taleemabad" / "taleemabad-core")))



NVM      = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
VARYS_DIR = Path(__file__).parent.parent.parent

HARNESS_PROMPT = """Query the Notion Harness DB (de10157da3e34ef58a74ea240f31fe98) for tickets where Phase is In Progress, In Dev, or Blocked. Use mcp__claude_ai_Notion__notion-search on the data source collection://a173fd5a-b953-4a53-a020-4545db41ccb5.

Output ONLY a JSON array, no prose:
[{"title": "...", "phase": "...", "pr": "...", "jira": "...", "plan": "..."}]

Empty array if none found."""


def fetch_harness_active() -> list:
    env = os.environ.copy()
    env["VARYS_PROMPT"] = HARNESS_PROMPT
    try:
        r = subprocess.run(
            ["bash", "-c", f'{NVM} && claude --dangerously-skip-permissions --print -p "$VARYS_PROMPT"'],
            capture_output=True, text=True, cwd=str(VARYS_DIR), timeout=60, env=env,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return []
        # Extract JSON array from output
        out = r.stdout.strip()
        start, end = out.find("["), out.rfind("]")
        if start == -1 or end == -1:
            return []
        return json.loads(out[start:end+1])
    except Exception as e:
        print(f"[poll-work-state] harness via claude: {e}", file=sys.stderr)
        return []


def fetch_open_prs() -> list:
    if not CORE_PATH.exists():
        return []
    try:
        r = subprocess.run(
            ["gh", "pr", "list", "--author", "@me", "--state", "open",
             "--json", "number,title,url,isDraft,headRefName,reviewDecision",
             "--limit", "10"],
            capture_output=True, text=True, timeout=15, cwd=str(CORE_PATH),
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except Exception as e:
        print(f"[poll-work-state] gh: {e}", file=sys.stderr)
    return []


def fetch_recent_commits() -> list:
    if not CORE_PATH.exists():
        return []
    try:
        r = subprocess.run(
            ["git", "log", "--since=30 days ago", "--author=shoaib",
             "--oneline", "--no-merges", "--max-count=15"],
            capture_output=True, text=True, timeout=10, cwd=str(CORE_PATH),
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()
    except Exception as e:
        print(f"[poll-work-state] git: {e}", file=sys.stderr)
    return []


def fetch_active_branch() -> str:
    if not CORE_PATH.exists():
        return ""
    try:
        r = subprocess.run(["git", "branch", "--show-current"],
                           capture_output=True, text=True, timeout=5, cwd=str(CORE_PATH))
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def main():
    state = {
        "updated_at": datetime.now().isoformat(),
        "active_branch": fetch_active_branch(),
        "harness_active": fetch_harness_active(),
        "open_prs": fetch_open_prs(),
        "recent_commits": fetch_recent_commits(),
    }
    OUTPUT.write_text(json.dumps(state, indent=2))
    print(
        f"[poll-work-state] branch={state['active_branch'] or '?'} "
        f"tickets={len(state['harness_active'])} "
        f"PRs={len(state['open_prs'])} "
        f"commits={len(state['recent_commits'])}"
    )


if __name__ == "__main__":
    import time as _t
    t0 = _t.time()
    try:
        main()
        klog_cron("poll-work-state", status="ok", duration_ms=(_t.time() - t0) * 1000)
    except Exception as e:
        klog_error("poll-work-state", e, component="poll-work-state", severity="ERROR")
        raise
