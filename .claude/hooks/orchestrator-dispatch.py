#!/usr/bin/env python3
"""
orchestrator-dispatch.py — Group pending events by context_key, spawn subagents.

Called once per /loop tick AFTER all pollers succeed.
Follows the exact 7-step dispatcher protocol from orchestration-harness-v2.

Step 1: SELECT DISTINCT context_keys with pending events (two-query pattern)
Step 2: Skip if session already running for context_key
Step 3: Resolve rich context (Notion ticket, linked Slack thread, linked GitHub PR)
Step 4: INSERT session record (status='running')
Step 5: UPDATE events to status='processing'
Step 6: Spawn subagent via claude CLI with injected context
Step 7: On failure → revert session to 'cancelled', events back to 'pending'
"""

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_harness_db import get_db, get_linked_entities
from kamil_notion import notion_request
try:
    from kamil_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

NOTION_CFG  = Path.home() / ".claude" / "hooks" / ".notion"
SLACK_CFG   = Path.home() / ".claude" / "hooks" / ".slack"
HARNESS_CFG = Path.home() / ".kamil-harness" / "config.json"
WORKSPACE   = Path.home() / ".kamil-harness" / "workspace"
KAMIL_DIR   = Path(__file__).parent.parent.parent

SKILLS_DIR  = KAMIL_DIR / ".claude" / "commands"


def _load_config() -> dict:
    cfg = {}
    for cfg_file, prefix in [(NOTION_CFG, ""), (SLACK_CFG, ""), (HARNESS_CFG, "")]:
        if cfg_file.exists():
            try:
                if cfg_file.suffix == ".json":
                    cfg.update(json.loads(cfg_file.read_text()))
                else:
                    for line in cfg_file.read_text().splitlines():
                        if "=" in line:
                            k, v = line.split("=", 1)
                            cfg[k.strip()] = v.strip()
            except Exception:
                pass
    for key in ("NOTION_API_KEY", "SLACK_BOT_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(key):
            cfg[key] = os.environ[key]
    return cfg


def _notion_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
    }


def _fetch_notion_ticket(api_key: str, external_id: str) -> dict:
    """Fetch full Notion page content for a ticket."""
    import urllib.request as ur
    req = ur.Request(
        f"https://api.notion.com/v1/pages/{external_id}",
        headers=_notion_headers(api_key),
        method="GET",
    )
    _, body = notion_request(req)
    return json.loads(body)


def _fetch_slack_thread(bot_token: str, channel: str, thread_ts: str,
                        limit: int = 10) -> list[dict]:
    """Fetch last N messages from a Slack thread."""
    import urllib.request as ur
    import urllib.parse
    params = urllib.parse.urlencode({
        "channel": channel, "ts": thread_ts, "limit": limit
    })
    req = ur.Request(
        f"https://slack.com/api/conversations.replies?{params}",
        headers={"Authorization": f"Bearer {bot_token}"},
        method="GET",
    )
    with ur.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    return data.get("messages", [])


def _fetch_github_pr(gh_token: str, repo: str, pr_num: str) -> dict:
    """Fetch GitHub PR details."""
    import urllib.request as ur
    req = ur.Request(
        f"https://api.github.com/repos/{repo}/pulls/{pr_num}",
        headers={
            "Authorization": f"Bearer {gh_token}",
            "Accept": "application/vnd.github+json",
        },
        method="GET",
    )
    with ur.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _available_skills() -> list[str]:
    """Return list of available slash command names."""
    if not SKILLS_DIR.exists():
        return []
    return [f.stem for f in SKILLS_DIR.glob("*.md")]


def _page_title(page: dict) -> str:
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return "".join(p.get("plain_text", "") for p in prop.get("title", []))
    return "Untitled"


def _page_status(page: dict) -> str:
    props = page.get("properties", {})
    # Harness DB uses "Phase" (select), not "Status"
    for name in ("Phase", "Status"):
        prop = props.get(name, {})
        if prop.get("type") == "select":
            return prop.get("select", {}).get("name", "Unknown") or "Unknown"
        if prop.get("type") == "status":
            return prop.get("status", {}).get("name", "Unknown") or "Unknown"
    return "Unknown"


