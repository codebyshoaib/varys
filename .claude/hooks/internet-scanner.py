#!/usr/bin/env python3
"""
internet-scanner.py — Scans the open internet for paid problems to solve.

Beyond job boards — finds people actively asking for help and willing to pay:
  - Reddit r/forhire, r/djangolearning, r/learnpython, r/webdev (HIRING posts)
  - HN "Who is Hiring?" monthly thread (Django/Python/AI entries)
  - GitHub issues with bounty labels
  - Remotive.com API (remote jobs with salaries)
  - Reddit r/entrepreneur, r/startups (technical help needed posts)

Called by job-finder.py every 30 min.
Returns list of job dicts compatible with job-finder scoring.
"""

import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from agent_config import cfg as _cfg_scanner
except Exception:
    _cfg_scanner = lambda k, d=None: d

HEADERS = {"User-Agent": f"KamilJobFinder/1.0 ({_cfg_scanner('USER_EMAIL', 'your-email@example.com')})"}

# Reddit subreddits to scan
HIRING_SUBS = [
    "forhire",          # [HIRING] and [FOR HIRE] posts
    "webdev",           # "looking for developer" posts
    "entrepreneur",     # "need a developer" posts
    "SideProject",      # "looking for technical co-founder / dev"
]

# Problem-solving subreddits (people stuck, willing to pay for fix)
HELP_SUBS = [
    "django",
    "learnpython",
    "reactjs",
    "aws",
]

# Keywords that signal someone will pay
PAID_SIGNALS = [
    "will pay", "paying", "paid", "budget", "hire", "hiring",
    "contract", "freelance", "bounty", "reward", "compensation",
    "$", "usd", "hourly", "fixed price", "help needed urgently",
    "need developer", "need engineer", "looking for developer",
]

# Keywords that signal it matches Kamal's stack
STACK_SIGNALS = [
    "django", "python", "react", "typescript", "aws", "terraform",
    "postgres", "postgresql", "redis", "celery", "docker",
    "rest api", "fastapi", "llm", "ai agent", "claude", "automation",
    "backend", "full stack", "fullstack", "edtech", "lms",
]


def http_get(url: str, headers: dict = None, timeout: int = 12) -> str:
    try:
        h = {**HEADERS, **(headers or {})}
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[internet-scanner] GET failed {url[:60]}: {e}", file=sys.stderr)
        return ""


def is_recent(utc_ts: float, hours: int = 1) -> bool:
    """True if timestamp is within last N hours."""
    try:
        return (datetime.utcnow() - datetime.utcfromtimestamp(utc_ts)).total_seconds() < hours * 3600
    except Exception:
        return False


def has_paid_signal(text: str) -> bool:
    text_l = text.lower()
    return any(s in text_l for s in PAID_SIGNALS)


def has_stack_signal(text: str) -> bool:
    text_l = text.lower()
    return any(s in text_l for s in STACK_SIGNALS)


