# OpenOutreach Signal-First Outreach Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace generic LinkedIn outreach messages with signal-first PAS messages built from real job-posting pain indicators, running fully automatically until a prospect replies.

**Architecture:** A new `Automation Freelance Outreach` campaign row is inserted into OpenOutreach's SQLite DB with a PAS-structured objective. A new `openoutreach-job-signal-scraper.py` script scrapes LinkedIn job postings every 30 min for "hiring VA/admin/ops/EA" signals, passes each poster's LinkedIn URL + job post text to `openoutreach-signal-injector.py`, which writes enriched `crm_lead` + `crm_deal` rows (with `profile_summary` pre-populated with signal JSON). The existing OpenOutreach AI follow-up agent reads `profile_summary` when composing connection requests — so the signal flows into the message with zero changes to OpenOutreach internals. The existing `openoutreach_monitor.py` gets a minor upgrade: when it detects a reply it includes the full conversation context in the Kamal DM.

**Tech Stack:** Python 3, SQLite3 (`~/.openoutreach/data/db.sqlite3`), Playwright (already installed by OpenOutreach), `urllib.request` for HTTP, existing `kamil_log` + `kamil_eval_tracker` utilities from `.claude/hooks/`.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `.claude/hooks/openoutreach-job-signal-scraper.py` | Scrapes LinkedIn job posts for VA/admin/ops hiring signals every 30min; calls injector |
| Create | `.claude/hooks/openoutreach-signal-injector.py` | Writes signal-enriched `crm_lead` + `crm_deal` rows into OpenOutreach DB |
| Modify | `.claude/hooks/openoutreach_monitor.py` | Add full conversation context to reply DMs so Kamal can take over informed |
| Modify | `.claude/hooks/job-finder.py` | Add scraper call alongside existing `monitor_openoutreach` call |
| Create | `tests/test_signal_injector.py` | Unit tests for injector dedup logic and profile_summary shape |
| Create | `tests/test_job_signal_scraper.py` | Unit tests for signal extraction and URL parsing |

---

## Task 1: Insert the new campaign into OpenOutreach DB

**Files:**
- No new file — one-time SQL insert run as a script step

- [ ] **Step 1: Write the campaign insert script inline**

```python
# run once: python3 -c "$(cat <<'EOF'
import sqlite3, json
from pathlib import Path

DB = Path.home() / ".openoutreach" / "data" / "db.sqlite3"
conn = sqlite3.connect(str(DB))
cur = conn.cursor()

PRODUCT_DOCS = """Muhammad Kamal builds AI agents and workflow automations for non-technical business owners.

WHAT HE BUILDS:
- Workflow automations: connect existing tools (CRM, email, spreadsheets, calendars) to eliminate manual steps
- AI agents: autonomous agents that handle lead follow-up, inbox triage, report generation, onboarding
- Assessment → build: he audits your ops first, then builds whatever combo removes the most pain

RESULTS DELIVERED:
- Saved one agency owner 10 hrs/week on client reporting
- Automated lead qualification pipeline for a real estate broker
- Built AI inbox triage that cut response time from 4 hrs to 15 min

AVAILABILITY: Freelance, remote. Fixed-scope projects $800–4000. Monthly retainer available.
BOOKING: https://oykamal.netlify.app/
GITHUB: https://github.com/oyekamal"""

CAMPAIGN_OBJECTIVE = """TARGET: Non-technical business owners and operators who are actively hiring someone to do manual, repetitive work — this is a real-time pain signal.

SIGNAL SOURCES:
1. LinkedIn job postings: they posted a job for VA, admin assistant, operations coordinator, executive assistant, data entry, or similar — that job post IS the pain signal
2. LinkedIn profiles: headline or about section mentions "doing everything myself", "wearing many hats", or recent post about being overwhelmed with admin

MESSAGE STRUCTURE (PAS — Problem-Agitate-Solution, under 4 sentences, NO questions):
1. Hook — reference the specific signal (job title from posting, or specific task they mentioned)
2. Problem — name the pain concretely (the task they're hiring for is usually 80% automatable)
3. Bridge — one sentence: what you do + one concrete outcome from a past client
4. CTA — single zero-friction ask: "Happy to send a 60-sec demo if useful."

EXAMPLE (job posting signal — hiring VA):
"[Name] — saw you're hiring a virtual assistant to handle [task from job post]. Before you onboard someone — that kind of work is usually 80% automatable with a small AI agent. Saved one [similar business type] 10 hrs/week doing exactly this. Happy to send a 60-sec demo if useful."

EXAMPLE (profile signal — overwhelmed founder):
"[Name] — your post about [specific thing they said] resonated. That's exactly the kind of work I automate. Built a system last month that handled this for a [similar business]. 60-sec demo if useful?"

WHAT NOT TO DO:
- Never open with a question ("How do you handle X?" signals salesperson)
- Never use "founder teams usually" — too generic, signals template
- Never pitch features — pitch a concrete outcome from a real client
- Never use "I noticed" — say what you saw specifically

TARGETING: US, UK, Canada, Australia, UAE, or remote-first. Company size 1–30 people. Non-technical operator roles only (not CTOs or engineers)."""

cur.execute("""
    INSERT OR IGNORE INTO linkedin_campaign
        (name, product_docs, campaign_objective, booking_link, is_freemium,
         action_fraction, seed_public_ids)
    VALUES (?, ?, ?, ?, 0, 0.8, '[]')
""", ("Automation Freelance Outreach", PRODUCT_DOCS, CAMPAIGN_OBJECTIVE,
      "https://oykamal.netlify.app/"))

conn.commit()
cur.execute("SELECT id, name FROM linkedin_campaign WHERE name='Automation Freelance Outreach'")
row = cur.fetchone()
print(f"Campaign ID: {row[0]}, Name: {row[1]}")
conn.close()
# EOF
# )"
```

