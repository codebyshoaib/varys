#!/usr/bin/env python3
"""
poll-work-state.py — Every 30min cron.
Captures Shoaib's active work state: branch + PRs + commits + Harness tickets.
Output: /tmp/varys-work-state.json  ← read by session-start.py at every session.
"""
import json, subprocess, sys, urllib.request
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


def _notion_token() -> str:
    cfg_file = Path.home() / ".claude" / "hooks" / ".notion"
    if cfg_file.exists():
        for line in cfg_file.read_text().splitlines():
            if line.startswith("NOTION_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def fetch_harness_active() -> list:
    token = _notion_token()
    if not token:
        return []
    db_id = cfg("NOTION_HARNESS_DB_ID", "de10157da3e34ef58a74ea240f31fe98")
    try:
        data = json.dumps({
            "filter": {"or": [
                {"property": "Phase", "select": {"equals": "In Progress"}},
                {"property": "Phase", "select": {"equals": "In Dev"}},
                {"property": "Phase", "select": {"equals": "Blocked"}},
            ]},
            "page_size": 10,
        }).encode()
        req = urllib.request.Request(
            f"https://api.notion.com/v1/databases/{db_id}/query",
            data=data,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "Notion-Version": "2022-06-28"},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            pages = json.loads(r.read()).get("results", [])
        results = []
        for page in pages:
            p = page["properties"]
            results.append({
                "title": (p.get("Feature", {}).get("title") or [{}])[0].get("plain_text", ""),
                "phase": (p.get("Phase", {}).get("select") or {}).get("name", ""),
                "pr":    (p.get("PR", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
                "plan":  ((p.get("Plan Summary", {}).get("rich_text") or [{}])[0].get("plain_text", ""))[:200],
                "jira":  (p.get("Jira Ticket", {}).get("rich_text") or [{}])[0].get("plain_text", ""),
            })
        return results
    except Exception as e:
        print(f"[poll-work-state] harness: {e}", file=sys.stderr)
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
