#!/usr/bin/env python3
"""
job-finder.py — Kamil's daily freelance job hunter.

Runs every 30 min via cron (same pattern as slack-poller).
Searches Upwork, RemoteOK, We Work Remotely, Freelancer for jobs
matching Kamal's stack. Deduplicates, scores, surfaces only new
high-quality matches. Saves to Notion Job Tracker. DMs Kamal.

Cron:
  */30 * * * * python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/job-finder.py >> /tmp/kamil-jobs.log 2>&1

Goal: Kamal buys a house. Kamil finds the clients.
"""

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_log import klog, klog_error
from kamil_eval_tracker import log_action

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_CONFIG  = Path.home() / ".claude" / "hooks" / ".slack"
JOBS_FILE     = Path("/tmp/kamil-jobs-seen.json")   # dedup store
STATE_FILE    = Path("/tmp/kamil-jobs-state.json")
LOG_FILE      = Path("/tmp/kamil-jobs.log")
KAMIL_DIR     = Path(__file__).parent.parent.parent

KAMAL_USER_ID = "U0AV1DX3WSE"
KAMAL_DM      = "D0B415M06SK"
JOBS_DB       = "0d69c6ff-83d8-44c7-94c2-d341c4ded8d7"

# Only DM jobs with score >= this
MIN_SCORE_TO_DM = 50

# Max jobs per DM to avoid noise
MAX_JOBS_PER_DM = 3

# Scoring weights
SCORE_WEIGHTS = {
    "django":       30,
    "python":       20,
    "react":        20,
    "typescript":   10,
    "ai agent":     35,
    "claude":       35,
    "anthropic":    35,
    "llm":          25,
    "automation":   20,
    "n8n":          15,
    "edtech":       15,
    "lms":          15,
    "education":    10,
    "rest api":     10,
    "fastapi":      15,
    "senior":       10,
}

SCORE_PENALTIES = {
    "wordpress":   -20,
    "php":         -20,
    "java ":       -15,
    "ruby":        -15,
    "ios":         -20,
    "android":     -20,
    "us only":     -10,
    "us citizen":  -30,
    "clearance":   -30,
}

LOW_BUDGET_PATTERNS = [
    r"\$[1-9]\b",           # $1-$9
    r"\$1[0-9]\b",          # $10-$19 hourly
    r"budget.*\$[1-9]\d\b", # budget under $100
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str):
    ts   = datetime.now().strftime("%H:%M:%S")
    line = f"[job-finder] {msg}"
    print(line, file=sys.stderr)


def load_config() -> dict:
    cfg = {}
    if SLACK_CONFIG.exists():
        for line in SLACK_CONFIG.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


def http_get(url: str, timeout: int = 15) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        log(f"GET failed {url[:60]}: {e}")
        return ""