- [ ] **Step 2: Run the insert and note the campaign ID**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "
import sqlite3, json
from pathlib import Path

DB = Path.home() / '.openoutreach' / 'data' / 'db.sqlite3'
conn = sqlite3.connect(str(DB))
cur = conn.cursor()

PRODUCT_DOCS = '''Muhammad Kamal builds AI agents and workflow automations for non-technical business owners.

WHAT HE BUILDS:
- Workflow automations: connect existing tools (CRM, email, spreadsheets, calendars) to eliminate manual steps
- AI agents: autonomous agents that handle lead follow-up, inbox triage, report generation, onboarding
- Assessment + build: he audits your ops first, then builds whatever combo removes the most pain

RESULTS DELIVERED:
- Saved one agency owner 10 hrs/week on client reporting
- Automated lead qualification pipeline for a real estate broker
- Built AI inbox triage that cut response time from 4 hrs to 15 min

AVAILABILITY: Freelance, remote. Fixed-scope projects 800-4000 USD. Monthly retainer available.
BOOKING: https://oykamal.netlify.app/'''

CAMPAIGN_OBJECTIVE = '''TARGET: Non-technical business owners and operators who are actively hiring someone to do manual, repetitive work.

MESSAGE STRUCTURE (PAS, under 4 sentences, NO questions):
1. Hook: reference the specific signal (job title from posting or specific task they mentioned)
2. Problem: name the pain (the task they are hiring for is usually 80% automatable)
3. Bridge: one concrete outcome from a past client
4. CTA: Happy to send a 60-sec demo if useful.

EXAMPLE:
[Name] — saw you are hiring a virtual assistant to handle [task from job post]. Before you onboard someone — that kind of work is usually 80% automatable with a small AI agent. Saved one agency owner 10 hrs/week doing exactly this. Happy to send a 60-sec demo if useful.

WHAT NOT TO DO: Never open with a question. Never use founder teams usually. Never pitch features.'''

cur.execute(
    \"INSERT OR IGNORE INTO linkedin_campaign (name, product_docs, campaign_objective, booking_link, is_freemium, action_fraction, seed_public_ids) VALUES (?, ?, ?, ?, 0, 0.8, '[]')\",
    ('Automation Freelance Outreach', PRODUCT_DOCS, CAMPAIGN_OBJECTIVE, 'https://oykamal.netlify.app/')
)
conn.commit()
cur.execute(\"SELECT id, name FROM linkedin_campaign WHERE name='Automation Freelance Outreach'\")
row = cur.fetchone()
print(f'Campaign ID: {row[0]}, Name: {row[1]}')
conn.close()
"
```

Expected output: `Campaign ID: <N>, Name: Automation Freelance Outreach` — note the ID, you'll use it in Task 2.

- [ ] **Step 3: Verify the row exists**

```bash
sqlite3 ~/.openoutreach/data/db.sqlite3 "SELECT id, name, substr(campaign_objective,1,100) FROM linkedin_campaign WHERE name='Automation Freelance Outreach';"
```

Expected: one row with the campaign name and first 100 chars of objective visible.

- [ ] **Step 4: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add -p  # nothing to stage — this was a DB change, no file changed
# No commit needed for this task — DB change only
echo "Campaign inserted."
```

---

## Task 2: Write `openoutreach-signal-injector.py`

**Files:**
- Create: `.claude/hooks/openoutreach-signal-injector.py`
- Test: `tests/test_signal_injector.py`

This script takes a LinkedIn URL + signal dict and writes a `crm_lead` + `crm_deal` row. It is idempotent — running it twice for the same URL does nothing (UNIQUE constraint on `crm_lead.linkedin_url`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_signal_injector.py`:

```python
"""Tests for openoutreach-signal-injector.py"""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

# Point imports at hooks dir
sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))

