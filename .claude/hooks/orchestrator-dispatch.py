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
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from varys_harness_db import get_db, get_linked_entities
from varys_notion import notion_request
try:
    from varys_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

NOTION_CFG  = Path.home() / ".claude" / "hooks" / ".notion"
SLACK_CFG   = Path.home() / ".claude" / "hooks" / ".slack"
HARNESS_CFG = Path.home() / ".varys-harness" / "config.json"
WORKSPACE   = Path.home() / ".varys-harness" / "workspace"
VARYS_DIR   = Path(__file__).parent.parent.parent

SKILLS_DIR  = VARYS_DIR / ".claude" / "commands"


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


def _fetch_bead(bead_id: str) -> dict:
    """Fetch a single bead by ID. Returns flat dict with title/status keys, or {}."""
    bd_bin = shutil.which("bd") or str(Path.home() / ".local" / "bin" / "bd")
    try:
        r = subprocess.run(
            [bd_bin, "show", bead_id, "--json"],
            capture_output=True, text=True,
            cwd=str(VARYS_DIR), timeout=10,
        )
        items = json.loads(r.stdout) if r.returncode == 0 else []
        return items[0] if items else {}
    except Exception:
        return {}


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
    # Bead format: flat dict with "title" key
    if "properties" not in page and "title" in page:
        return page["title"] or "Untitled"
    # Notion format: nested properties
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return "".join(p.get("plain_text", "") for p in prop.get("title", []))
    return "Untitled"


def _page_status(page: dict) -> str:
    # Bead format: flat dict with "status" key
    if "properties" not in page and "status" in page:
        return page["status"] or "Unknown"
    # Notion format: nested properties — Harness DB uses "Phase" (select), not "Status"
    props = page.get("properties", {})
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

    github_repo = cfg.get("GITHUB_REPO", "{{YOUR_GITHUB_ORG}}/{{YOUR_REPO}}")

    return f"""You are Varys, Taleemabad's AI engineer. You have been spawned to handle work.

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
             → post plan to Slack thread with "Reply @Varys go to proceed"
             → set Notion Status=Blocked → update session status='cancelled' in harness.db
             → exit (wait for human approval)
   - Step B: Only when triggered by "@Varys go" reply → implement per plan → run E2E tests
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
   → next @Varys reply will spawn a new session

HARNESS DB: {Path.home() / '.varys-harness' / 'harness.db'}
GITHUB REPO: {github_repo}
"""


