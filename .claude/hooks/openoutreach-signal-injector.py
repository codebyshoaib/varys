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

if "OPENOUTREACH_DB" not in dir():
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

        cur.execute("""
            INSERT OR IGNORE INTO crm_lead
                (linkedin_url, public_identifier, disqualified, creation_date, update_date)
            VALUES (?, ?, 0, ?, ?)
        """, (linkedin_url.rstrip("/") + "/", public_identifier, now, now))

        if cur.rowcount == 0:
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

        profile_summary = json.dumps({
            "source": signal.get("source", "unknown"),
            "signal_text": signal.get("signal_text", ""),
            "job_title": signal.get("job_title", ""),
            "company": signal.get("company", ""),
            "job_post_url": signal.get("job_post_url", ""),
            "injected_at": now,
        })

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
