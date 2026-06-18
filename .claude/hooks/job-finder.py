#!/usr/bin/env python3
"""
job-finder.py — Varys's daily freelance job hunter.

Runs every 30 min via cron (same pattern as slack-poller).
Searches Upwork, RemoteOK, We Work Remotely, Freelancer for jobs
matching Shoaib's stack. Deduplicates, scores, surfaces only new
high-quality matches. Saves to Notion Job Tracker. DMs Shoaib.

Cron:
  */30 * * * * python3 .claude/hooks/job-finder.py >> /tmp/varys-jobs.log 2>&1

Goal: Shoaib buys a house. Varys finds the clients.
"""

import json
import os
import re
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_config import cfg
from varys_log import klog, klog_error
from varys_eval_tracker import log_action

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_CONFIG  = Path.home() / ".claude" / "hooks" / ".slack"
JOBS_FILE     = Path("/tmp/varys-jobs-seen.json")   # dedup store
STATE_FILE    = Path("/tmp/varys-jobs-state.json")
LOG_FILE      = Path("/tmp/varys-jobs.log")
VARYS_DIR     = Path(__file__).parent.parent.parent

SHOAIB_USER_ID = cfg("USER_SLACK_ID", "")
SHOAIB_DM      = os.environ.get("USER_SLACK_DM", "")  # set USER_SLACK_DM in ~/.agent-config.json
JOBS_DB       = "0d69c6ff-83d8-44c7-94c2-d341c4ded8d7"

# Only DM jobs with score >= this
# Baseline is 50, so 55+ means at least one relevant signal found
MIN_SCORE_TO_DM = 55

# Max jobs per DM to avoid noise
MAX_JOBS_PER_DM = 3

# Max 2 Claude subprocesses at a time — prevents OOM freeze on busy job runs
_NOTION_SEMA = threading.Semaphore(2)

# Scoring weights — Shoaib does ANY digital work (laptop or mobile)
# Higher score = better match. Baseline score = 50 for any remote digital job.
SCORE_WEIGHTS = {
    # AI / Claude — highest value work
    "claude":           35,
    "ai agent":         35,
    "anthropic":        35,
    "llm":              25,
    "langchain":        20,
    "openai":           20,
    "automation":       20,
    "machine learning": 20,
    "data engineering": 20,
    # Core dev stack
    "django":           25,
    "python":           20,
    "react":            20,
    "typescript":       15,
    "javascript":       15,
    "next.js":          15,
    "node":             15,
    "fastapi":          15,
    "rest api":         10,
    "api":              8,
    "scraping":         15,
    "n8n":              15,
    # DevOps / Cloud
    "docker":           15,
    "aws":              15,
    "terraform":        15,
    "kubernetes":       15,
    "devops":           15,
    "ci/cd":            10,
    "linux":            10,
    # Frontend
    "frontend":         12,
    "vue":              10,
    "css":              8,
    "html":             8,
    "ui":               8,
    "ux":               8,
    # Mobile / general digital
    "flutter":          12,
    "figma":            10,
    "wordpress":        8,
    "shopify":          10,
    "webflow":          10,
    "zapier":           12,
    "make.com":         12,
    "airtable":         10,
    "notion":           8,
    # Content / writing / VA
    "copywriting":      8,
    "content":          8,
    "social media":     8,
    "virtual assistant": 8,
    "data entry":       6,
    "transcription":    6,
    "video editing":    10,
    "thumbnail":        8,
    # Startup / co-founder / EIC
    "co-founder":       25,
    "cofounder":        25,
    "cto":              25,
    "eic":              25,
    "equity":           20,
    "technical lead":   20,
    "mvp":              15,
    "startup":          10,
    # Job signals
    "bot":              15,
    "script":           10,
    "crypto":           10,
    "bitcoin":          10,
    "bounty":           15,
    "remote":           5,
    "freelance":        5,
    "contract":         5,
    "paid":             5,
}

