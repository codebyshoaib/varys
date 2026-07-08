"""Regression guard for the trend-scanner duplicate cleanup.

trend-scanner.py (hyphen, 160 ln) was a divergent dead copy sitting beside the
importable trend_scanner.py module. Hyphenated names cannot be imported as
Python modules; content-scheduler.py imports the underscore form. The hyphen
copy was orphaned (not in crontab, imported/invoked by nothing) and was deleted.
This test keeps the dupe from silently reappearing and pins the survivor's
public surface that content-scheduler.py depends on.
"""
import os
import sys
import importlib

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)


def test_hyphen_duplicate_is_gone():
    assert not os.path.exists(os.path.join(HOOKS_DIR, "trend-scanner.py")), (
        "dead divergent dupe trend-scanner.py reappeared; delete it "
        "(content-scheduler.py imports the underscore module trend_scanner)"
    )


def test_survivor_exposes_scheduler_surface():
    m = importlib.import_module("trend_scanner")
    assert hasattr(m, "scan_trends"), (
        "trend_scanner missing scan_trends (imported by content-scheduler.py)"
    )


if __name__ == "__main__":
    test_hyphen_duplicate_is_gone()
    test_survivor_exposes_scheduler_surface()
    print("ok")
