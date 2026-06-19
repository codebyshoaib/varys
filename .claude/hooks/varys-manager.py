#!/usr/bin/env python3
"""
varys-manager.py — Varys's manager process.

Called by orchestrator-dispatch.py instead of the generic subagent prompt.

Two phases:
  Phase 1 (manager): read context + skills → pick agent → post plan → set awaiting_approval
  Phase 2 (worker):  spawned after @Varys go → execute with brief → synthesis pass

Usage:
  python3 varys-manager.py --context-key <entity_id> --session-id <session_id>
  python3 varys-manager.py --context-key <entity_id> --session-id <session_id> --phase worker
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from varys_harness_db import get_db, get_linked_entities
from varys_notion import notion_request
try:
    from varys_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

VARYS_DIR   = Path(__file__).parent.parent.parent
AGENTS_DIR  = VARYS_DIR / ".claude" / "agents"
SKILLS_DIR  = VARYS_DIR / ".claude" / "skills" / "varys"
RULES_DIR   = VARYS_DIR / ".claude" / "rules"
WORKSPACE   = Path.home() / ".varys-harness" / "workspace"
GAPS_LOG    = VARYS_DIR / ".beads" / "capability-gaps.jsonl"
SLACK_CFG   = Path.home() / ".claude" / "hooks" / ".slack"
NOTION_CFG  = Path.home() / ".claude" / "hooks" / ".notion"

# ponytail: when a ticket has no linked Slack origin thread, post to Shoaib's DM —
# never a public channel. chat.postMessage resolves a user ID to the DM channel.
SHOAIB_DM   = "U0AU07QRYJV"


def _load_cfg() -> dict:
    cfg = {}
    for f in (SLACK_CFG, NOTION_CFG):
        if f.exists():
            for line in f.read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    for key in ("NOTION_API_KEY", "SLACK_BOT_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(key):
            cfg[key] = os.environ[key]
    return cfg


def slack_post(bot_token: str, channel: str, text: str, thread_ts: str = None) -> dict:
    payload = {"channel": channel, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=data,
        headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _read_skill(name: str) -> str:
    path = SKILLS_DIR / f"{name}.md"
    return path.read_text() if path.exists() else ""


def _read_agent(name: str) -> str:
    path = AGENTS_DIR / f"{name}.md"
    return path.read_text() if path.exists() else ""


def _list_agents() -> list:
    return [f.stem for f in AGENTS_DIR.glob("*.md")] if AGENTS_DIR.exists() else []


def _append_skill(name: str, section: str, entry: str) -> None:
    path = SKILLS_DIR / f"{name}.md"
    if not path.exists():
        return
    content = path.read_text()
    marker = f"## {section}"
    if marker in content:
        idx = content.index(marker) + len(marker)
        content = content[:idx] + f"\n- [{datetime.now().strftime('%Y-%m-%d')}] {entry}" + content[idx:]
        path.write_text(content)


def run_manager_phase(context_key: str, session_id: str, events: list, notion_page: dict,
                      slack_messages: list, github_pr: dict, cfg: dict) -> None:
    """Phase 1: read context, pick agent, post plan, set awaiting_approval."""
    db = get_db()
    bot_token = cfg.get("SLACK_BOT_TOKEN") or cfg.get("BOT_TOKEN")

    routing   = _read_skill("routing")
    mgmt      = _read_skill("management")
    self_gaps = _read_skill("varys-self-gaps")
    agents    = _list_agents()

    # Find Slack thread for posting
    slack_channel, slack_thread_ts = None, None
    linked = get_linked_entities(db, context_key)
    for e in linked:
        if e["source"] == "slack":
            parts = e["external_id"].split("/")
            if len(parts) == 2:
                slack_channel, slack_thread_ts = parts
    # ponytail: no origin thread → DM Shoaib, never a public channel
    if not slack_channel:
        slack_channel, slack_thread_ts = SHOAIB_DM, None

    event_types = ", ".join(set(ev["type"] for ev in events))

    # Resolve ticket title and reference from either bead (flat) or Notion (nested) format
    ticket_title = "Unknown"
    ticket_ref   = ""
    if notion_page:
        if "properties" not in notion_page and "title" in notion_page:
            # Bead format: flat dict
            ticket_title = notion_page.get("title") or "Unknown"
            ticket_ref   = f"beads:{notion_page.get('id', '')}"
        else:
            # Notion format: nested properties
            props = notion_page.get("properties", {})
            for prop in props.values():
                if prop.get("type") == "title":
                    ticket_title = "".join(
                        p.get("plain_text", "") for p in prop.get("title", [])
                    )
                    break
            ticket_ref = notion_page.get("url", "")

    manager_prompt = f"""You are Varys, manager-orchestrator. You are running Phase 1.