def extract_rate(text: str) -> str:
    patterns = [
        r"\$\d+[\-–]\$?\d+\s*/\s*h(?:r|our)?",
        r"\$\d+\s*/\s*h(?:r|our)",
        r"\$[\d,]+\+?\s*(?:per\s+)?(?:hour|month|project|fixed)",
        r"\$[\d,k]+\s*(?:budget|total)",
        r"£[\d,k]+",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(0)
    return ""


# ── Sources ───────────────────────────────────────────────────────────────────

def scan_reddit_hiring() -> list[dict]:
    """Scan r/forhire and other subs for [HIRING] posts."""
    jobs = []
    for sub in HIRING_SUBS:
        url  = f"https://www.reddit.com/r/{sub}/new.json?limit=25&t=day"
        data = http_get(url)
        if not data:
            continue
        try:
            posts = json.loads(data)["data"]["children"]
        except Exception:
            continue

        for p in posts:
            post = p["data"]
            title  = post.get("title", "")
            body   = post.get("selftext", "")
            score  = post.get("score", 0)
            ts     = post.get("created_utc", 0)
            url_p  = f"https://reddit.com{post.get('permalink','')}"
            full   = f"{title} {body}"

            # Only want HIRING posts (not FOR HIRE)
            is_hiring = (
                "[hiring]" in title.lower()
                or "looking for" in title.lower()
                or "need a" in title.lower()
                or "need developer" in title.lower()
                or "need engineer" in title.lower()
                or (sub in ("entrepreneur", "SideProject") and has_paid_signal(full))
            )
            if not is_hiring:
                continue
            if not is_recent(ts, hours=48):  # last 48h
                continue
            if not has_stack_signal(full) and score < 5:
                continue

            rate = extract_rate(full)
            jobs.append({
                "title":       title[:120],
                "url":         url_p,
                "description": body[:400],
                "platform":    "other",
                "rate":        rate,
                "company":     f"r/{sub}",
                "source":      "reddit-hiring",
            })

    return jobs


def scan_reddit_problems() -> list[dict]:
    """Scan tech subs for problems people will pay to solve."""
    jobs = []
    for sub in HELP_SUBS:
        url  = f"https://www.reddit.com/r/{sub}/new.json?limit=25&t=day"
        data = http_get(url)
        if not data:
            continue
        try:
            posts = json.loads(data)["data"]["children"]
        except Exception:
            continue

        for p in posts:
            post  = p["data"]
            title = post.get("title", "")
            body  = post.get("selftext", "")
            ts    = post.get("created_utc", 0)
            full  = f"{title} {body}"
            url_p = f"https://reddit.com{post.get('permalink','')}"

            # Only posts with a paid signal
            if not has_paid_signal(full):
                continue
            if not is_recent(ts, hours=24):
                continue

            rate = extract_rate(full)
            jobs.append({
                "title":       f"[Problem] {title[:100]}",
                "url":         url_p,
                "description": body[:400],
                "platform":    "other",
                "rate":        rate,
                "company":     f"r/{sub}",
                "source":      "reddit-problem",
            })

    return jobs


def scan_hn_hiring() -> list[dict]:
    """Scan current HN Who's Hiring thread for Django/Python/AI entries."""
    jobs = []

    # Find the most recent Who's Hiring thread
    search_url = "https://hn.algolia.com/api/v1/search_by_date?query=Ask+HN+Who+is+hiring&tags=story&hitsPerPage=3"
    data = http_get(search_url)
    if not data:
        return []

    thread_id = None
    try:
        hits = json.loads(data)["hits"]
        for h in hits:
            if "who is hiring" in h.get("title", "").lower():
                thread_id = h["objectID"]
                break
    except Exception:
        return []

    if not thread_id:
        return []

    # Fetch comments mentioning our stack
    for keyword in ["django", "python ai", "react backend", "claude api"]:
        q = urllib.parse.quote(keyword)
        url  = f"https://hn.algolia.com/api/v1/search?query={q}&tags=comment,story_{thread_id}&hitsPerPage=10"
        data = http_get(url)
        if not data:
            continue
        try:
            hits = json.loads(data)["hits"]
        except Exception:
            continue

        for h in hits:
            text = re.sub(r"<[^>]+>", " ", h.get("comment_text") or "")
            if not text.strip():
                continue
            # Extract company/role from HN hiring format: "Company | Role | Location | ..."
            first_line = text.split("\n")[0][:120]
            rate       = extract_rate(text)
            hn_url     = f"https://news.ycombinator.com/item?id={h.get('objectID','')}"
            jobs.append({
                "title":       f"HN Hiring: {first_line}",
                "url":         hn_url,
                "description": text[:400],
                "platform":    "other",
                "rate":        rate,
                "company":     "HN Who's Hiring",
                "source":      "hn-hiring",
            })

    return jobs


def scan_github_bounties() -> list[dict]:
    """Scan GitHub for issues with bounty labels."""
    jobs = []
    queries = [
        "label:bounty+language:python+is:open",
        "label:bounty+django+is:open",
        "bounty+python+django+is:open+is:issue",
        "bounty+react+typescript+is:open+is:issue",
    ]
    for q in queries:
        url  = f"https://api.github.com/search/issues?q={urllib.parse.quote(q)}&sort=created&per_page=10"
        data = http_get(url, headers={"Accept": "application/vnd.github+json"})
        if not data:
            continue
        try:
            items = json.loads(data).get("items", [])
        except Exception:
            continue

        for item in items:
            title = item.get("title", "")
            body  = (item.get("body") or "")[:300]
            full  = f"{title} {body}"
            rate  = extract_rate(full)

            # Skip if no actual money signal
            if not has_paid_signal(full) and "$" not in full:
                continue

            jobs.append({
                "title":       f"[Bounty] {title[:100]}",
                "url":         item.get("html_url", ""),
                "description": body,
                "platform":    "other",
                "rate":        rate or "bounty",
                "company":     item.get("repository_url", "").split("/")[-1],
                "source":      "github-bounty",
            })

    return jobs


def scan_remotive() -> list[dict]:
    """Scan Remotive API for remote jobs with salary info."""
    jobs = []
    url  = "https://remotive.com/api/remote-jobs?category=software-dev&limit=50"
    data = http_get(url)
    if not data:
        return []
    try:
        items = json.loads(data).get("jobs", [])
    except Exception:
        return []

    for item in items:
        title       = item.get("title", "")
        description = re.sub(r"<[^>]+>", " ", item.get("description") or "")[:400]
        salary      = item.get("salary", "") or ""
        tags        = " ".join(item.get("tags") or [])
        full        = f"{title} {description} {tags}".lower()

        if not has_stack_signal(full):
            continue

        jobs.append({
            "title":       title[:120],
            "url":         item.get("url", ""),
            "description": description,
            "platform":    "other",
            "rate":        salary[:80] if salary else extract_rate(description),
            "company":     item.get("company_name", ""),
            "source":      "remotive",
        })

    return jobs


def scan_all() -> list[dict]:
    """Run all scanners, return combined results."""
    all_jobs = []

    results = [
        ("reddit-hiring",   scan_reddit_hiring),
        ("reddit-problems", scan_reddit_problems),
        ("hn-hiring",       scan_hn_hiring),
        ("github-bounties", scan_github_bounties),
        ("remotive",        scan_remotive),
    ]

    for name, fn in results:
        try:
            found = fn()
            print(f"[internet-scanner] {name}: {len(found)} items", file=sys.stderr)
            all_jobs.extend(found)
        except Exception as e:
            print(f"[internet-scanner] {name} error: {e}", file=sys.stderr)

    return all_jobs


if __name__ == "__main__":
    jobs = scan_all()
    print(f"\nTotal found: {len(jobs)}")
    for j in jobs[:5]:
        print(f"\n[{j['source']}] {j['title'][:70]}")
        print(f"  Rate: {j['rate'] or 'unknown'}")
        print(f"  URL: {j['url'][:70]}")