import importlib.util, types

def load_injector(db_path: str):
    """Load injector module with DB path override."""
    spec = importlib.util.spec_from_file_location(
        "injector",
        Path(__file__).parent.parent / ".claude" / "hooks" / "openoutreach-signal-injector.py"
    )
    mod = importlib.util.module_from_spec(spec)
    mod.OPENOUTREACH_DB = Path(db_path)
    spec.loader.exec_module(mod)
    return mod


def make_test_db(path: str):
    """Create minimal OpenOutreach schema for testing."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE crm_lead (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            linkedin_url VARCHAR(200) NOT NULL UNIQUE,
            public_identifier VARCHAR(200) NOT NULL UNIQUE,
            embedding BLOB,
            disqualified BOOL NOT NULL DEFAULT 0,
            creation_date DATETIME NOT NULL,
            update_date DATETIME NOT NULL,
            urn VARCHAR(200) UNIQUE
        );
        CREATE TABLE crm_deal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state VARCHAR(20) NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            connect_attempts INTEGER NOT NULL DEFAULT 0,
            backoff_hours INTEGER NOT NULL DEFAULT 0,
            creation_date DATETIME NOT NULL,
            update_date DATETIME NOT NULL,
            campaign_id BIGINT NOT NULL,
            lead_id INTEGER NOT NULL REFERENCES crm_lead(id),
            chat_summary TEXT,
            profile_summary TEXT,
            outcome VARCHAR(20) NOT NULL DEFAULT '',
            UNIQUE(lead_id, campaign_id)
        );
    """)
    conn.commit()
    conn.close()


def test_inject_creates_lead_and_deal():
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
        db_path = f.name
    make_test_db(db_path)
    mod = load_injector(db_path)

    result = mod.inject(
        linkedin_url="https://www.linkedin.com/in/test-user/",
        public_identifier="test-user",
        campaign_id=1,
        signal={"source": "job_posting", "signal_text": "Hiring VA to handle invoicing and scheduling", "job_title": "Virtual Assistant"},
    )

    assert result["status"] == "inserted"
    conn = sqlite3.connect(db_path)
    lead = conn.execute("SELECT id, linkedin_url FROM crm_lead WHERE public_identifier='test-user'").fetchone()
    assert lead is not None
    deal = conn.execute("SELECT profile_summary, state FROM crm_deal WHERE lead_id=?", (lead[0],)).fetchone()
    assert deal is not None
    ps = json.loads(deal[1])  # profile_summary is JSON
    assert ps["signal_text"] == "Hiring VA to handle invoicing and scheduling"
    assert deal[2] == "Pending"  # state
    conn.close()


def test_inject_is_idempotent():
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
        db_path = f.name
    make_test_db(db_path)
    mod = load_injector(db_path)

    kwargs = dict(
        linkedin_url="https://www.linkedin.com/in/idempotent-user/",
        public_identifier="idempotent-user",
        campaign_id=1,
        signal={"source": "job_posting", "signal_text": "Hiring admin"},
    )
    r1 = mod.inject(**kwargs)
    r2 = mod.inject(**kwargs)
    assert r1["status"] == "inserted"
    assert r2["status"] == "already_exists"

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM crm_lead WHERE public_identifier='idempotent-user'").fetchone()[0]
    assert count == 1
    conn.close()