TASK: Read the context below. Determine the real intent. Pick the right agent.
Write a delegation brief. Post the plan to Slack. DO NOT execute the work yourself.

CONTEXT KEY: {context_key}
SESSION ID: {session_id}
EVENTS: {event_types}
TICKET: {ticket_title}
REF: {ticket_ref}

SLACK THREAD CONTEXT:
{chr(10).join(f"  [{m.get('user','?')}]: {m.get('text','')[:200]}" for m in (slack_messages or [])[-10:])}

AVAILABLE AGENTS:
{chr(10).join(f"  - {a}" for a in agents)}

ROUTING SKILL:
{routing[:1500]}

MANAGEMENT SKILL:
{mgmt[:800]}

MY SELF-GAPS (avoid repeating these mistakes):
{self_gaps[:600]}

YOUR OUTPUT MUST BE A JSON OBJECT:
{{
  "real_intent": "one sentence: what is Shoaib/team actually trying to achieve?",
  "chosen_agent": "agent-name from the available list (or null if gap)",
  "repo": "repo key from registry (taleemabad-core / compliancetracker / etc) or null if not code work",
  "delegation_brief": "full brief for the worker: task, context, definition of done, constraints",
  "slack_plan_message": "message to post in the Slack thread — plan + who is handling it",
  "confidence": 85,
  "capability_gap": null
}}

ROUTING RULES:
- For ANY feature / bug / implementation / code task: chosen_agent = "product-lead", repo = the target repo
- product-lead runs the full pipeline: engineer → QA → code review → security. It handles all sub-delegation.
- For non-code tasks (content, research, Slack, Notion updates): use the specialist agent, repo = null.

