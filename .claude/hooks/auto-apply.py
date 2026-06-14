#!/usr/bin/env python3
"""
auto-apply.py — Varys applies for work autonomously.

Rules:
  score >= 75  → auto-apply immediately, DM Kamal confirmation
  score 60-74  → DM Kamal for approval, apply when he says "approve"
  score < 60   → skip

Channels:
  1. Email      — extract contact email from post, send via Gmail MCP
  2. GitHub     — comment on bounty issue with pitch
  3. LinkedIn   — OpenOutreach handles this separately

Every application is:
  - Logged to Notion Job Tracker (Status → "applied")
  - Logged to Axiom
  - Eval tracked (watches for response)

Called by job-finder.py after finding new qualifying jobs.
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_config import cfg
from varys_log import klog, klog_error
from varys_eval_tracker import log_action

VARYS_DIR   = Path(__file__).parent.parent.parent
KAMAL_DM    = os.environ.get("USER_SLACK_DM", "")  # set USER_SLACK_DM in ~/.agent-config.json
JOBS_DB     = "0d69c6ff-83d8-44c7-94c2-d341c4ded8d7"
SLACK_CFG   = Path.home() / ".claude" / "hooks" / ".slack"
APPLIED_FILE = Path("/tmp/varys-applied.jsonl")  # dedup — never apply twice

# Auto-apply threshold
AUTO_APPLY_SCORE   = 75
APPROVAL_NEEDED    = 60   # 60-74: ask {{USER_NAME}} first

_user_email = cfg("USER_EMAIL", "your-email@example.com")
USER_BIO = f"""{{USER_NAME}} — Fill in your bio
- Set USER_BIO_TEXT env var or edit this in auto-apply.py after /setup
- Your skills, experience, and portfolio
- GitHub: https://github.com/{{YOUR_GITHUB}}
- Email: {_user_email}"""


def load_token() -> str:
    if SLACK_CFG.exists():
        for line in SLACK_CFG.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def slack_dm(token: str, text: str) -> str:
    data = json.dumps({"channel": KAMAL_DM, "text": text}).encode()
    req  = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", data=data,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("ts", "")
    except Exception:
        return ""


def already_applied(url: str) -> bool:
    if not APPLIED_FILE.exists():
        return False
    return url in APPLIED_FILE.read_text()


def mark_applied(url: str, method: str, job_title: str):
    entry = json.dumps({"url": url, "method": method,
                        "title": job_title, "ts": datetime.now().isoformat()})
    with open(APPLIED_FILE, "a") as f:
        f.write(entry + "\n")


def run_claude(prompt: str, timeout: int = 120) -> str:
    env = os.environ.copy()
    env["VARYS_APPLY_PROMPT"] = prompt
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    result = subprocess.run(
        ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$VARYS_APPLY_PROMPT"'],
        capture_output=True, text=True, cwd=str(VARYS_DIR),
        timeout=timeout, env=env,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def extract_email(text: str) -> str | None:
    """Extract contact email from job post."""
    matches = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
    for m in matches:
        # Skip common non-contact emails
        if not any(skip in m.lower() for skip in ["noreply", "example", "reddit", "github"]):
            return m
    return None


def extract_github_issue(url: str) -> tuple[str, str, str] | None:
    """Extract owner/repo/issue_number from GitHub issue URL."""
    m = re.match(r'https://github\.com/([^/]+)/([^/]+)/issues/(\d+)', url)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None


def write_proposal(job: dict) -> str:
    """Generate a tailored proposal using Claude."""
    title       = job.get("title", "")
    description = job.get("description", "")
    source      = job.get("source", "")
    rate        = job.get("rate", "")

    prompt = f"""You are Varys writing a freelance proposal for Kamal.

JOB:
Title: {title}
Description: {description[:600]}
Source: {source}
Rate mentioned: {rate}

KAMAL'S BACKGROUND:
{USER_BIO}

Write a SHORT, tailored proposal (max 150 words). Rules:
- Open with ONE specific thing from the job description that matches Kamal's experience
- 2-3 bullet points of relevant proof (use real numbers from bio)
- Clear CTA: "Happy to jump on a quick call or send more details"
- Natural, human tone — not AI-sounding
- DO NOT mention being an AI
- Sign: "{{USER_NAME}} | {_user_email} | {{YOUR_PORTFOLIO}}"

Output ONLY the proposal text. No explanation, no preamble."""

    return run_claude(prompt, timeout=60)


def apply_via_email(job: dict, email: str, token: str) -> bool:
    """Send application email via Gmail MCP."""
    proposal = write_proposal(job)
    if not proposal:
        return False

    subject = f"Re: {job['title'][:80]}"

    prompt = f"""Use mcp__claude_ai_Gmail__create_draft to create an email draft:

To: {email}
Subject: {subject}
Body:
{proposal}