def test_inject_profile_summary_is_valid_json():
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
        db_path = f.name
    make_test_db(db_path)
    mod = load_injector(db_path)

    mod.inject(
        linkedin_url="https://www.linkedin.com/in/json-test/",
        public_identifier="json-test",
        campaign_id=2,
        signal={"source": "job_posting", "signal_text": "Hiring ops coordinator", "job_title": "Ops Coordinator", "company": "Acme LLC"},
    )

    conn = sqlite3.connect(db_path)
    ps_raw = conn.execute("SELECT profile_summary FROM crm_deal").fetchone()[0]
    conn.close()
    parsed = json.loads(ps_raw)
    assert parsed["company"] == "Acme LLC"
    assert parsed["source"] == "job_posting"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m pytest tests/test_signal_injector.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError` or `FileNotFoundError` — the injector doesn't exist yet.

- [ ] **Step 3: Write the injector**

Create `.claude/hooks/openoutreach-signal-injector.py`:

```python
#!/usr/bin/env python3
"""
openoutreach-signal-injector.py — Write signal-enriched leads into OpenOutreach DB.

Takes a LinkedIn URL + signal dict, writes crm_lead + crm_deal rows.
Idempotent: running twice for the same URL does nothing.

Usage (from other scripts):
    from openoutreach_signal_injector import inject
    result = inject(
        linkedin_url="https://www.linkedin.com/in/jane-smith/",
        public_identifier="jane-smith",
        campaign_id=4,
        signal={
            "source": "job_posting",
            "signal_text": "Hiring VA to handle invoicing, scheduling, and client follow-ups",
            "job_title": "Virtual Assistant",
            "company": "Smith Consulting",
            "job_post_url": "https://www.linkedin.com/jobs/view/...",
        },
    )
    # result: {"status": "inserted"|"already_exists", "lead_id": int, "deal_id": int|None}

CLI usage:
    python3 openoutreach-signal-injector.py \
        --url "https://www.linkedin.com/in/jane-smith/" \
        --identifier "jane-smith" \
        --campaign-id 4 \
        --signal '{"source":"job_posting","signal_text":"Hiring VA"}'
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from kamil_log import klog, klog_error
except ImportError:
    def klog(event, **kw): pass
    def klog_error(context, exc, **kw): pass

OPENOUTREACH_DB = Path.home() / ".openoutreach" / "data" / "db.sqlite3"


def inject(
    linkedin_url: str,
    public_identifier: str,
    campaign_id: int,
    signal: dict,
) -> dict:
    """
    Write one lead + deal into OpenOutreach DB.
    Returns {"status": "inserted"|"already_exists", "lead_id": int, "deal_id": int|None}
    """
    if not OPENOUTREACH_DB.exists():
        klog_error("openoutreach-signal-injector", Exception("DB not found"), db=str(OPENOUTREACH_DB))
        return {"status": "error", "reason": "db_not_found"}

    now = datetime.utcnow().isoformat()

    try:
        conn = sqlite3.connect(str(OPENOUTREACH_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Insert lead (ignore if duplicate URL)
        cur.execute("""
            INSERT OR IGNORE INTO crm_lead
                (linkedin_url, public_identifier, disqualified, creation_date, update_date)
            VALUES (?, ?, 0, ?, ?)
        """, (linkedin_url.rstrip("/") + "/", public_identifier, now, now))

        if cur.rowcount == 0:
            # Lead already exists — fetch its id
            cur.execute("SELECT id FROM crm_lead WHERE public_identifier=?", (public_identifier,))
            row = cur.fetchone()
            if row is None:
                conn.close()
                return {"status": "error", "reason": "lead_not_found_after_ignore"}
            lead_id = row["id"]
            conn.close()
            klog("signal_inject_skip", component="signal-injector",
                 public_identifier=public_identifier, reason="already_exists")
            return {"status": "already_exists", "lead_id": lead_id, "deal_id": None}

        lead_id = cur.lastrowid

        # Write profile_summary as JSON so OpenOutreach AI can read the signal
        profile_summary = json.dumps({
            "source": signal.get("source", "unknown"),
            "signal_text": signal.get("signal_text", ""),
            "job_title": signal.get("job_title", ""),
            "company": signal.get("company", ""),
            "job_post_url": signal.get("job_post_url", ""),
            "injected_at": now,
        })

        # Insert deal
        cur.execute("""
            INSERT OR IGNORE INTO crm_deal
                (state, reason, connect_attempts, backoff_hours,
                 creation_date, update_date, campaign_id, lead_id,
                 profile_summary, outcome)
            VALUES ('Pending', '', 0, 0, ?, ?, ?, ?, ?, '')
        """, (now, now, campaign_id, lead_id, profile_summary))

        deal_id = cur.lastrowid
        conn.commit()
        conn.close()

        klog("signal_injected", component="signal-injector",
             public_identifier=public_identifier,
             campaign_id=campaign_id,
             signal_source=signal.get("source"),
             signal_preview=signal.get("signal_text", "")[:80])

        return {"status": "inserted", "lead_id": lead_id, "deal_id": deal_id}

    except Exception as e:
        klog_error("signal-injector", e, public_identifier=public_identifier)
        return {"status": "error", "reason": str(e)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject signal-enriched lead into OpenOutreach")
    parser.add_argument("--url", required=True, help="LinkedIn profile URL")
    parser.add_argument("--identifier", required=True, help="LinkedIn public identifier (slug)")
    parser.add_argument("--campaign-id", required=True, type=int, help="OpenOutreach campaign ID")
    parser.add_argument("--signal", required=True, help="JSON signal dict")
    args = parser.parse_args()

    signal = json.loads(args.signal)
    result = inject(
        linkedin_url=args.url,
        public_identifier=args.identifier,
        campaign_id=args.campaign_id,
        signal=signal,
    )
    print(json.dumps(result, indent=2))
```

- [ ] **Step 4: Run tests — should pass**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m pytest tests/test_signal_injector.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks/openoutreach-signal-injector.py tests/test_signal_injector.py
git commit -m "feat: add openoutreach signal injector with idempotent lead+deal writes"
```

---

## Task 3: Write `openoutreach-job-signal-scraper.py`

**Files:**
- Create: `.claude/hooks/openoutreach-job-signal-scraper.py`
- Test: `tests/test_job_signal_scraper.py`

This script searches LinkedIn Jobs for postings containing pain-signal keywords (VA, admin, ops, EA). It extracts the poster's profile URL and the job post body as the signal, then calls `inject()` for each new posting. Runs every 30min via job-finder.

**Important:** LinkedIn Jobs search does NOT require authentication for the public URL — we scrape `https://www.linkedin.com/jobs/search/?keywords=<query>` with `urllib.request` and a browser User-Agent. No Playwright needed.

- [ ] **Step 1: Write the failing test**

Create `tests/test_job_signal_scraper.py`:

```python
"""Tests for openoutreach-job-signal-scraper.py"""
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))


def load_scraper():
    spec = importlib.util.spec_from_file_location(
        "scraper",
        Path(__file__).parent.parent / ".claude" / "hooks" / "openoutreach-job-signal-scraper.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_extract_public_identifier_from_url():
    mod = load_scraper()
    assert mod.extract_identifier("https://www.linkedin.com/in/jane-smith/") == "jane-smith"
    assert mod.extract_identifier("https://www.linkedin.com/in/john-doe") == "john-doe"
    assert mod.extract_identifier("https://linkedin.com/in/alice-bob-123/") == "alice-bob-123"


def test_extract_identifier_returns_none_for_bad_url():
    mod = load_scraper()
    assert mod.extract_identifier("https://example.com/notlinkedin") is None
    assert mod.extract_identifier("") is None


def test_is_pain_signal_true():
    mod = load_scraper()
    assert mod.is_pain_signal("Hiring a virtual assistant to manage inbox and scheduling") is True
    assert mod.is_pain_signal("Looking for an admin assistant to handle data entry") is True
    assert mod.is_pain_signal("EA needed for calendar and travel management") is True
    assert mod.is_pain_signal("Operations coordinator for our small team") is True


def test_is_pain_signal_false():
    mod = load_scraper()
    assert mod.is_pain_signal("Senior Software Engineer — Python and Django") is False
    assert mod.is_pain_signal("Marketing Manager for B2B SaaS company") is False


def test_build_signal_dict():
    mod = load_scraper()
    signal = mod.build_signal(
        job_title="Virtual Assistant",
        job_text="Handle invoicing, scheduling, and client follow-up for a 5-person agency",
        company="Acme LLC",
        job_url="https://www.linkedin.com/jobs/view/12345/",
    )
    assert signal["source"] == "job_posting"
    assert "invoicing" in signal["signal_text"]
    assert signal["company"] == "Acme LLC"
    assert signal["job_post_url"] == "https://www.linkedin.com/jobs/view/12345/"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m pytest tests/test_job_signal_scraper.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError` — scraper doesn't exist yet.

- [ ] **Step 3: Write the scraper**

Create `.claude/hooks/openoutreach-job-signal-scraper.py`:

```python
#!/usr/bin/env python3
"""
openoutreach-job-signal-scraper.py — Scrape LinkedIn job postings for VA/admin/ops pain signals.