confidence: 0-100. Your honest estimate of routing quality. If < 40, escalation-broker will be notified.
If no agent fits: set chosen_agent to null, explain in capability_gap.
Return ONLY the JSON object. No prose before or after."""

    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    prompt_file = Path(f"/tmp/varys-manager-p1-{session_id}.txt")
    prompt_file.write_text(manager_prompt)

    try:
        result = subprocess.run(
            ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$(cat {prompt_file})"'],
            capture_output=True, text=True, timeout=120,
            cwd=str(VARYS_DIR),
            # Manager decides routing only — the harness posts. Block any self-send.
            env={**os.environ, "VARYS_CONTENT_AGENT": "1"},
        )
        raw = result.stdout.strip()
        # Extract JSON from output
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        decision = json.loads(raw[start:end])
        # Schema validation (handoff-schemas.md)
        required = {"real_intent", "delegation_brief", "slack_plan_message", "confidence"}
        missing = required - set(decision.keys())
        if missing:
            raise ValueError(f"Manager Phase 1 output missing required fields: {missing}")
        if not decision.get("chosen_agent") and not decision.get("capability_gap"):
            raise ValueError("Manager Phase 1: both chosen_agent and capability_gap are null")
        agent_names = [f.stem for f in AGENTS_DIR.glob("*.md")]
        if decision.get("chosen_agent") and decision["chosen_agent"] not in agent_names:
            decision["capability_gap"] = f"Agent '{decision['chosen_agent']}' not found in agents dir"
            decision["chosen_agent"] = None
    except Exception as e:
        klog_error("manager-phase1-parse", e)
        db.execute("UPDATE sessions SET status='cancelled', updated_at=datetime('now') WHERE id=?", (session_id,))
        db.commit()
        db.close()
        return
    finally:
        if prompt_file.exists():
            prompt_file.unlink()

    # Handle capability gap
    if decision.get("capability_gap") and not decision.get("chosen_agent"):
        GAPS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(GAPS_LOG, "a") as f:
            f.write(json.dumps({
                "task_type": event_types,
                "what_was_missing": decision["capability_gap"],
                "how_handled": "no agent available",
                "timestamp": datetime.utcnow().isoformat(),
            }) + "\n")
        if bot_token and slack_channel:
            slack_post(bot_token, slack_channel,
                f"⚠️ I handled this but had no dedicated agent for it. "
                f"I improvised. Gap logged. Want me to build a skill/agent for: {decision['capability_gap'][:200]}? "
                f"Reply `yes build it` to proceed.\n\U0001f916 Varys",
                slack_thread_ts)
        db.execute("UPDATE sessions SET status='cancelled', updated_at=datetime('now') WHERE id=?", (session_id,))
        db.commit()
        db.close()
        return

    # Post Phase 1 plan to Slack
    if bot_token and slack_channel:
        plan_msg = (
            f"*Plan for: {ticket_title}*\n"
            f"{decision.get('slack_plan_message', '')}\n\n"
            f"_Delegating to: `{decision.get('chosen_agent')}`_\n"
            f"Reply `@Varys go` to proceed. \U0001f916 Varys"
        )
        slack_post(bot_token, slack_channel, plan_msg, slack_thread_ts)

    # Store decision in session for Phase 2
    db.execute(
        "UPDATE sessions SET status='awaiting_approval', phase='manager', "
        "intent=?, updated_at=datetime('now') WHERE id=?",
        (json.dumps(decision), session_id),
    )
    db.commit()
    db.close()
    klog("manager-phase1-complete", component="manager",
         session_id=session_id, agent=decision.get("chosen_agent"))


def run_worker_phase(context_key: str, session_id: str, cfg: dict) -> None:
    """Phase 2: spawn chosen worker agent, synthesise result, update skills."""
    db = get_db()
    bot_token = cfg.get("SLACK_BOT_TOKEN") or cfg.get("BOT_TOKEN")
    started_at = time.time()

    row = db.execute(
        "SELECT intent FROM sessions WHERE id=?", (session_id,)
    ).fetchone()
    if not row:
        print(f"[manager] Session {session_id} not found", file=sys.stderr)
        db.close()
        return

    decision = json.loads(row[0]) if row[0] else {}
    chosen_agent = decision.get("chosen_agent")
    brief        = decision.get("delegation_brief", "")
    real_intent  = decision.get("real_intent", "")
    repo_key     = decision.get("repo")


    # Resolve working directory
    registry = _load_registry()
    repo_info = registry.get(repo_key) if repo_key else None
    if repo_info and Path(repo_info["abs_path"]).exists():
        work_cwd = repo_info["abs_path"]
    elif WORKSPACE.exists():
        work_cwd = str(WORKSPACE)
    else:
        work_cwd = str(VARYS_DIR)

    agent_def = _read_agent(chosen_agent) if chosen_agent else ""
    slack_channel, slack_thread_ts = None, None
    linked = get_linked_entities(db, context_key)
    for e in linked:
        if e["source"] == "slack":
            parts = e["external_id"].split("/")
            if len(parts) == 2:
                slack_channel, slack_thread_ts = parts
    # ponytail: no origin thread → DM Shoaib, never a public channel
    if not slack_channel:
        slack_channel, slack_thread_ts = SHOAIB_DM, None

    # RULE: always sync the repo clone before any work (enforced for all agents with a repo)
    if repo_info and Path(repo_info["abs_path"]).exists() and chosen_agent != "product-lead":
        _base = repo_info.get("branch", "main")
        _git(work_cwd, "fetch", "origin", timeout=120)
        _git(work_cwd, "checkout", _base)
        _git(work_cwd, "reset", "--hard", f"origin/{_base}")

    # For product-lead: create a fresh branch in the target repo before running
    branch = None
    if chosen_agent == "product-lead" and repo_info:
        base   = repo_info.get("branch", "main")
        branch = f"varys/{_slugify(real_intent)}-{session_id[-6:]}"
        _git(work_cwd, "fetch", "origin", timeout=120)
        _git(work_cwd, "checkout", base)
        _git(work_cwd, "reset", "--hard", f"origin/{base}")
        co = _git(work_cwd, "checkout", "-b", branch)
        if co.returncode != 0:
            if bot_token and slack_channel:
                slack_post(bot_token, slack_channel,
                           f"⛔ Branch setup failed: {co.stderr[:200]}\n🤖 Varys", slack_thread_ts)
            db.execute("UPDATE sessions SET status='cancelled', updated_at=datetime('now') WHERE id=?",
                       (session_id,))
            db.execute("UPDATE events SET status='pending' WHERE context_key=? AND status='processing'",
                       (context_key,))
            db.commit(); db.close()
            klog("manager-branch-fail", component="manager", session_id=session_id, branch=branch)
            return

    # product-lead gets the pipeline invocation; all other agents get the standard brief
    if chosen_agent == "product-lead":
        worker_prompt = (
            "Invoke the product-lead skill and run the full pipeline for this task. "
            "The scope is pre-captured — skip Phase 1 scope dialogue. "
            "Use specialist subagents (senior-software-engineer, code-reviewer, qa-engineer, "
            "solutions-architect, ui-ux-designer, security-engineer) as the brief warrants. "
            "Do NOT commit or push — leave the diff unstaged.\n\n"
            f"TASK: {real_intent}\n\nBRIEF:\n{brief}\n\n"
            f"SESSION ID: {session_id}\nCONTEXT KEY: {context_key}\n\n"
            "When complete, return JSON: "
            '{"status":"done","summary":"...","pr_url":null,"files_changed":[],"phases_run":[]}'
        )
    else:
        worker_prompt = f"""You are Varys's {chosen_agent}. Execute the delegation brief below.

