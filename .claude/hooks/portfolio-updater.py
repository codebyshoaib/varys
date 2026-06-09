#!/usr/bin/env python3
"""
portfolio-updater.py — CV intelligence loop.

Runs weekly (Monday via kamil-weekly-report.sh).
Reads Notion Job Tracker → finds skills in demand → compares to portfolio.json
→ proposes updates → commits + pushes → logs to Notion history.

Every change is logged with:
  - What changed
  - Why (which jobs demanded this skill)
  - When
  - Outcome (did response rate improve after?)

Portfolio data repo: https://github.com/{{YOUR_GITHUB}}/portfolio-data
Portfolio website: https://{{YOUR_PORTFOLIO}}/
"""

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_log import klog, klog_error

PORTFOLIO_REPO   = Path.home() / "Documents" / "free_work" / "portfolio-data"
PORTFOLIO_JSON   = PORTFOLIO_REPO / "portfolio.json"
KAMIL_DIR        = Path(__file__).parent.parent.parent
JOBS_DB          = "0d69c6ff-83d8-44c7-94c2-d341c4ded8d7"
BRAIN_PAGE       = "364d8747-b3b1-813d-8ac8-c248800f0a4d"  # Agent Brain — replace with your Notion page ID
PLAN_PAGE        = "369d8747-b3b1-81d5-9775-dcb4297d7dbd"  # Master Plan page
HISTORY_FILE     = Path("/tmp/kamil-portfolio-history.jsonl")

SLACK_CONFIG     = Path.home() / ".claude" / "hooks" / ".slack"


def log(msg: str):
    print(f"[portfolio-updater] {msg}", flush=True)


def load_token() -> str:
    if SLACK_CONFIG.exists():
        for line in SLACK_CONFIG.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def run_git(cmd: list, cwd: Path) -> tuple[bool, str]:
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return result.returncode == 0, result.stdout + result.stderr


def slack_dm(token: str, text: str):
    data = json.dumps({"channel": os.environ.get("USER_SLACK_DM", ""), "text": text}).encode()
    req  = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", data=data,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def load_portfolio() -> dict:
    if not PORTFOLIO_JSON.exists():
        log(f"portfolio.json not found at {PORTFOLIO_JSON}")
        return {}
    return json.loads(PORTFOLIO_JSON.read_text())


def save_portfolio(data: dict):
    PORTFOLIO_JSON.write_text(json.dumps(data, indent=2))