def _build_subagent_prompt(
    context_key: str,
    events: list[dict],
    notion_page: dict | None,
    linked_entities: list[dict],
    slack_messages: list[dict],
    github_pr: dict | None,
    session_id: str,
    cfg: dict,
) -> str:
    """Build the rich context prompt injected into the subagent."""
    event_types = ", ".join(set(e["type"] for e in events))
    title = _page_title(notion_page) if notion_page else "Unknown ticket"
    status = _page_status(notion_page) if notion_page else "Unknown"
    notion_url = notion_page.get("url", "") if notion_page else ""

    slack_section = ""
    if slack_messages:
        msgs = "\n".join(
            f"  [{m.get('user','?')}]: {m.get('text','')[:200]}"
            for m in slack_messages[-10:]
        )
        slack_section = f"\nSLACK THREAD (last {len(slack_messages)} messages):\n{msgs}"

    github_section = ""
    if github_pr:
        github_section = (
            f"\nGITHUB PR #{github_pr.get('number','?')}: {github_pr.get('title','')}\n"
            f"  State: {github_pr.get('state','')}  URL: {github_pr.get('html_url','')}\n"
            f"  Body: {(github_pr.get('body') or '')[:400]}"
        )

    skills = _available_skills()
    skills_section = "\n".join(f"  /{s}" for s in skills) if skills else "  (none)"

    github_repo = cfg.get("GITHUB_REPO", "Orenda-Project/taleemabad-core")

    return f"""You are Kamil, Taleemabad's AI engineer. You have been spawned to handle work.

SESSION ID: {session_id}
CONTEXT KEY (Notion ticket entity): {context_key}
TRIGGERING EVENTS: {event_types}

NOTION TICKET:
  Title: {title}
  Status: {status}
  URL: {notion_url}
{slack_section}
{github_section}

WORKSPACE: {WORKSPACE}
  (taleemabad-core checkout — operate here for all code changes)

AVAILABLE SKILLS:
{skills_section}

RULES YOU MUST FOLLOW:
1. PLAN-FIRST for all implementation work:
   - Step A: Read source code in workspace → draft implementation plan + define E2E test cases
             → post plan to Slack thread with "Reply @Kamil go to proceed"
             → set Notion Status=Blocked → update session status='cancelled' in harness.db
             → exit (wait for human approval)
   - Step B: Only when triggered by "@Kamil go" reply → implement per plan → run E2E tests
             → if E2E pass: open PR → set Notion Status=Done LAST
             → if E2E fail after 5 attempts: open PR with failure report → Status=Blocked LAST

2. For informational questions (no code needed):
   → answer directly in Slack thread → update Notion ticket → mark session completed

3. For pr.merged events:
   → set Notion Status=Done → post success message to Slack → mark session completed

4. For pr.closed (not merged) events:
   → set Notion Status=Blocked → post explanation to Slack → mark session completed

5. For pr.review_commented events:
   → read review, reason about changes → implement fixes → push to same branch
   → reply to review in GitHub → mark session completed

6. STATUS=DONE IS ALWAYS THE LAST NOTION UPDATE — it is the commit signal.

7. When done (any path), update harness.db:
   UPDATE sessions SET status='completed', updated_at=datetime('now') WHERE id='{session_id}';
   UPDATE events SET status='done', processed_at=datetime('now')
   WHERE context_key='{context_key}' AND status='processing';

8. If you cannot proceed (need info, blocked):
   → explain in Slack → set Notion Status=Blocked → set session status='cancelled'
   → next @Kamil reply will spawn a new session

HARNESS DB: {Path.home() / '.kamil-harness' / 'harness.db'}
GITHUB REPO: {github_repo}
"""