SCORE_PENALTIES = {
    # Hard blockers — genuinely can't do
    "us citizen":   -30,
    "clearance":    -30,
    "in-person":    -25,
    "on-site":      -25,
    "must relocate": -25,
    # Light penalties — possible but less ideal
    "us only":      -10,
    "full time only": -5,
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

    # Baseline: any remote/digital/freelance job starts at 50
    # Shoaib will do ANY work that needs a laptop or mobile
    score = 50

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
    """
    Fetch jobs from Upwork via their search page (RSS was retired in 2024).
    Uses the JSON search endpoint that the web app calls.
    """
    url = (
        "https://www.upwork.com/search/jobs/url?"
        f"q={urllib.parse.quote(query)}&sort=recency&per_page=10"
    )
    # Try the API endpoint Upwork uses internally
    api_url = (
        "https://www.upwork.com/ab/profiles/search/?"
        f"q={urllib.parse.quote(query)}&page=1&per=10"
    )
    # Upwork blocks scrapers hard — use their public GraphQL or fall back to
    # a curated job board that aggregates Upwork listings
    content = http_get(
        f"https://jobicy.com/feed/?s={urllib.parse.quote(query)}&job_type=remote"
    )
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
                    "platform":    "other",
                    "rate":        extract_rate(desc),
                })
    except ET.ParseError as e:
        log(f"Jobicy RSS parse error ({query}): {e}")
    return jobs


def fetch_jobicy(query: str) -> list[dict]:
    """Jobicy — aggregates remote jobs including many from Upwork clients."""
    url     = f"https://jobicy.com/feed/?s={urllib.parse.quote(query)}&job_type=remote"
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
                    "platform":    "other",
                    "rate":        extract_rate(desc),
                })
    except ET.ParseError as e:
        log(f"Jobicy RSS parse error ({query}): {e}")
    return jobs


def fetch_wwr_api(role: str) -> list[dict]:
    """We Work Remotely via their public job category pages (JSON-like)."""
    # WWR blocks RSS but has a public listing page
    url     = f"https://weworkremotely.com/categories/remote-{role}-jobs.rss"
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
            if title and link:
                jobs.append({
                    "title":       title,
                    "url":         link,
                    "description": desc[:500],
                    "platform":    "weworkremotely",
                    "rate":        extract_rate(desc),
                })
    except ET.ParseError as e:
        log(f"WWR RSS parse error ({role}): {e}")
    return jobs


