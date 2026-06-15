#!/usr/bin/env python3
"""
stop-notion hook: Runs at session end.
Writes a Work Log entry to Notion via MCP (claude -p), no API token needed.
"""
import json, os, subprocess, sys
from datetime import datetime
from pathlib import Path
import sys as _sys, time as _time

_sys.path.insert(0, str(Path(__file__).parent))
try:
    import varys_log as _k
except Exception:
    _k = None

VARYS_DIR = Path(__file__).parent.parent.parent
CORE      = Path.home() / "Taleemabad" / "taleemabad-core"
NVM       = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'


def git(args, cwd=CORE):
    r = subprocess.run(args, capture_output=True, text=True, timeout=8, cwd=str(cwd))
    return r.stdout.strip() if r.returncode == 0 else ""


def detect_session() -> dict:
    branch  = git(["git", "branch", "--show-current"])
    commits = git(["git", "log", "--since=midnight", "--oneline", "--no-merges", "--max-count=10"])
    prs = ""
    try:
        r = subprocess.run(
            ["gh", "pr", "list", "--author", "@me", "--state", "open",
             "--json", "number,title", "--limit", "5"],
            capture_output=True, text=True, timeout=10, cwd=str(CORE)
        )
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            prs = "; ".join(f"#{p['number']} {p['title']}" for p in data)
    except Exception:
        pass

    project = "taleemabad-core"
    cwd = os.getcwd()
    if "taleemabad-cms" in cwd:   project = "taleemabad-cms"
    elif "/varys" in cwd and "taleemabad" not in cwd: project = "personal-agent"

    what_done = ""
    if branch:
        what_done += f"Branch: {branch}\n"
    if commits:
        what_done += "Commits today:\n" + "\n".join(f"  {l}" for l in commits.splitlines())
    if not what_done:
        what_done = "Session ended — no commits detected."

    return {
        "date":      datetime.now().strftime("%Y-%m-%d"),
        "project":   project,
        "branch":    branch,
        "what_done": what_done.strip(),
        "prs":       prs,
    }


def write_via_mcp(info: dict):
    prompt = f"""Write a Work Log entry to Notion for today's session using the notion MCP.

DB: 0b71db855f914d18ac6d97c0f77fc21e (Work Log)

Properties to set:
- Session: "{info['date']} — {info['project']} session"
- Date: {info['date']}
- Project: {info['project']}
- Phase: Feature
- What Was Done: {info['what_done'][:500]}
{f"- PRs Worked On: {info['prs']}" if info['prs'] else ""}

Use mcp__claude_ai_Notion__notion-create-pages to create the entry. Output only "OK" when done."""

    env = os.environ.copy()
    env["VARYS_PROMPT"] = prompt
    result = subprocess.run(
        ["bash", "-c", f'{NVM} && claude --dangerously-skip-permissions --print -p "$VARYS_PROMPT"'],
        capture_output=True, text=True,
        cwd=str(VARYS_DIR), timeout=90, env=env,
    )
    return result.returncode == 0 and result.stdout.strip()


def main():
    info = detect_session()
    ok   = write_via_mcp(info)
    msg  = f"✅ Work Log written via MCP: {info['date']} — {info['project']}" if ok \
           else f"⚠️ Work Log MCP write failed for {info['date']}"
    print(msg, file=sys.stderr)
    print(json.dumps({"systemMessage": msg}))
    return 0


if __name__ == "__main__":
    t0 = _time.time()
    try:
        rc = main()
        if _k: _k.klog_cron("stop-notion", status="ok", duration_ms=(_time.time()-t0)*1000)
        sys.exit(rc)
    except Exception as e:
        if _k: _k.klog_error("stop-notion-main", e, component="stop-notion", severity="ERROR")
        raise
