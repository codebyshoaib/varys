#!/usr/bin/env python3
"""
openoutreach_job_signal_scraper.py — Scrape LinkedIn job postings for VA/admin/ops pain signals.

Searches LinkedIn Jobs public guest API (no auth needed) for job titles indicating
manual process pain: Virtual Assistant, Admin Assistant, Operations Coordinator, EA.
For each posting, extracts poster LinkedIn URL + job text as signal, then calls
inject() to write a lead into OpenOutreach DB.

State: /tmp/varys-oo-scraped-jobs.json (dedup store, persists across runs)
Called by job-finder.py every 30min.
"""

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from varys_log import klog, klog_error
except ImportError:
    def klog(event, **kw): pass
    def klog_error(context, exc, **kw): pass

STATE_FILE = Path("/tmp/varys-oo-scraped-jobs.json")
OPENOUTREACH_DB = Path.home() / ".openoutreach" / "data" / "db.sqlite3"
AUTOMATION_CAMPAIGN_NAME = "Automation Freelance Outreach"

PAIN_KEYWORDS = [
    "virtual assistant", "va needed", "va role",
    "admin assistant", "administrative assistant",
    "operations coordinator", "ops coordinator",
    "executive assistant", "ea needed",
    "personal assistant", "office manager",
    "data entry", "office administrator",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def get_campaign_id():
    if not OPENOUTREACH_DB.exists():
        return None
    import sqlite3
    conn = sqlite3.connect(str(OPENOUTREACH_DB))
    row = conn.execute(
        "SELECT id FROM linkedin_campaign WHERE name=?",
        (AUTOMATION_CAMPAIGN_NAME,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def extract_identifier(url: str):
    if not url:
        return None
    m = re.search(r"linkedin\.com/in/([^/?#]+)", url)
    if not m:
        return None
    return m.group(1).strip("/")


def is_pain_signal(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in PAIN_KEYWORDS)


def build_signal(job_title: str, job_text: str, company: str, job_url: str) -> dict:
    return {
        "source": "job_posting",
        "signal_text": job_text[:500],
        "job_title": job_title,
        "company": company,
        "job_post_url": job_url,
    }


def http_get(url: str, timeout: int = 10):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        klog_error("job-signal-scraper-http", e, url=url[:100])
        return None


def search_linkedin_jobs(keyword: str, start: int = 0) -> list:
    params = urllib.parse.urlencode({
        "keywords": keyword,
        "location": "United States",
        "start": start,
        "count": 10,
    })
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?{params}"
    html = http_get(url)
    if not html:
        return []

    job_ids   = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
    titles    = re.findall(r'class="base-search-card__title"[^>]*>\s*([^<]+)\s*<', html)
    companies = re.findall(r'class="base-search-card__subtitle"[^>]*>\s*<[^>]+>\s*([^<]+)\s*<', html)

    jobs = []
    for i, jid in enumerate(job_ids[:10]):
        title   = titles[i].strip()    if i < len(titles)    else ""
        company = companies[i].strip() if i < len(companies) else ""
        jobs.append({
            "job_id":     jid,
            "title":      title,
            "company":    company,
            "detail_url": f"https://www.linkedin.com/jobs/view/{jid}/",
        })
    return jobs


def get_poster_url(job_id: str):
    html = http_get(f"https://www.linkedin.com/jobs/view/{job_id}/")
    if not html:
        return None
    m = re.search(r'href="(https://www\.linkedin\.com/in/[^"?]+)"', html)
    return m.group(1) if m else None


def get_job_description(job_id: str) -> str:
    html = http_get(f"https://www.linkedin.com/jobs/view/{job_id}/")
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    m = re.search(r"(responsibilities|about the role|what you.ll do|job description)(.{50,800})", text, re.I)
    return m.group(0).strip() if m else text[500:1000]


def load_state() -> set:
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text()).get("seen_job_ids", []))
        except Exception:
            pass
    return set()


def save_state(seen: set):
    STATE_FILE.write_text(json.dumps({"seen_job_ids": list(seen)}, indent=2))


def run() -> int:
    if not OPENOUTREACH_DB.exists():
        return 0

    campaign_id = get_campaign_id()
    if campaign_id is None:
        klog("signal_scraper_no_campaign", component="job-signal-scraper",
             reason="Automation Freelance Outreach campaign not found in DB")
        return 0

    try:
        from openoutreach_signal_injector import inject
    except ImportError as e:
        klog_error("job-signal-scraper", e, reason="injector not found")
        return 0

    seen = load_state()
    injected = 0

    for keyword in [
        "virtual assistant",
        "admin assistant hiring",
        "operations coordinator small business",
        "executive assistant founder",
    ]:
        jobs = search_linkedin_jobs(keyword)
        time.sleep(2)

        for job in jobs:
            job_id = job["job_id"]
            if job_id in seen:
                continue

            if not is_pain_signal(job["title"]):
                seen.add(job_id)
                continue

            poster_url = get_poster_url(job_id)
            time.sleep(1)

            if not poster_url:
                seen.add(job_id)
                klog("signal_scraper_no_poster", component="job-signal-scraper",
                     job_id=job_id, title=job["title"])
                continue

            identifier = extract_identifier(poster_url)
            if not identifier:
                seen.add(job_id)
                continue

            description = get_job_description(job_id)
            time.sleep(1)

            signal = build_signal(
                job_title=job["title"],
                job_text=description or f"Hiring a {job['title']} — {job.get('company', '')}",
                company=job.get("company", ""),
                job_url=job["detail_url"],
            )

            result = inject(
                linkedin_url=f"https://www.linkedin.com/in/{identifier}/",
                public_identifier=identifier,
                campaign_id=campaign_id,
                signal=signal,
            )
            seen.add(job_id)

            if result["status"] == "inserted":
                injected += 1
                klog("signal_scraper_injected", component="job-signal-scraper",
                     job_id=job_id, title=job["title"], company=job.get("company", ""),
                     identifier=identifier, campaign_id=campaign_id)

    save_state(seen)
    klog("signal_scraper_run", component="job-signal-scraper",
         injected=injected)
    return injected


if __name__ == "__main__":
    count = run()
    print(f"[job-signal-scraper] {count} new leads injected", flush=True)
