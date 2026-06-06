"""Tests for openoutreach_job_signal_scraper.py"""
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))


def load_scraper():
    spec = importlib.util.spec_from_file_location(
        "scraper",
        Path(__file__).parent.parent / ".claude" / "hooks" / "openoutreach_job_signal_scraper.py"
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