def slack_post(token: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", data=data,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        log(f"Slack post failed: {e}")
        return {}


def load_seen() -> set:
    if JOBS_FILE.exists():
        try:
            return set(json.loads(JOBS_FILE.read_text()))
        except Exception:
            return set()
    return set()


def save_seen(seen: set):
    # Keep last 2000 URLs to avoid unbounded growth
    items = list(seen)[-2000:]
    JOBS_FILE.write_text(json.dumps(items))


def score_job(title: str, description: str, rate_text: str = "") -> int:
    text = (title + " " + description + " " + rate_text).lower()
    score = 0
    for kw, weight in SCORE_WEIGHTS.items():
        if kw in text:
            score += weight
    for kw, penalty in SCORE_PENALTIES.items():
        if kw in text:
            score += penalty  # penalty is negative
    # Low budget penalty
    for pattern in LOW_BUDGET_PATTERNS:
        if re.search(pattern, text):
            score -= 25
            break
    return max(0, min(100, score))


def detect_platform(url: str) -> str:
    if "upwork.com"    in url: return "upwork"
    if "remoteok.com"  in url: return "remoteok"
    if "weworkremotely" in url: return "weworkremotely"
    if "freelancer.com" in url: return "freelancer"
    if "linkedin.com"  in url: return "linkedin"
    return "other"


def extract_rate(text: str) -> str:
    """Try to find a rate or budget mention."""
    patterns = [
        r"\$\d+[\-–]\$?\d+\s*/\s*hr",
        r"\$\d+\s*/\s*hour",
        r"\$[\d,]+\s*(?:fixed|budget|total)",
        r"\$\d+[\-–]\d+k",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(0)
    return "Rate not listed"


# ── Job sources ───────────────────────────────────────────────────────────────

def fetch_upwork_rss(query: str) -> list[dict]:
    """Fetch jobs from Upwork RSS feed."""
    url = f"https://www.upwork.com/ab/feed/jobs/rss?q={urllib.parse.quote(query)}&sort=recency&paging=0%3B10"
    content = http_get(url)
    if not content:
        return []

    jobs = []
    try:
        root = ET.fromstring(content)
        ns   = {"atom": "http://www.w3.org/2005/Atom"}
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link", "").strip()
            desc  = item.findtext("description", "").strip()
            # Strip HTML tags from description
            desc  = re.sub(r"<[^>]+>", " ", desc)
            if title and link:
                jobs.append({
                    "title":       title,
                    "url":         link,
                    "description": desc[:500],
                    "platform":    "upwork",
                    "rate":        extract_rate(desc),
                })
    except ET.ParseError as e:
        log(f"Upwork RSS parse error ({query}): {e}")
    return jobs


def fetch_remoteok(tag: str) -> list[dict]:
    """Fetch jobs from RemoteOK JSON API."""
    url     = f"https://remoteok.com/remote-{urllib.parse.quote(tag)}-jobs.json"
    content = http_get(url)
    if not content:
        return []
    jobs = []
    try:
        data = json.loads(content)
        for item in data:
            if not isinstance(item, dict) or not item.get("position"):
                continue
            desc = " ".join(filter(None, [
                item.get("description", ""),
                item.get("tags", ""),
            ]))
            if isinstance(desc, list):
                desc = " ".join(desc)
            jobs.append({
                "title":       item.get("position", ""),
                "url":         item.get("url", f"https://remoteok.com/l/{item.get('id','')}"),
                "description": str(desc)[:500],
                "platform":    "remoteok",
                "rate":        item.get("salary", extract_rate(str(desc))),
                "company":     item.get("company", ""),
            })
    except (json.JSONDecodeError, Exception) as e:
        log(f"RemoteOK parse error ({tag}): {e}")
    return jobs


def fetch_weworkremotely(term: str) -> list[dict]:
    """Fetch jobs from We Work Remotely RSS."""
    url     = f"https://weworkremotely.com/remote-jobs/search.rss?term={urllib.parse.quote(term)}"
    content = http_get(url)
    if not content:
        return []
    jobs = []
    try:
        root = ET.fromstring(content)
        for item in root.findall(".//item"):
            title   = item.findtext("title", "").strip()
            link    = item.findtext("link", "").strip()
            desc    = item.findtext("description", "").strip()
            desc    = re.sub(r"<[^>]+>", " ", desc)
            company_region = re.split(r"\s*-\s*", title, maxsplit=2)
            clean_title = company_region[-1].strip() if len(company_region) > 1 else title
            if title and link:
                jobs.append({
                    "title":       clean_title,
                    "url":         link,
                    "description": desc[:500],
                    "platform":    "weworkremotely",
                    "rate":        extract_rate(desc),
                    "company":     company_region[0].strip() if len(company_region) > 1 else "",
                })
    except ET.ParseError as e:
        log(f"WWR parse error ({term}): {e}")
    return jobs


def fetch_freelancer_rss(skill: str) -> list[dict]:
    """Fetch from Freelancer.com RSS."""
    url     = f"https://www.freelancer.com/jobs/{urllib.parse.quote(skill)}.rss"
    content = http_get(url)
    if not content:
        return []
    jobs = []
    try:
        root = ET.fromstring(content)
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link", "").strip()
            desc  = item.findtext("description", "").strip()
            desc  = re.sub(r"<[^>]+>", " ", desc)
            if title and link:
                jobs.append({
                    "title":       title,
                    "url":         link,
                    "description": desc[:500],
                    "platform":    "freelancer",
                    "rate":        extract_rate(desc),
                })
    except ET.ParseError as e:
        log(f"Freelancer RSS parse error ({skill}): {e}")
    return jobs


# ── Notion write ──────────────────────────────────────────────────────────────

def save_job_to_notion(job: dict):
    """Write a new job to the Notion Job Tracker DB via Claude MCP."""
    today = datetime.now().strftime("%Y-%m-%d")
    props = {
        "Job Title":        job["title"][:200],
        "Company":          job.get("company", "")[:100],
        "Platform":         job["platform"],
        "Status":           "new",
        "Score":            job["score"],
        "Rate":             job.get("rate", "")[:100],
        "Why It Matches":   job.get("why", "")[:500],
        "Proposal Written": "no",
        "userDefined:URL":  job["url"][:500],
        "date:Date Found:start": today,
    }
    prompt = f"""Use mcp__claude_ai_Notion__notion-create-pages to add ONE page to DB {JOBS_DB}.
Properties:
{json.dumps(props, indent=2)}
Reply only "ok"."""

    env = os.environ.copy()
    env["KAMIL_JOB_PROMPT"] = prompt
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    subprocess.Popen(
        ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$KAMIL_JOB_PROMPT"'],
        cwd=str(KAMIL_DIR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


# ── Why it matches builder ────────────────────────────────────────────────────

def build_why(title: str, desc: str) -> str:
    text    = (title + " " + desc).lower()
    reasons = []
    if "django" in text:         reasons.append("Django")
    if "react" in text:          reasons.append("React")
    if "claude" in text or "anthropic" in text: reasons.append("Claude/AI")
    if "llm" in text or "ai agent" in text:     reasons.append("AI agents")
    if "automation" in text:     reasons.append("automation")
    if "edtech" in text or "lms" in text or "education" in text: reasons.append("EdTech")
    if "python" in text:         reasons.append("Python")
    if "typescript" in text:     reasons.append("TypeScript")
    if not reasons:              reasons.append("general backend/frontend")
    return "Matches: " + ", ".join(reasons)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    cfg       = load_config()
    bot_token = cfg.get("BOT_TOKEN") or os.environ.get("BOT_TOKEN")
    if not bot_token:
        log("No BOT_TOKEN — cannot DM Kamal.")
        return 1

    log("Starting job hunt...")
    seen = load_seen()

    # Fetch from all sources
    raw_jobs = []
    raw_jobs += fetch_upwork_rss("django react")
    raw_jobs += fetch_upwork_rss("django AI agent")
    raw_jobs += fetch_upwork_rss("Claude API developer")
    raw_jobs += fetch_upwork_rss("python automation LLM")
    raw_jobs += fetch_remoteok("django")
    raw_jobs += fetch_remoteok("python")
    raw_jobs += fetch_remoteok("ai")
    raw_jobs += fetch_weworkremotely("django")
    raw_jobs += fetch_weworkremotely("python")
    raw_jobs += fetch_freelancer_rss("django")

    log(f"Fetched {len(raw_jobs)} raw jobs from all sources")

    # Deduplicate by URL, score, filter
    new_jobs = []
    for job in raw_jobs:
        url = job.get("url", "").strip()
        if not url or url in seen:
            continue
        seen.add(url)

        score = score_job(job["title"], job.get("description", ""), job.get("rate", ""))
        if score < MIN_SCORE_TO_DM:
            continue

        job["score"] = score
        job["why"]   = build_why(job["title"], job.get("description", ""))
        job["company"] = job.get("company", "")
        new_jobs.append(job)

    # Sort by score descending
    new_jobs.sort(key=lambda j: j["score"], reverse=True)
    save_seen(seen)

    log(f"New qualifying jobs: {len(new_jobs)}")

    # Save all qualifying jobs to Notion (background)
    for job in new_jobs:
        save_job_to_notion(job)

    # Log to Axiom
    klog("job_finder_run",
         component="job-finder",
         raw_fetched=len(raw_jobs),
         new_qualifying=len(new_jobs),
         sources=["upwork", "remoteok", "weworkremotely", "freelancer"])

    # Only DM top N if there are new jobs
    dm_jobs = new_jobs[:MAX_JOBS_PER_DM]
    if not dm_jobs:
        log("No new qualifying jobs this run — skipping DM.")
        return 0

    # Build Slack DM
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"🏠 *Job Hunt — {today}* _(goal: house fund)_\n"]

    for i, job in enumerate(dm_jobs, 1):
        title   = job["title"][:80]
        company = f" — {job['company']}" if job.get("company") else ""
        rate    = job.get("rate", "Rate not listed")
        url     = job["url"]
        why     = job["why"]
        score   = job["score"]

        lines.append(f"*{i}. {title}{company}*")
        lines.append(f"   💰 {rate}  |  🎯 Score: {score}/100")
        lines.append(f"   ✅ {why}")
        lines.append(f"   🔗 {url}")
        lines.append("")

    lines.append('_Reply `apply 1`, `apply 2`, or `apply 3` → I\'ll write the proposal._')
    lines.append("🤖 Kamil")

    msg    = "\n".join(lines)
    result = slack_post(bot_token, {"channel": KAMAL_DM, "text": msg})

    if result.get("ok"):
        msg_ts = result.get("ts", "")
        log(f"DM sent with {len(dm_jobs)} jobs (top score: {dm_jobs[0]['score']})")
        # Eval: track this DM, watch for Kamal's "apply X" reaction
        log_action(
            action_type = "proactive-dm",
            event       = f"Job hunt DM: {len(dm_jobs)} new jobs",
            evidence    = f"Top job: {dm_jobs[0]['title']} | Score: {dm_jobs[0]['score']}",
            signal      = "sent",
            service     = "job-finder",
            channel     = KAMAL_DM,
            ts          = msg_ts,
        )
    else:
        log(f"DM failed: {result.get('error')}")

    # Update state
    STATE_FILE.write_text(json.dumps({
        "last_run":        datetime.now().isoformat(),
        "last_new_jobs":   len(new_jobs),
        "last_dm_jobs":    len(dm_jobs),
        "total_seen":      len(seen),
    }))

    return 0


if __name__ == "__main__":
    sys.exit(main())
