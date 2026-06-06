"""Tests for openoutreach-signal-injector.py"""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))

import importlib.util


def load_injector(db_path: str):
    spec = importlib.util.spec_from_file_location(
        "injector",
        Path(__file__).parent.parent / ".claude" / "hooks" / "openoutreach-signal-injector.py"
    )
    mod = importlib.util.module_from_spec(spec)
    mod.OPENOUTREACH_DB = Path(db_path)
    spec.loader.exec_module(mod)
    return mod


def make_test_db(path: str):
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
    ps = json.loads(deal[0])
    assert ps["signal_text"] == "Hiring VA to handle invoicing and scheduling"
    assert deal[1] == "Pending"
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