def _spawn_manager(
    context_key: str,
    session_id: str,
    events: list,
    notion_page,
    slack_messages: list,
    github_pr,
) -> bool:
    """
    Spawn varys-manager.py Phase 1 instead of the old generic prompt.
    Writes context to temp JSON files, calls manager with --phase manager.
    Returns True on success.
    """
    import tempfile
    import shutil

    tmpdir = Path(tempfile.mkdtemp(prefix="varys-dispatch-"))
    try:
        events_file  = tmpdir / "events.json"
        notion_file  = tmpdir / "notion.json"
        slack_file   = tmpdir / "slack.json"
        github_file  = tmpdir / "github.json"

        events_file.write_text(json.dumps(events))
        notion_file.write_text(json.dumps(notion_page or {}))
        slack_file.write_text(json.dumps(slack_messages or []))
        github_file.write_text(json.dumps(github_pr or {}))

        manager_script = Path(__file__).parent / "varys-manager.py"
        nvm_source = (
            'export NVM_DIR="$HOME/.nvm"; '
            '[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
        )
        cmd = (
            f'{nvm_source} && python3 {manager_script} '
            f'--context-key "{context_key}" '
            f'--session-id "{session_id}" '
            f'--phase manager '
            f'--events-file "{events_file}" '
            f'--notion-page-file "{notion_file}" '
            f'--slack-msgs-file "{slack_file}" '
            f'--github-pr-file "{github_file}"'
        )
        result = subprocess.run(
            ["bash", "-c", cmd],
            cwd=str(VARYS_DIR),
            capture_output=True,
            text=True,
            timeout=180,
        )
        return result.returncode == 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> int:
    cfg = _load_config()
    api_key   = cfg.get("NOTION_API_KEY")
    bot_token = cfg.get("SLACK_BOT_TOKEN") or cfg.get("BOT_TOKEN")
    gh_token  = cfg.get("GITHUB_TOKEN")
    gh_repo   = cfg.get("GITHUB_REPO", "{{YOUR_GITHUB_ORG}}/{{YOUR_REPO}}")

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

        # Find beads entity for this context_key (preferred source)
        beads_row = db.execute(
            "SELECT external_id, url FROM entities WHERE id=? AND source='beads'",
            (context_key,),
        ).fetchone()

        if beads_row:
            bead_id = beads_row[0]
            try:
                bead_data = _fetch_bead(bead_id)
                if bead_data:
                    # Pass as notion_page arg so _spawn_manager signature stays unchanged
                    notion_page = bead_data
            except Exception as e:
                print(f"[dispatch] WARNING: could not fetch bead {bead_id}: {e}")
        else:
            # Backward compat: fall back to Notion entity for pre-migration events
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

        # ── Step 6: Dispatch via varys-manager.py ──

        # Check for go-signal — triggers Phase 2 worker
        go_events = [e for e in events if e["type"] == "message.go_signal"]
        if go_events:
            go_payload = go_events[0]["payload"]
            worker_session_id = go_payload.get("session_id")
            if worker_session_id:
                print(f"[dispatch] @Varys go received — spawning worker for session {worker_session_id[:16]}")
                nvm_source = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
                manager_script = VARYS_DIR / ".claude" / "hooks" / "varys-manager.py"
                cmd = (
                    f'{nvm_source} && python3 {manager_script} '
                    f'--context-key "{context_key}" '
                    f'--session-id "{worker_session_id}" '
                    f'--phase worker'
                )
                subprocess.run(["bash", "-c", cmd], cwd=str(VARYS_DIR),
                               capture_output=True, text=True, timeout=600)
                db.execute(
                    "UPDATE events SET status='done', processed_at=datetime('now') "
                    "WHERE context_key=? AND type='message.go_signal'",
                    (context_key,)
                )
                db.commit()
                continue  # Don't also run Phase 1 for this context_key

        title = _page_title(notion_page) if notion_page else context_key[:20]
        print(f"[dispatch] Spawning manager for: {title[:60]} ({event_types})")

        try:
            success = _spawn_manager(
                context_key=context_key,
                session_id=session_id,
                events=events,
                notion_page=notion_page,
                slack_messages=slack_messages,
                github_pr=github_pr,
            )
            if success:
                spawned += 1
                klog("dispatch-spawn", component="orchestrator",
                     session_id=session_id, context_key=context_key,
                     event_types=event_types)
            else:
                raise RuntimeError("manager process exited non-zero")

        except Exception as e:
            print(f"[dispatch] ERROR spawning manager for {context_key[:16]}: {e}",
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

    # ── Escalation broker: fire for stuck tickets ──
    try:
        broker_script = Path(__file__).parent / "escalation-broker.py"
        if broker_script.exists():
            subprocess.run(
                ["python3", str(broker_script)],
                cwd=str(VARYS_DIR), capture_output=True, text=True, timeout=60,
            )
    except Exception as e:
        print(f"[dispatch] escalation-broker check failed: {e}", file=sys.stderr)

    # ── Evolution agent: fire if 3+ new failures ──
    try:
        evo_script = Path(__file__).parent / "varys-evolution-agent.py"
        if evo_script.exists():
            subprocess.run(
                ["python3", str(evo_script)],
                cwd=str(VARYS_DIR), capture_output=True, text=True, timeout=60,
            )
    except Exception as e:
        print(f"[dispatch] evolution-agent check failed: {e}", file=sys.stderr)

    print(f"[dispatch] Done. {spawned}/{len(context_keys)} subagents spawned.")
    klog("dispatch-complete", component="orchestrator",
         spawned=spawned, total=len(context_keys))
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