def main() -> int:
    cfg = _load_config()
    api_key   = cfg.get("NOTION_API_KEY")
    bot_token = cfg.get("SLACK_BOT_TOKEN") or cfg.get("BOT_TOKEN")
    gh_token  = cfg.get("GITHUB_TOKEN")
    gh_repo   = cfg.get("GITHUB_REPO", "Orenda-Project/taleemabad-core")

    db = get_db()

    # ── Step 1: Get distinct context_keys with pending events (two-query pattern) ──
    context_keys = [
        row[0] for row in
        db.execute("SELECT DISTINCT context_key FROM events WHERE status='pending'").fetchall()
    ]

    if not context_keys:
        print("[dispatch] No pending events.")
        db.close()
        return 0

    print(f"[dispatch] {len(context_keys)} context key(s) with pending events.")
    spawned = 0

    for context_key in context_keys:
        # Fetch full event rows (never GROUP_CONCAT — JSON payloads contain commas)
        events = [
            {"id": r[0], "source": r[1], "type": r[2], "payload": json.loads(r[3])}
            for r in db.execute(
                "SELECT id, source, type, payload FROM events "
                "WHERE context_key=? AND status='pending'",
                (context_key,),
            ).fetchall()
        ]

        # ── Step 2: Skip if session already running ──
        running = db.execute(
            "SELECT id FROM sessions WHERE context_key=? AND status='running'",
            (context_key,),
        ).fetchone()
        if running:
            print(f"[dispatch] Skipping {context_key[:16]}... — session already running")
            continue

        # ── Step 3: Resolve rich context ──
        notion_page   = None
        slack_messages = []
        github_pr     = None

        # Find Notion entity for this context_key
        notion_row = db.execute(
            "SELECT external_id, url FROM entities WHERE id=? AND source='notion'",
            (context_key,),
        ).fetchone()

        if notion_row and api_key:
            try:
                notion_page = _fetch_notion_ticket(api_key, notion_row[0])
            except Exception as e:
                print(f"[dispatch] WARNING: could not fetch Notion page: {e}")

        # Find linked entities
        linked = get_linked_entities(db, context_key)
        for entity in linked:
            if entity["source"] == "slack" and bot_token:
                try:
                    parts = entity["external_id"].split("/")
                    if len(parts) == 2:
                        channel, thread_ts = parts
                        slack_messages = _fetch_slack_thread(bot_token, channel, thread_ts)
                except Exception:
                    pass
            elif entity["source"] == "github" and gh_token:
                try:
                    # external_id format: "repo#pr_num"
                    pr_num = entity["external_id"].split("#")[-1]
                    github_pr = _fetch_github_pr(gh_token, gh_repo, pr_num)
                except Exception:
                    pass

        # ── Step 4: Create session record ──
        session_id = f"session-{uuid.uuid4()}"
        event_types = ",".join(set(e["type"] for e in events))
        db.execute(
            "INSERT INTO sessions (id, context_key, status, intent, created_at, updated_at) "
            "VALUES (?, ?, 'running', ?, datetime('now'), datetime('now'))",
            (session_id, context_key, event_types),
        )
        db.commit()

        # ── Step 5: Mark events as processing ──
        db.execute(
            "UPDATE events SET status='processing' "
            "WHERE context_key=? AND status='pending'",
            (context_key,),
        )
        db.commit()

        # ── Step 6: Build prompt and spawn subagent ──
        prompt = _build_subagent_prompt(
            context_key=context_key,
            events=events,
            notion_page=notion_page,
            linked_entities=linked,
            slack_messages=slack_messages,
            github_pr=github_pr,
            session_id=session_id,
            cfg=cfg,
        )

        title = _page_title(notion_page) if notion_page else context_key[:20]
        print(f"[dispatch] Spawning subagent for: {title[:60]} ({event_types})")

        # Write prompt to temp file so we can pass it cleanly
        prompt_file = Path(f"/tmp/kamil-dispatch-{session_id}.txt")
        prompt_file.write_text(prompt)

        try:
            nvm_source = (
                'export NVM_DIR="$HOME/.nvm"; '
                '[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
            )
            cmd = (
                f'{nvm_source} && claude --dangerously-skip-permissions '
                f'--print -p "$(cat {prompt_file})"'
            )
            result = subprocess.run(
                ["bash", "-c", cmd],
                cwd=str(WORKSPACE) if WORKSPACE.exists() else str(KAMIL_DIR),
                capture_output=True,
                text=True,
                timeout=600,  # 10 min max per subagent
            )

            if result.returncode == 0:
                spawned += 1
                klog("dispatch-spawn", component="orchestrator",
                     session_id=session_id, context_key=context_key,
                     event_types=event_types)
            else:
                raise RuntimeError(f"claude exited {result.returncode}: {result.stderr[:300]}")

        except Exception as e:
            # ── Step 7: Failure — revert session + events ──
            print(f"[dispatch] ERROR spawning subagent for {context_key[:16]}: {e}",
                  file=sys.stderr)
            klog_error("dispatch-spawn-fail", e, component="orchestrator",
                       session_id=session_id)
            db.execute(
                "UPDATE sessions SET status='cancelled', updated_at=datetime('now') "
                "WHERE id=?", (session_id,)
            )
            db.execute(
                "UPDATE events SET status='pending' "
                "WHERE context_key=? AND status='processing'",
                (context_key,),
            )
            db.commit()
        finally:
            if prompt_file.exists():
                prompt_file.unlink()

    print(f"[dispatch] Done. {spawned}/{len(context_keys)} subagents spawned.")
    klog("dispatch-complete", component="orchestrator",
         spawned=spawned, total=len(context_keys))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
