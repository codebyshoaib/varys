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
import subprocess
import sys
import urllib.request
import urllib.parse
from datetime import datetime
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

    event_types = ", ".join(set(ev["type"] for ev in events))
    notion_title = "Unknown"
    if notion_page:
        props = notion_page.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                notion_title = "".join(p.get("plain_text", "") for p in prop.get("title", []))
                break

    manager_prompt = f"""You are Varys, manager-orchestrator. You are running Phase 1.

TASK: Read the context below. Determine the real intent. Pick the right agent.
Write a delegation brief. Post the plan to Slack. DO NOT execute the work yourself.

CONTEXT KEY: {context_key}
SESSION ID: {session_id}
EVENTS: {event_types}
NOTION TICKET: {notion_title}
NOTION URL: {notion_page.get('url', '') if notion_page else ''}

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
  "real_intent": "one sentence: what is Kamal/team actually trying to achieve?",
  "chosen_agent": "agent-name from the available list (or null if gap)",
  "delegation_brief": "full brief for the worker: task, context, definition of done, constraints",
  "slack_plan_message": "message to post in the Slack thread — plan + who is handling it",
  "confidence": 85,
  "capability_gap": null
}}

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
            f"*Plan for: {notion_title}*\n"
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

    agent_def = _read_agent(chosen_agent) if chosen_agent else ""
    slack_channel, slack_thread_ts = None, None
    linked = get_linked_entities(db, context_key)
    for e in linked:
        if e["source"] == "slack":
            parts = e["external_id"].split("/")
            if len(parts) == 2:
                slack_channel, slack_thread_ts = parts

    worker_prompt = f"""You are Varys's {chosen_agent}. Execute the delegation brief below.

AGENT DEFINITION:
{agent_def[:2000]}

DELEGATION BRIEF:
{brief}

REAL INTENT: {real_intent}

HARNESS DB: {Path.home() / '.varys-harness' / 'harness.db'}
WORKSPACE: {WORKSPACE}
SESSION ID: {session_id}
CONTEXT KEY: {context_key}

Return a JSON object with your result. Structure depends on your agent type.
Every result must include: {{"status": "done|blocked", "summary": "what happened"}}"""

    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    prompt_file = Path(f"/tmp/varys-worker-{session_id}.txt")
    prompt_file.write_text(worker_prompt)

    worker_result = {}
    try:
        result = subprocess.run(
            ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$(cat {prompt_file})"'],
            capture_output=True, text=True, timeout=600,
            cwd=str(WORKSPACE) if WORKSPACE.exists() else str(VARYS_DIR),
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

    # Synthesis pass — quality check + skill update
    success = worker_result.get("status") == "done"
    skill_name = _agent_to_skill(chosen_agent)
    if skill_name:
        if success:
            _append_skill(skill_name, "What Works",
                f"Agent {chosen_agent} handled '{real_intent[:80]}' successfully")
        else:
            _append_skill(skill_name, "What to Avoid",
                f"Agent {chosen_agent} blocked on '{real_intent[:80]}': {worker_result.get('summary','')[:100]}")

    # Post synthesis to Slack
    if bot_token and slack_channel:
        if success:
            msg = (
                f"✅ *Done: {real_intent[:100]}*\n"
                f"{worker_result.get('summary', '')[:400]}\n"
                f"\U0001f916 Varys"
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
        "UPDATE sessions SET status=?, phase='synthesis', updated_at=datetime('now') WHERE id=?",
        (final_status, session_id),
    )
    db.execute(
        "UPDATE events SET status='done', processed_at=datetime('now') "
        "WHERE context_key=? AND status='processing'",
        (context_key,),
    )
    db.commit()
    db.close()
    klog("manager-synthesis-complete", component="manager",
         session_id=session_id, success=success)


def _agent_to_skill(agent):
    mapping = {
        "research-agent": "research",
        "code-agent": "pr-review",
        "content-agent": "content-posting",
        "slack-agent": "slack-replies",
        "notion-agent": None,
        "people-agent": "helping-team",
    }
    return mapping.get(agent)


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