def log_portfolio_change(change: str, reason: str, skills_added: list, skills_promoted: list):
    """Log every change with full context for history tracking."""
    entry = {
        "ts":              datetime.now().isoformat(),
        "change":          change,
        "reason":          reason,
        "skills_added":    skills_added,
        "skills_promoted": skills_promoted,
        "outcome":         "pending",  # updated when Kamal reports a win
    }
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def get_notion_job_skills(prompt_runner_fn) -> dict:
    """
    Ask Claude to query the Notion Job Tracker and extract skill frequency.
    Returns dict: {skill: count}
    """
    prompt = f"""Query the Notion Job Tracker DB (ID: {JOBS_DB}).
Read all entries where Status is 'new', 'applied', or 'interviewing'.
For each job, read the 'Why It Matches' and 'Job Title' fields.

Count how many times each skill/technology appears across all jobs:
- Django, Python, React, TypeScript, AWS, AI agents, Claude, LLM, automation,
  FastAPI, PostgreSQL, Docker, Terraform, EdTech, LMS, Redis, Celery, n8n,
  MCP, REST API, CI/CD, ECS, RabbitMQ, Kafka, GraphQL, Node.js

Output ONLY a JSON object like:
{{"Django": 12, "Python": 10, "AI agents": 8, "React": 6}}

No explanation, just the JSON."""

    result = prompt_runner_fn(prompt)
    try:
        # Extract JSON from result
        import re
        match = re.search(r'\{[^}]+\}', result, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception:
        pass
    return {}


def run_claude_prompt(prompt: str) -> str:
    """Run a Claude prompt and return output."""
    env = os.environ.copy()
    env["KAMIL_PORTFOLIO_PROMPT"] = prompt
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    result = subprocess.run(
        ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$KAMIL_PORTFOLIO_PROMPT"'],
        capture_output=True, text=True,
        cwd=str(KAMIL_DIR),
        timeout=120, env=env,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def analyse_and_update(portfolio: dict, job_skills: dict) -> list[dict]:
    """
    Compare job demand vs portfolio emphasis.
    Returns list of proposed changes with reasoning.
    """
    if not portfolio or not job_skills:
        return []

    changes = []
    skills_section = portfolio.get("skills", {})

    # Flatten current portfolio skills to a list
    current_skills = []
    for category, skill_list in skills_section.items():
        if isinstance(skill_list, list):
            current_skills.extend([s.lower() for s in skill_list])

    # Find high-demand skills not prominent in portfolio
    threshold = 3  # appears in 3+ jobs = worth adding/promoting
    for skill, count in sorted(job_skills.items(), key=lambda x: -x[1]):
        if count < threshold:
            continue
        skill_lower = skill.lower()
        in_portfolio = any(skill_lower in s for s in current_skills)

        if not in_portfolio:
            changes.append({
                "type":    "add",
                "skill":   skill,
                "count":   count,
                "reason":  f"Appears in {count} recent jobs but not in portfolio",
                "section": _guess_section(skill),
            })
        elif count >= 8:
            # High demand — ensure it's in a prominent position (first 3 in its category)
            changes.append({
                "type":    "promote",
                "skill":   skill,
                "count":   count,
                "reason":  f"High demand ({count} jobs) — ensure it's prominent",
                "section": _guess_section(skill),
            })

    return changes[:5]  # max 5 changes per run


def _guess_section(skill: str) -> str:
    skill_l = skill.lower()
    if skill_l in ("django", "python", "fastapi", "flask", "rest api"):
        return "Backend"
    if skill_l in ("react", "typescript", "node.js", "graphql"):
        return "Frontend"
    if skill_l in ("aws", "ecs", "terraform", "docker", "ci/cd", "redis"):
        return "AWS & Infrastructure"
    if skill_l in ("ai agents", "claude", "llm", "mcp", "automation", "n8n"):
        return "AI & Modern Development"
    if skill_l in ("postgresql", "elasticsearch", "kafka", "rabbitmq", "celery"):
        return "Databases"
    return "Engineering Practices"


def apply_changes(portfolio: dict, changes: list[dict]) -> tuple[dict, list[str]]:
    """Apply proposed changes to portfolio dict. Returns updated dict + summary."""
    summaries = []
    skills    = portfolio.get("skills", {})

    for change in changes:
        section = change["section"]
        skill   = change["skill"]

        if section not in skills:
            skills[section] = []

        if change["type"] == "add" and skill not in skills[section]:
            skills[section].append(skill)
            summaries.append(f"Added '{skill}' to {section} (appears in {change['count']} jobs)")

        elif change["type"] == "promote":
            # Move to front of section list
            lst = skills[section]
            if skill in lst:
                lst.remove(skill)
                lst.insert(0, skill)
                summaries.append(f"Promoted '{skill}' to top of {section} ({change['count']} job demand)")

    portfolio["skills"] = skills
    return portfolio, summaries


def commit_and_push(summaries: list[str]) -> bool:
    """Git commit portfolio.json and push to trigger Netlify redeploy."""
    if not PORTFOLIO_REPO.exists():
        log(f"Portfolio repo not found at {PORTFOLIO_REPO}")
        return False

    today   = datetime.now().strftime("%Y-%m-%d")
    message = f"kamil: cv update {today} — {'; '.join(summaries[:2])}"

    ok, out = run_git(["git", "add", "portfolio.json"], PORTFOLIO_REPO)
    if not ok:
        log(f"Git add failed: {out}")
        return False

    ok, out = run_git(["git", "commit", "-m", message], PORTFOLIO_REPO)
    if not ok:
        log(f"Git commit failed (maybe nothing to commit): {out}")
        return False

    ok, out = run_git(["git", "push", "origin", "main"], PORTFOLIO_REPO)
    if not ok:
        ok, out = run_git(["git", "push", "origin", "master"], PORTFOLIO_REPO)
    if not ok:
        log(f"Git push failed: {out}")
        return False

    log(f"Pushed portfolio update: {message}")
    return True


def log_to_notion_history(summaries: list[str], job_skills: dict, token: str):
    """Log the portfolio change to the Master Plan page history section."""
    today   = datetime.now().strftime("%Y-%m-%d")
    top_skills = ", ".join(f"{k}({v})" for k, v in
                           sorted(job_skills.items(), key=lambda x: -x[1])[:5])
    change_text = "; ".join(summaries) if summaries else "No changes needed"

    prompt = f"""Update the Notion page {PLAN_PAGE} (Freelance Outreach Master Plan).

Find the "Portfolio Version History" table in the page.
Add a new row to it with:
- Date: {today}
- What changed: {change_text[:150]}
- Why: Top job demand skills this week: {top_skills}
- Outcome: pending

Use mcp__claude_ai_Notion__notion-update-page with update_content command.
Find the table row format from existing rows and match it exactly.
Reply only "ok"."""

    env = os.environ.copy()
    env["KAMIL_NOTION_PROMPT"] = prompt
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    subprocess.Popen(
        ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$KAMIL_NOTION_PROMPT"'],
        cwd=str(KAMIL_DIR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def run():
    """Main entry point. Called by weekly report script."""
    token     = load_token()
    portfolio = load_portfolio()

    if not portfolio:
        log("Could not load portfolio.json — skipping")
        return

    log("Analysing job demand vs portfolio...")

    # Get skill frequency from Notion Job Tracker
    job_skills = get_notion_job_skills(run_claude_prompt)

    if not job_skills:
        log("No job skills data from Notion — skipping update")
        return

    log(f"Top demanded skills: {dict(list(sorted(job_skills.items(), key=lambda x: -x[1]))[:5])}")

    # Find and apply changes
    changes            = analyse_and_update(portfolio, job_skills)
    updated_portfolio, summaries = apply_changes(portfolio, changes)

    if not summaries:
        log("Portfolio already optimal for current job demand — no changes")
        klog("portfolio_check", component="portfolio-updater",
             changes=0, top_skills=dict(list(sorted(job_skills.items(), key=lambda x: -x[1])[:5])))
        if token:
            top = ", ".join(f"{k}({v})" for k, v in
                            sorted(job_skills.items(), key=lambda x: -x[1])[:5])
            slack_dm(token, f"📊 *Portfolio check:* No updates needed this week.\n"
                            f"Top demanded skills match your CV: {top}\n🤖 Kamil")
        return

    # Save updated portfolio.json
    save_portfolio(updated_portfolio)
    log(f"Portfolio updated: {summaries}")

    # Log to history file
    for summary in summaries:
        log_portfolio_change(
            change=summary,
            reason="Job demand analysis from Notion Job Tracker",
            skills_added=[c["skill"] for c in changes if c["type"] == "add"],
            skills_promoted=[c["skill"] for c in changes if c["type"] == "promote"],
        )

    # Commit and push
    pushed = commit_and_push(summaries)
    klog("portfolio_updated", component="portfolio-updater",
         changes=len(summaries), pushed=pushed,
         summaries=summaries,
         top_skills=dict(list(sorted(job_skills.items(), key=lambda x: -x[1])[:5])))

    # Log to Notion Master Plan history
    log_to_notion_history(summaries, job_skills, token)

    # DM Kamal
    if token:
        status = "✅ Pushed to GitHub — Netlify will redeploy in ~1 min" if pushed else "⚠️ Could not push (check portfolio repo)"
        changes_text = "\n".join(f"  • {s}" for s in summaries)
        top = ", ".join(f"{k}({v})" for k, v in
                        sorted(job_skills.items(), key=lambda x: -x[1])[:5])
        slack_dm(token,
            f"📝 *Portfolio updated based on job demand:*\n"
            f"{changes_text}\n\n"
            f"*Top demanded skills:* {top}\n"
            f"{status}\n"
            f"_Reply \"revert\" if you don't want this change._\n🤖 Kamil"
        )


if __name__ == "__main__":
    run()