Searches LinkedIn Jobs public search (no auth needed) for job titles that indicate
manual process pain: Virtual Assistant, Admin Assistant, Operations Coordinator, EA.
For each posting, extracts poster LinkedIn URL + job text as signal, then calls
openoutreach-signal-injector.inject() to write a lead into OpenOutreach DB.

State: /tmp/kamil-oo-scraped-jobs.json (dedup store, persists across runs)

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
    from kamil_log import klog, klog_error
except ImportError:
    def klog(event, **kw): pass
    def klog_error(context, exc, **kw): pass

STATE_FILE = Path("/tmp/kamil-oo-scraped-jobs.json")
OPENOUTREACH_DB = Path.home() / ".openoutreach" / "data" / "db.sqlite3"

# Job titles that signal manual-process pain
PAIN_KEYWORDS = [
    "virtual assistant", "va needed", "va role",
    "admin assistant", "administrative assistant",
    "operations coordinator", "ops coordinator",
    "executive assistant", "ea needed",
    "personal assistant", "office manager",
    "data entry", "office administrator",
]

# LinkedIn Jobs public search base URL
LI_JOBS_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Campaign ID for "Automation Freelance Outreach" — set after Task 1
# Update this after running the campaign insert in Task 1
AUTOMATION_CAMPAIGN_NAME = "Automation Freelance Outreach"


def get_campaign_id() -> int | None:
    """Look up campaign ID from DB by name."""
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


def extract_identifier(url: str) -> str | None:
    """Extract LinkedIn public identifier from a profile URL."""
    if not url:
        return None
    m = re.search(r"linkedin\.com/in/([^/?#]+)", url)
    if not m:
        return None
    return m.group(1).strip("/")


