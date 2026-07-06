"""Regression guard for the internet-scanner duplicate cleanup.

internet-scanner.py (hyphen) was a byte-identical dead copy of the importable
internet_scanner.py module. Hyphenated names cannot be imported as Python
modules; job-finder.py imports the underscore form. The hyphen copy was deleted.
This test keeps the dupe from silently reappearing and pins the survivor's
public surface that job-finder.py depends on.
"""
import os
import sys
import importlib

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)


def test_hyphen_duplicate_is_gone():
    assert not os.path.exists(os.path.join(HOOKS_DIR, "internet-scanner.py")), (
        "dead byte-identical dupe internet-scanner.py reappeared; delete it "
        "(job-finder.py imports the underscore module internet_scanner)"
    )


def test_survivor_exposes_job_finder_surface():
    m = importlib.import_module("internet_scanner")
    for name in (
        "scan_all", "scan_reddit_hiring", "scan_remotive", "scan_hn_hiring",
        "scan_github_bounties", "scan_reddit_problems", "http_get",
        "has_paid_signal", "has_stack_signal", "extract_rate", "is_recent",
    ):
        assert hasattr(m, name), f"internet_scanner missing {name} (imported by job-finder.py)"


if __name__ == "__main__":
    test_hyphen_duplicate_is_gone()
    test_survivor_exposes_job_finder_surface()
    print("ok")