def fetch_remoteok(tag: str) -> list[dict]:
    """Fetch jobs from RemoteOK API."""
    url     = f"https://remoteok.com/api?tag={urllib.parse.quote(tag)}"
    content = http_get(url)
    if not content:
        return []
    jobs = []
    try:
        data = json.loads(content)
        for item in data:
            if not isinstance(item, dict) or not item.get("position"):
                continue
            # tags is a list — join into string for scoring
            tags = item.get("tags", [])
            tags_str = " ".join(tags) if isinstance(tags, list) else str(tags)
            desc = f"{item.get('description', '')} {tags_str}".strip()
            jobs.append({
                "title":       item.get("position", ""),
                "url":         item.get("url", f"https://remoteok.com/l/{item.get('id','')}"),
                "description": desc[:500],
                "platform":    "remoteok",
                "rate":        str(item.get("salary", "")) or extract_rate(desc),
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
    env["VARYS_JOB_PROMPT"] = prompt
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'

    def _run():
        with _NOTION_SEMA:
            subprocess.Popen(
                ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$VARYS_JOB_PROMPT"'],
                cwd=str(VARYS_DIR), env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            ).wait()

    threading.Thread(target=_run, daemon=True).start()


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
        log("No BOT_TOKEN — cannot DM Shoaib.")
        return 1

    log("Starting job hunt...")

    # Check OpenOutreach for LinkedIn activity (runs silently if DB not present yet)
    try:
        from openoutreach_monitor import run as monitor_openoutreach
        oo_events = monitor_openoutreach(bot_token)
        if oo_events:
            log(f"OpenOutreach: {oo_events} new LinkedIn event(s)")
    except Exception as e:
        log(f"OpenOutreach monitor skipped: {e}")
    # Scrape LinkedIn job postings for VA/admin/ops pain signals → inject leads
    try:
        from openoutreach_job_signal_scraper import run as scrape_job_signals
        injected = scrape_job_signals()
        if injected:
            log(f"OpenOutreach signal scraper: {injected} new leads injected")
    except Exception as e:
        log(f"OpenOutreach signal scraper skipped: {e}")

    seen = load_seen()

    # ── Internet exploration (3-4 slots per 30-min run) ─────────────────────────
    internet_jobs = []
    try:
        from internet_scanner import scan_all as internet_scan_all
        from internet_scanner import scan_reddit_hiring, scan_remotive, scan_hn_hiring, scan_github_bounties, scan_reddit_problems

        # Load exploration queue and pick current slots (3-4 per run instead of 1)
        queue_file = Path(__file__).parent / "exploration-queue.json"
        if queue_file.exists():
            queue = json.loads(queue_file.read_text())
            slots = queue.get("slots", [])
            idx   = queue.get("current_index", 0) % len(slots)
            # Run 4 slots per pass for 5-6 hour full cycle
            slots_to_run = [slots[(idx + i) % len(slots)] for i in range(4)]

            log(f"Exploring {len(slots_to_run)} slots (indices {idx}-{(idx+3)%len(slots)})...")
        else:
            slots_to_run = []

        for slot in slots_to_run:
            log(f"  └─ {slot['name']}")

            for slot_idx, slot in enumerate(slots_to_run):
                slot_start = len(internet_jobs)

                # Route to correct scanner based on source
                source = slot.get("source", "")
                if source == "reddit" or source.startswith("reddit"):
                    sub   = slot.get("subreddit", "forhire")
                    hours = slot.get("hours", 48)
                    # Use generic reddit scan for this subreddit
                    from internet_scanner import http_get, has_paid_signal, has_stack_signal, extract_rate, is_recent
                    url  = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
                    data = http_get(url)
                    if data:
                        try:
                            posts = json.loads(data)["data"]["children"]
                            for p in posts:
                                post  = p["data"]
                                title = post.get("title", "")
                                body  = post.get("selftext", "")
                                ts    = post.get("created_utc", 0)
                                full  = f"{title} {body}"
                                url_p = f"https://reddit.com{post.get('permalink','')}"
                                if not is_recent(ts, hours=hours):
                                    continue
                                # Broad relevance — Shoaib is open to any work
                                slot_id = slot.get("id", "")
                                full_lower = full.lower()

                                # Startup/cofounder/EIC channels — look for opportunity signals
                                STARTUP_SLOTS = {
                                    "reddit_cofounder", "reddit_cofounderhunt", "reddit_findacofounder",
                                    "reddit_startup_ideas", "reddit_entrepreneur_eic", "reddit_startupninjas",
                                    "reddit_microsaas", "reddit_nocode_devneeded", "reddit_alphaandbeta",
                                    "reddit_indiehackers", "reddit_indiehackers_collabs", "reddit_SaaS",
                                    "reddit_sideproject", "reddit_EntrepreneurRideAlong",
                                }
                                # Micro-task channels — anything with a price
                                MICROTASK_SLOTS = {
                                    "reddit_slavelabour", "reddit_donedirtcheap", "reddit_hireforgigs",
                                    "reddit_hiringph", "reddit_jobs4bitcoin", "reddit_sidehustle",
                                }
                                # Broad tech channels — any technical work
                                BROAD_TECH_SLOTS = {
                                    "reddit_webdeveloperjobs", "reddit_pythonjobs", "reddit_remotepython",
                                    "reddit_javascriptjobs", "reddit_mljobs", "reddit_bigdatajobs",
                                    "reddit_developerjobs", "reddit_devopsjobs", "reddit_requestabot",
                                    "reddit_claudeai_builders", "reddit_aitools_builders",
                                    "reddit_gamedevclassifieds", "reddit_designjobs",
                                    "reddit_ecommerce_devneeded", "reddit_passive_income_tech",
                                    "reddit_freelance_forhire", "reddit_forhirefreelance",
                                    "reddit_developers_hire", "reddit_freelanceprogramming",
                                    "reddit_remotearmy", "reddit_jobs4bitcoin",
                                }

                                if slot_id in STARTUP_SLOTS:
                                    # For startup channels: look for founder/builder/technical signals
                                    is_relevant = any(w in full_lower for w in [
                                        "technical", "developer", "engineer", "cto", "cofounder",
                                        "co-founder", "build", "mvp", "equity", "looking for",
                                        "need help", "startup", "saas", "app", "website", "paid",
                                        "eic", "technical lead", "full stack", "backend", "python",
                                    ])
                                elif slot_id in MICROTASK_SLOTS:
                                    # For micro-task channels: anything with a price is relevant
                                    is_relevant = has_paid_signal(full) or "$" in full or "pay" in full_lower
                                elif slot_id in BROAD_TECH_SLOTS:
                                    # For tech boards: any hiring post
                                    is_relevant = (
                                        has_paid_signal(full) or
                                        "[hiring]" in title.lower() or
                                        "looking for" in full_lower or
                                        "need a" in full_lower or
                                        "hiring" in full_lower or
                                        "contract" in full_lower or
                                        "freelance" in full_lower or
                                        "remote" in full_lower
                                    )
                                else:
                                    # Default: paid signal + any tech mention
                                    is_relevant = (
                                        has_paid_signal(full) or
                                        "[hiring]" in title.lower() or
                                        "looking for" in title.lower() or
                                        "need a dev" in title.lower() or
                                        "need developer" in title.lower()
                                    )

                                if not is_relevant:
                                    continue

                                # Stack signal check — relaxed for startup/microtask channels
                                # No stack filter — Shoaib does any digital/remote work
                                internet_jobs.append({
                                    "title":       title[:120],
                                    "url":         url_p,
                                    "description": body[:400],
                                    "platform":    "other",
                                    "rate":        extract_rate(full),
                                    "company":     f"r/{sub}",
                                    "source":      f"reddit-{sub}",
                                })
                        except Exception as e:
                            log(f"Reddit parse error: {e}")

                elif source == "hn_hiring":
                    internet_jobs.extend(scan_hn_hiring())

                elif source == "github_bounty":
                    from internet_scanner import http_get
                    import urllib.parse as _up
                    q   = slot.get("query", "label:bounty+python+is:open+is:issue")
                    url = f"https://api.github.com/search/issues?q={_up.quote(q)}&sort=created&per_page=15"
                    data = http_get(url, headers={"Accept": "application/vnd.github+json"})
                    if data:
                        try:
                            items = json.loads(data).get("items", [])
                            from internet_scanner import extract_rate, has_paid_signal
                            for item in items:
                                title = item.get("title", "")
                                body  = (item.get("body") or "")[:300]
                                full  = f"{title} {body}"
                                rate  = extract_rate(full)
                                if not has_paid_signal(full) and "$" not in full:
                                    continue
                                internet_jobs.append({
                                    "title":       f"[Bounty] {title[:100]}",
                                    "url":         item.get("html_url", ""),
                                    "description": body,
                                    "platform":    "other",
                                    "rate":        rate or "bounty",
                                    "company":     item.get("repository_url","").split("/")[-1],
                                    "source":      "github-bounty",
                                })
                        except Exception as e:
                            log(f"GitHub bounty parse error: {e}")

                elif source in ("remotive", "remotive_ai"):
                    internet_jobs.extend(scan_remotive())

                elif source == "hn_ask":
                    # HN Ask threads needing help
                    data = http_get("https://hn.algolia.com/api/v1/search_by_date?query=django+python+help&tags=ask_hn&hitsPerPage=10")
                    if data:
                        try:
                            import re as _re
                            hits = json.loads(data).get("hits", [])
                            from internet_scanner import extract_rate
                            for h in hits:
                                text = h.get("title","") + " " + (h.get("story_text") or "")
                                if not any(kw in text.lower() for kw in ["paid","will pay","hire","bounty","$"]):
                                    continue
                                internet_jobs.append({
                                    "title":       h.get("title","")[:100],
                                    "url":         f"https://news.ycombinator.com/item?id={h.get('objectID','')}",
                                    "description": (h.get("story_text") or "")[:300],
                                    "platform":    "other",
                                    "rate":        extract_rate(text),
                                    "company":     "Hacker News",
                                    "source":      "hn-ask",
                                })
                        except Exception as e:
                            log(f"HN ask parse error: {e}")

                slot_found = len(internet_jobs) - slot_start
                log(f"  ✓ {slot['name']}: {slot_found} found")

        # Advance index for next run
        if slots_to_run:
            queue["current_index"] = (idx + len(slots_to_run)) % len(slots)
            queue_file.write_text(json.dumps(queue, indent=2))

    except Exception as e:
        log(f"Internet scanner error: {e}")

    # Fetch from all job board sources
    raw_jobs = []
    raw_jobs += internet_jobs  # add internet scan results
    # RemoteOK — works reliably via /api?tag=
    raw_jobs += fetch_remoteok("django")
    raw_jobs += fetch_remoteok("python")
    raw_jobs += fetch_remoteok("ai")
    raw_jobs += fetch_remoteok("react")
    raw_jobs += fetch_remoteok("backend")
    # Jobicy — aggregates remote jobs from many platforms
    raw_jobs += fetch_jobicy("django")
    raw_jobs += fetch_jobicy("python AI")
    raw_jobs += fetch_jobicy("react developer")
    raw_jobs += fetch_jobicy("AI automation")
    # We Work Remotely — by category
    raw_jobs += fetch_wwr_api("programming")
    raw_jobs += fetch_wwr_api("full-stack")
    # Freelancer.com RSS
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

    # ── Auto-apply to high-score jobs ─────────────────────────────────────────
    if new_jobs:
        try:
            from auto_apply import run as auto_apply_run
            apply_stats = auto_apply_run(new_jobs, bot_token)
            if apply_stats.get("applied", 0) or apply_stats.get("pending", 0):
                log(f"Auto-apply: {apply_stats['applied']} applied, "
                    f"{apply_stats['pending']} pending approval, "
                    f"{apply_stats['skipped']} skipped")
        except Exception as e:
            log(f"Auto-apply error: {e}")

    # What internet slots were explored this run
    slots_explored = ""
    try:
        queue_file = Path(__file__).parent / "exploration-queue.json"
        if queue_file.exists():
            q     = json.loads(queue_file.read_text())
            slots = q.get("slots", [])
            start_idx = (q.get("current_index", 1) - 4) % len(slots)
            explored = [slots[(start_idx + i) % len(slots)]["name"] for i in range(4)]
            slots_explored = " + ".join(explored)
    except Exception:
        pass

    # Log to Axiom
    klog("job_finder_run",
         component="job-finder",
         raw_fetched=len(raw_jobs),
         new_qualifying=len(new_jobs),
         internet_found=len(internet_jobs),
         slots_explored_count=4,
         slots_explored=slots_explored)

    # Only DM top N if there are new jobs
    dm_jobs = new_jobs[:MAX_JOBS_PER_DM]
    if not dm_jobs:
        # Still tell Shoaib what we explored
        if slot_name:
            slack_post(bot_token, {"channel": SHOAIB_DM,
                "text": f"🔍 *Explored:* {slot_name}\n_No new qualifying work found this pass. Back in 30 min._\n🤖 Varys"})
        log("No new qualifying jobs this run — skipping DM.")
        return 0

    # Build Slack DM
    today = datetime.now().strftime("%Y-%m-%d")
    time_now = datetime.now().strftime("%H:%M")
    lines = [f"🏠 *{time_now} — Found work ({slot_name or 'job boards'})*\n"]

    for i, job in enumerate(dm_jobs, 1):
        title   = job["title"][:80]
        company = f" — {job['company']}" if job.get("company") else ""
        rate    = job.get("rate") or "Rate not listed"
        url     = job["url"]
        why     = job["why"]
        score   = job["score"]
        src     = job.get("source", "")

        # Source emoji
        src_emoji = "🌐" if src.startswith("reddit") or src in ("hn-hiring","github-bounty","hn-ask") else "📋"

        lines.append(f"*{i}. {src_emoji} {title}{company}*")
        lines.append(f"   💰 {rate}  |  🎯 {score}/100")
        lines.append(f"   ✅ {why}")
        lines.append(f"   🔗 {url}")
        lines.append("")

    lines.append('_Reply `apply 1`, `apply 2`, or `apply 3` → I\'ll write the proposal._')
    lines.append("🤖 Varys")

    msg    = "\n".join(lines)
    result = slack_post(bot_token, {"channel": SHOAIB_DM, "text": msg})

    if result.get("ok"):
        msg_ts = result.get("ts", "")
        log(f"DM sent with {len(dm_jobs)} jobs (top score: {dm_jobs[0]['score']})")
        # Eval: track this DM, watch for Shoaib's "apply X" reaction
        log_action(
            action_type = "proactive-dm",
            event       = f"Job hunt DM: {len(dm_jobs)} new jobs",
            evidence    = f"Top job: {dm_jobs[0]['title']} | Score: {dm_jobs[0]['score']}",
            signal      = "sent",
            service     = "job-finder",
            channel     = SHOAIB_DM,
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