def is_pain_signal(text: str) -> bool:
    """Return True if job title/text contains a manual-process pain keyword."""
    lower = text.lower()
    return any(kw in lower for kw in PAIN_KEYWORDS)


def build_signal(job_title: str, job_text: str, company: str, job_url: str) -> dict:
    """Build signal dict for the injector."""
    return {
        "source": "job_posting",
        "signal_text": job_text[:500],
        "job_title": job_title,
        "company": company,
        "job_post_url": job_url,
    }


def http_get(url: str, timeout: int = 10) -> str | None:
    """GET with browser headers. Returns body text or None on error."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        klog_error("job-signal-scraper-http", e, url=url[:100])
        return None


def search_linkedin_jobs(keyword: str, start: int = 0) -> list[dict]:
    """
    Query LinkedIn guest jobs API for a keyword.
    Returns list of dicts: {job_id, title, company, location, detail_url, poster_url}
    """
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

    jobs = []
    # LinkedIn guest API returns HTML cards — extract job IDs and titles with regex
    job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
    titles  = re.findall(r'class="base-search-card__title"[^>]*>\s*([^<]+)\s*<', html)
    companies = re.findall(r'class="base-search-card__subtitle"[^>]*>\s*<[^>]+>\s*([^<]+)\s*<', html)

    for i, jid in enumerate(job_ids[:10]):
        title   = titles[i].strip()   if i < len(titles)    else ""
        company = companies[i].strip() if i < len(companies) else ""
        jobs.append({
            "job_id":    jid,
            "title":     title,
            "company":   company,
            "detail_url": f"https://www.linkedin.com/jobs/view/{jid}/",
            "poster_url": "",  # fetched separately in get_poster_url
        })
    return jobs


def get_poster_url(job_id: str) -> str | None:
    """
    Fetch the job detail page and extract the poster's LinkedIn profile URL.
    LinkedIn guest job pages include a "Meet the hiring team" section.
    """
    url = f"https://www.linkedin.com/jobs/view/{job_id}/"
    html = http_get(url)
    if not html:
        return None
    # LinkedIn embeds poster profile links in job pages
    m = re.search(r'href="(https://www\.linkedin\.com/in/[^"?]+)"', html)
    return m.group(1) if m else None


def get_job_description(job_id: str) -> str:
    """Fetch job detail page and extract description text."""
    url = f"https://www.linkedin.com/jobs/view/{job_id}/"
    html = http_get(url)
    if not html:
        return ""
    # Strip tags, collapse whitespace
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    # Grab text around "responsibilities" or "about the role"
    m = re.search(r"(responsibilities|about the role|what you.ll do|job description)(.{50,800})", text, re.I)
    return m.group(0).strip() if m else text[500:1000]


def load_state() -> set:
    """Return set of already-seen job IDs."""
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text()).get("seen_job_ids", []))
        except Exception:
            pass
    return set()


def save_state(seen: set):
    STATE_FILE.write_text(json.dumps({"seen_job_ids": list(seen)}, indent=2))


def run() -> int:
    """Main scraper run. Returns count of new leads injected."""
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

    search_keywords = [
        "virtual assistant",
        "admin assistant hiring",
        "operations coordinator small business",
        "executive assistant founder",
    ]

    for keyword in search_keywords:
        jobs = search_linkedin_jobs(keyword)
        time.sleep(2)  # polite delay between searches

        for job in jobs:
            job_id = job["job_id"]
            if job_id in seen:
                continue

            title = job["title"]
            if not is_pain_signal(title):
                seen.add(job_id)
                continue

            # Get poster URL and job description
            poster_url = get_poster_url(job_id)
            time.sleep(1)

            if not poster_url:
                seen.add(job_id)
                klog("signal_scraper_no_poster", component="job-signal-scraper",
                     job_id=job_id, title=title)
                continue

            identifier = extract_identifier(poster_url)
            if not identifier:
                seen.add(job_id)
                continue

            description = get_job_description(job_id)
            time.sleep(1)

            signal = build_signal(
                job_title=title,
                job_text=description or f"Hiring a {title} — {job.get('company','')}",
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
                     job_id=job_id, title=title, company=job.get("company",""),
                     identifier=identifier, campaign_id=campaign_id)

    save_state(seen)
    klog("signal_scraper_run", component="job-signal-scraper",
         injected=injected, keywords_searched=len(search_keywords))
    return injected


if __name__ == "__main__":
    count = run()
    print(f"[job-signal-scraper] {count} new leads injected", flush=True)
```

- [ ] **Step 4: Run tests — should pass**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m pytest tests/test_job_signal_scraper.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks/openoutreach-job-signal-scraper.py tests/test_job_signal_scraper.py
git commit -m "feat: add linkedin job signal scraper for VA/admin/ops postings"
```

---

## Task 4: Wire scraper into `job-finder.py`

**Files:**
- Modify: `.claude/hooks/job-finder.py:510-516`

The job-finder already calls `openoutreach_monitor` at line 510. We add the scraper call right after.

- [ ] **Step 1: Find the exact insertion point**

```bash
grep -n "openoutreach_monitor\|oo_events" /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/job-finder.py
```

Note the line numbers — should be around 510–516.

- [ ] **Step 2: Add the scraper call after the monitor block**

In `.claude/hooks/job-finder.py`, after this existing block:

```python
    try:
        from openoutreach_monitor import run as monitor_openoutreach
        oo_events = monitor_openoutreach(bot_token)
        if oo_events:
            log(f"OpenOutreach: {oo_events} new LinkedIn event(s)")
    except Exception as e:
        log(f"OpenOutreach monitor skipped: {e}")
```

Add immediately after:

```python
    # Scrape LinkedIn job postings for VA/admin/ops pain signals → inject leads
    try:
        from openoutreach_job_signal_scraper import run as scrape_job_signals
        injected = scrape_job_signals()
        if injected:
            log(f"OpenOutreach signal scraper: {injected} new leads injected")
    except Exception as e:
        log(f"OpenOutreach signal scraper skipped: {e}")
```

- [ ] **Step 3: Verify the import name matches the file**

```bash
# File is openoutreach-job-signal-scraper.py but Python needs underscore for import
# Check if Python can import it as openoutreach_job_signal_scraper
python3 -c "
import sys
sys.path.insert(0, '/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks')
import importlib.util
spec = importlib.util.spec_from_file_location(
    'openoutreach_job_signal_scraper',
    '/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/openoutreach-job-signal-scraper.py'
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print('Import OK:', hasattr(mod, 'run'))
"
```

Expected: `Import OK: True`

Note: The import in job-finder.py uses `importlib.util` pattern or relies on Python path. If job-finder imports other hooks with dashes (e.g. `openoutreach_monitor` maps to `openoutreach_monitor.py` with underscore), use the underscore filename. Rename the file if needed:

```bash
# Check how openoutreach_monitor is imported — it uses underscore filename
ls /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/ | grep openoutreach
# openoutreach_monitor.py has underscore — rename scraper to match convention
mv /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/openoutreach-job-signal-scraper.py \
   /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/openoutreach_job_signal_scraper.py
# Update test import path to match
sed -i 's/openoutreach-job-signal-scraper.py/openoutreach_job_signal_scraper.py/' \
    /home/oye/Documents/free_work/personal-agent-v2/tests/test_job_signal_scraper.py
```

- [ ] **Step 4: Run existing tests to ensure nothing is broken**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m pytest tests/test_signal_injector.py tests/test_job_signal_scraper.py -v
```

Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks/job-finder.py \
        .claude/hooks/openoutreach_job_signal_scraper.py \
        tests/test_job_signal_scraper.py
git commit -m "feat: wire job signal scraper into 30min job-finder cron"
```

---

## Task 5: Upgrade `openoutreach_monitor.py` — reply DMs include conversation context

**Files:**
- Modify: `.claude/hooks/openoutreach_monitor.py`

When OpenOutreach detects a reply, the current DM to Kamal just shows a 120-char preview. Kamal needs the full conversation to take over. We add a `get_conversation_for_deal()` helper that queries `chat_chatmessage` and prepends the last 5 messages to the DM.

- [ ] **Step 1: Check the chat_chatmessage schema**

```bash
sqlite3 ~/.openoutreach/data/db.sqlite3 ".schema chat_chatmessage" 2>/dev/null
```

Note the column names — specifically `content`, `created_at`, direction/sender fields.

- [ ] **Step 2: Add the context helper and update the reply DM**

In `.claude/hooks/openoutreach_monitor.py`, add this function before `run()`:

```python
def get_conversation_context(lead_id: int, limit: int = 5) -> str:
    """
    Return last `limit` messages for a lead as a formatted string.
    Falls back gracefully if chat tables have unexpected schema.
    """
    if not OPENOUTREACH_DB.exists():
        return ""
    try:
        conn = sqlite3.connect(str(OPENOUTREACH_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # chat_chatmessage links to crm_lead via recipients or to field
        # Try the most common schema first
        cur.execute("""
            SELECT m.content, m.created_at
            FROM chat_chatmessage m
            JOIN chat_chatmessage_recipients r ON r.chatmessage_id = m.id
            WHERE r.lead_id = ?
            ORDER BY m.created_at DESC
            LIMIT ?
        """, (lead_id, limit))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return ""

        lines = ["*Conversation (latest first):*"]
        for row in rows:
            content = (row["content"] or "")[:200]
            ts = (row["created_at"] or "")[:16]
            lines.append(f"  [{ts}] {content}")
        return "\n".join(lines)

    except Exception:
        return ""
```

Then in the `new_replies` block, replace:

```python
        for r in new_replies[:3]:
            content = r.get("content", "")[:120]
            lines.append(f"• \"{content}\"")
```

With:

```python
        for r in new_replies[:3]:
            content = r.get("content", "")[:120]
            lines.append(f"• \"{content}\"")
            # Add conversation context so Kamal can take over immediately
            lead_id = r.get("profile_id") or r.get("lead_id")
            if lead_id:
                ctx = get_conversation_context(int(lead_id))
                if ctx:
                    lines.append(ctx)
```

- [ ] **Step 3: Smoke test the monitor (dry run)**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "
import sys
sys.path.insert(0, '.claude/hooks')
from openoutreach_monitor import check_openoutreach, get_conversation_context
data = check_openoutreach()
print('Tables:', data.get('tables', []))
print('Stats:', data.get('stats', {}))
print('Conversation test:', get_conversation_context(1))
"
```

Expected: no exceptions, prints table list and stats.

- [ ] **Step 4: Commit**

```bash
git add .claude/hooks/openoutreach_monitor.py
git commit -m "feat: include full conversation context in reply DMs so Kamal can take over"
```

---

## Task 6: End-to-end smoke test

Verify the full pipeline: scraper finds a job → injector writes to DB → lead appears in OpenOutreach → monitor would detect a reply.

- [ ] **Step 1: Manually inject one test lead**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks

# Get the campaign ID first
python3 -c "
import sqlite3
from pathlib import Path
conn = sqlite3.connect(str(Path.home() / '.openoutreach' / 'data' / 'db.sqlite3'))
row = conn.execute(\"SELECT id FROM linkedin_campaign WHERE name='Automation Freelance Outreach'\").fetchone()
print('Campaign ID:', row[0] if row else 'NOT FOUND')
conn.close()
"

# Inject a test lead (replace CAMPAIGN_ID with the value above)
python3 openoutreach-signal-injector.py \
  --url "https://www.linkedin.com/in/smoke-test-user-001/" \
  --identifier "smoke-test-user-001" \
  --campaign-id CAMPAIGN_ID \
  --signal '{"source":"job_posting","signal_text":"Hiring VA to handle scheduling and invoicing for our 8-person agency","job_title":"Virtual Assistant","company":"Test Agency LLC","job_post_url":"https://www.linkedin.com/jobs/view/test123/"}'
```

Expected: `{"status": "inserted", "lead_id": <N>, "deal_id": <M>}`

- [ ] **Step 2: Verify the rows in DB**

```bash
sqlite3 ~/.openoutreach/data/db.sqlite3 "
SELECT l.linkedin_url, d.state, d.profile_summary
FROM crm_lead l
JOIN crm_deal d ON d.lead_id = l.id
WHERE l.public_identifier='smoke-test-user-001';
"
```

Expected: one row with `state=Pending` and `profile_summary` containing the signal JSON.

- [ ] **Step 3: Verify idempotency**

```bash
python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/openoutreach-signal-injector.py \
  --url "https://www.linkedin.com/in/smoke-test-user-001/" \
  --identifier "smoke-test-user-001" \
  --campaign-id CAMPAIGN_ID \
  --signal '{"source":"job_posting","signal_text":"duplicate run"}'
```

Expected: `{"status": "already_exists", ...}`

- [ ] **Step 4: Run the scraper once manually and check output**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks
python3 openoutreach_job_signal_scraper.py
```

Expected: `[job-signal-scraper] N new leads injected` where N ≥ 0 (0 is fine if LinkedIn rate-limits; that means the HTTP layer returned nothing, not a bug).

- [ ] **Step 5: Run all tests one final time**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m pytest tests/test_signal_injector.py tests/test_job_signal_scraper.py -v
```

Expected: `7 passed`.

- [ ] **Step 6: Final commit**

```bash
git add -p
git commit -m "test: end-to-end smoke test for signal-first outreach pipeline"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** Campaign insert ✓, injector ✓, scraper ✓, job-finder wiring ✓, monitor reply context ✓, no-approval automatic flow ✓, Kamal takeover on reply ✓
- [x] **No placeholders:** All code blocks are complete. No TBD/TODO in task steps.
- [x] **Type consistency:** `inject()` signature matches test calls in Task 2 and scraper call in Task 3. `get_conversation_context()` signature matches call site in Task 5.
- [x] **Import names:** `openoutreach_job_signal_scraper` (underscore) consistent with hooks convention and job-finder import.
- [x] **Campaign ID:** Task 1 inserts campaign, Task 3 `get_campaign_id()` looks it up dynamically — no hardcoded ID.