Then use the send endpoint to send it immediately.
Reply only "sent" when done."""

    result = run_claude(prompt, timeout=90)
    success = "sent" in result.lower() or "draft" in result.lower()

    if success:
        klog("auto_apply_email", component="auto-apply",
             job_title=job["title"][:80], email=email, score=job.get("score", 0))
        log_action("conversation", event=f"Applied via email: {job['title'][:60]}",
                   evidence=f"Sent to {email}", signal="sent", service="auto-apply",
                   channel=KAMAL_DM)
        slack_dm(token,
            f"✉️ *Applied (email):* {job['title'][:70]}\n"
            f"Sent to: `{email}`\n"
            f"Score: {job.get('score',0)}/100\n"
            f"🔗 {job['url'][:80]}\n🤖 Varys")

    return success


def apply_via_github(job: dict, token: str) -> bool:
    """Comment on GitHub bounty issue."""
    parsed = extract_github_issue(job["url"])
    if not parsed:
        return False

    owner, repo, issue_num = parsed
    proposal = write_proposal(job)
    if not proposal:
        return False

    # Post comment via GitHub API
    gh_token = os.environ.get("GITHUB_TOKEN", "")
    if not gh_token:
        # Try gh CLI
        result = subprocess.run(
            ["gh", "issue", "comment", issue_num,
             "--repo", f"{owner}/{repo}",
             "--body", proposal],
            capture_output=True, text=True,
        )
        success = result.returncode == 0
    else:
        data    = json.dumps({"body": proposal}).encode()
        url     = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_num}/comments"
        req     = urllib.request.Request(url, data=data, headers={
            "Authorization": f"Bearer {gh_token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                success = r.status == 201
        except Exception:
            success = False

    if success:
        klog("auto_apply_github", component="auto-apply",
             job_title=job["title"][:80], repo=f"{owner}/{repo}",
             issue=issue_num, score=job.get("score", 0))
        slack_dm(token,
            f"💬 *Applied (GitHub):* {job['title'][:70]}\n"
            f"Commented on: `{owner}/{repo}#{issue_num}`\n"
            f"Score: {job.get('score',0)}/100\n"
            f"🔗 {job['url']}\n🤖 Varys")

    return success


def update_notion_status(job_title: str, status: str = "applied"):
    """Update job status in Notion Job Tracker."""
    prompt = f"""Search the Notion Job Tracker DB ({JOBS_DB}) for a page with title containing "{job_title[:60]}".
Update its Status property to "{status}" and Proposal Written to "yes".
Reply only "ok"."""
    run_claude(prompt, timeout=60)


def process_job(job: dict, token: str) -> str:
    """
    Decide and execute the right apply action for a job.
    Returns: "applied", "pending_approval", "skipped"
    """
    url   = job.get("url", "")
    score = job.get("score", 0)
    title = job.get("title", "")
    desc  = job.get("description", "") + " " + title

    if already_applied(url):
        return "skipped"

    if score < APPROVAL_NEEDED:
        return "skipped"

    # Determine best apply method
    email  = extract_email(desc + " " + job.get("company", ""))
    is_gh  = bool(extract_github_issue(url))
    source = job.get("source", "")

    # Score 60-74: ask Kamal first
    if score < AUTO_APPLY_SCORE:
        method = "email" if email else ("github" if is_gh else "manual")
        slack_dm(token,
            f"🤔 *Approval needed:* {title[:70]}\n"
            f"Score: {score}/100 | Method: {method}\n"
            f"🔗 {url}\n"
            f'_Reply "approve" to apply, "skip" to pass._\n🤖 Varys')
        mark_applied(url, "pending", title)
        return "pending_approval"

    # Score >= 75: auto-apply
    applied = False

    if is_gh:
        applied = apply_via_github(job, token)
    elif email:
        applied = apply_via_email(job, email, token)
    else:
        # No direct contact — DM Kamal with ready-to-send proposal
        proposal = write_proposal(job)
        if proposal:
            slack_dm(token,
                f"📝 *Ready to apply (copy & paste):*\n"
                f"*{title[:70]}*\n"
                f"Score: {score}/100\n"
                f"🔗 {url}\n\n"
                f"```{proposal[:800]}```\n"
                f"🤖 Varys")
            applied = True

    if applied:
        mark_applied(url, "auto", title)
        update_notion_status(title, "applied")
        return "applied"

    return "skipped"


def run(jobs: list[dict], token: str) -> dict:
    """
    Process a list of new qualifying jobs.
    Returns stats: {applied, pending, skipped}
    """
    stats = {"applied": 0, "pending": 0, "skipped": 0}

    # Sort by score descending — apply to best first
    for job in sorted(jobs, key=lambda j: j.get("score", 0), reverse=True):
        result = process_job(job, token)
        stats[result] = stats.get(result, 0) + 1

    if stats["applied"] > 0 or stats["pending"] > 0:
        klog("auto_apply_run", component="auto-apply",
             applied=stats["applied"], pending=stats["pending"],
             skipped=stats["skipped"])

    return stats


if __name__ == "__main__":
    # Test with a sample job
    token = load_token()
    test_job = {
        "title": "Test: Senior Django Developer needed",
        "url":   "https://github.com/test/test/issues/1",
        "description": "We need a senior Django developer for our EdTech platform. Budget $50/hr. Contact: test@example.com",
        "score": 80,
        "source": "test",
        "rate":  "$50/hr",
    }
    print("Auto-apply test:")
    print(f"  Email found: {extract_email(test_job['description'])}")
    print(f"  GitHub issue: {extract_github_issue(test_job['url'])}")
    print(f"  Score: {test_job['score']} → {'auto-apply' if test_job['score'] >= AUTO_APPLY_SCORE else 'needs approval'}")