AGENT DEFINITION:
{agent_def[:2000]}

DELEGATION BRIEF:
{brief}

REAL INTENT: {real_intent}

HARNESS DB: {Path.home() / '.varys-harness' / 'harness.db'}
WORKSPACE: {work_cwd}
SESSION ID: {session_id}
CONTEXT KEY: {context_key}

Return a JSON object with your result. Structure depends on your agent type.
Every result must include: {{"status": "done|blocked", "summary": "what happened"}}"""

    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    model_flag = f"--model {repo_info['model']} " if repo_info and repo_info.get("model") else ""
    prompt_file = Path(f"/tmp/varys-worker-{session_id}.txt")
    prompt_file.write_text(worker_prompt)

    worker_result = {}
    try:
        result = subprocess.run(
            ["bash", "-c",
             f'{nvm} && claude --dangerously-skip-permissions {model_flag}--print -p "$(cat {prompt_file})"'],
            capture_output=True, text=True, timeout=1800,
            cwd=work_cwd,
            # Worker does the engineering (gh/git/code allowed) but NEVER posts to Slack —
            # the manager posts its result to the resolved channel. Block self-sends.
            env={**os.environ, "VARYS_CONTENT_AGENT": "1"},
        )
        raw = result.stdout.strip()
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start >= 0 and end > start:
            worker_result = json.loads(raw[start:end])
        else:
            worker_result = {"status": "done", "summary": raw[:500]}
    except Exception as e:
        klog_error("worker-phase-error", e, session_id=session_id)
        worker_result = {"status": "blocked", "summary": str(e)[:300]}
    finally:
        if prompt_file.exists():
            prompt_file.unlink()

    # For product-lead: commit changes, push, open PR
    if chosen_agent == "product-lead" and repo_info and branch and worker_result.get("status") == "done":
        if not _git(work_cwd, "status", "--porcelain").stdout.strip():
            worker_result = {"status": "blocked",
                             "summary": "product-lead produced no file changes — nothing to commit"}
        else:
            base = repo_info.get("branch", "main")
            _git(work_cwd, "add", "-A")
            _git(work_cwd, "commit", "-m",
                 f"feat: {real_intent[:60]}\n\nProduct-lead pipeline delivery. Session {session_id}.")
            ps = _git(work_cwd, "push", "-u", "origin", branch, timeout=180)
            if ps.returncode == 0:
                gh_env = {**os.environ,
                          "GH_TOKEN": cfg.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", ""))}
                pr_body = (
                    f"Autonomous delivery by Varys (product-lead pipeline).\n\n"
                    f"**Intent:** {real_intent}\n\n"
                    f"**Phases run:** {', '.join(worker_result.get('phases_run', []))}\n\n"
                    f"**Summary:**\n{worker_result.get('summary', '')[:800]}\n\n"
                    f"Review before merge."
                )
                pr = subprocess.run(
                    ["gh", "pr", "create", "--base", base, "--head", branch,
                     "--title", f"feat: {real_intent[:60]}", "--body", pr_body],
                    capture_output=True, text=True, timeout=120, cwd=work_cwd, env=gh_env,
                )
                if pr.returncode == 0 and pr.stdout.strip():
                    worker_result["pr_url"] = pr.stdout.strip().splitlines()[-1]
                else:
                    klog("manager-pr-fail", component="manager",
                         session_id=session_id, err=pr.stderr[:200])
            else:
                worker_result["summary"] = (
                    worker_result.get("summary", "") + f"\n[push failed: {ps.stderr[:100]}]"
                )

    duration_s = int(time.time() - started_at)
    success    = worker_result.get("status") == "done"
    pr_url     = worker_result.get("pr_url") or worker_result.get("deliverable")

    # Synthesis pass — quality check + skill update
    skill_name = _agent_to_skill(chosen_agent)
    if skill_name:
        if success:
            _append_skill(skill_name, "What Works",
                f"Agent {chosen_agent} handled '{real_intent[:80]}' successfully")
        else:
            _append_skill(skill_name, "What to Avoid",
                f"Agent {chosen_agent} blocked on '{real_intent[:80]}': {worker_result.get('summary','')[:100]}")

    # Post result to Slack thread
    if bot_token and slack_channel:
        if success:
            pr_line = f"\nPR: {pr_url}" if pr_url else ""
            msg = (
                f"✅ *Done: {real_intent[:100]}*{pr_line}\n"
                f"{worker_result.get('summary', '')[:400]}\n"
                f"_Session `{session_id}` · {duration_s}s_\n\U0001f916 Varys"
            )
        else:
            msg = (
                f"⛔ *Blocked: {real_intent[:100]}*\n"
                f"{worker_result.get('summary', '')[:400]}\n"
                f"\U0001f916 Varys"
            )
        slack_post(bot_token, slack_channel, msg, slack_thread_ts)

    final_status = "completed" if success else "cancelled"
    db.execute(
        "UPDATE sessions SET status=?, phase='synthesis', updated_at=datetime('now'), "
        "completed_at=datetime('now'), pr_url=? WHERE id=?",
        (final_status, pr_url, session_id),
    )
    db.execute(
        "UPDATE events SET status='done', processed_at=datetime('now') "
        "WHERE context_key=? AND status='processing'",
        (context_key,),
    )
    db.commit()

    # Notion: update harness ticket + create work log entry
    if success:
        _notion_log_session(db, context_key, session_id, real_intent, pr_url, duration_s, cfg)

    db.close()
    klog("manager-synthesis-complete", component="manager",
         session_id=session_id, success=success, pr=pr_url, duration_s=duration_s)


def _agent_to_skill(agent):
    mapping = {
        "research-agent": "research",
        "code-agent": "pr-review",
        "content-agent": "content-posting",
        "slack-agent": "slack-replies",
        "notion-agent": None,
        "people-agent": "helping-team",
        "product-lead": None,
    }
    return mapping.get(agent)


def _slugify(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_-]+", "-", s).strip("-")[:40]


def _git(cwd: str, *args, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, timeout=timeout, cwd=cwd
    )


def _load_registry() -> dict:
    """Return repos-registry.json as {key: {abs_path, branch, model, ...}}."""
    reg_path = RULES_DIR / "repos-registry.json"
    if not reg_path.exists():
        return {}
    data = json.loads(reg_path.read_text())
    return data.get("repos", data) if isinstance(data, dict) else {}


def _notion_log_session(
    db, context_key: str, session_id: str,
    real_intent: str, pr_url: str | None,
    duration_s: int, cfg: dict,
) -> None:
    """Write a Work Log entry to Notion. Notion is log-only — no ticket management."""
    api_key = cfg.get("NOTION_API_KEY", "")
    if not api_key:
        return
    work_log_db_id = cfg.get("NOTION_WORK_LOG_DB_ID", "37f902248f3d817890d2c70c1635bad9")
    today = datetime.now().strftime("%Y-%m-%d")
    pr_note = f"\nPR: {pr_url}" if pr_url else ""
    summary = f"{real_intent[:200]}{pr_note}\nDuration: {duration_s}s  Session: {session_id[-8:]}"
    body = {
        "parent": {"database_id": work_log_db_id},
        "properties": {
            "Date":       {"title": [{"text": {"content": f"{today} — {real_intent[:80]}"}}]},
            "Session ID": {"rich_text": [{"text": {"content": session_id}}]},
            "Summary":    {"rich_text": [{"text": {"content": summary[:2000]}}]},
        },
    }
    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Notion-Version": "2022-06-28",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        notion_request(req)
    except Exception as exc:
        klog("notion-worklog-fail", component="manager",
             session_id=session_id, error=str(exc)[:120])


def main() -> int:
    parser = argparse.ArgumentParser(description="Varys manager process")
    parser.add_argument("--context-key", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--phase", choices=["manager", "worker"], default="manager")
    parser.add_argument("--events-file",       default=None)
    parser.add_argument("--notion-page-file",  default=None)
    parser.add_argument("--slack-msgs-file",   default=None)
    parser.add_argument("--github-pr-file",    default=None)
    args = parser.parse_args()

    cfg = _load_cfg()

    if args.phase == "manager":
        events      = json.loads(Path(args.events_file).read_text())      if args.events_file      else []
        notion_page = json.loads(Path(args.notion_page_file).read_text()) if args.notion_page_file else None
        slack_msgs  = json.loads(Path(args.slack_msgs_file).read_text())  if args.slack_msgs_file  else []
        github_pr   = json.loads(Path(args.github_pr_file).read_text())   if args.github_pr_file   else None
        run_manager_phase(args.context_key, args.session_id, events,
                          notion_page, slack_msgs, github_pr, cfg)
    else:
        run_worker_phase(args.context_key, args.session_id, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
