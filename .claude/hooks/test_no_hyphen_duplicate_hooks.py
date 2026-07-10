"""Regression guard for the openoutreach / auto-apply duplicate cleanup.

Four dead files were removed:
  - auto-apply.py                    (hyphen dupe of importable auto_apply.py)
  - openoutreach-monitor.py          (hyphen dupe of importable openoutreach_monitor.py)
  - openoutreach-restore-prompt.py   (called ONLY by the dead hyphen monitor)
  - openoutreach-follow-up-prompt.j2 (patch template read ONLY by restore-prompt)

Hyphenated names cannot be imported as Python modules; job-finder.py imports the
underscore forms (auto_apply, openoutreach_monitor). The hyphen twins were
orphaned (no import, no subprocess, no crontab caller) and were deleted. This
test keeps them from silently reappearing and pins the survivors' `run` surface
that job-finder.py depends on.
"""
import os
import sys
import importlib

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)


def test_dead_files_are_gone():
    for dead in (
        "auto-apply.py",
        "openoutreach-monitor.py",
        "openoutreach-restore-prompt.py",
        "openoutreach-follow-up-prompt.j2",
    ):
        assert not os.path.exists(os.path.join(HOOKS_DIR, dead)), (
            f"dead orphaned file {dead} reappeared; delete it "
            "(job-finder.py imports the underscore modules auto_apply / openoutreach_monitor)"
        )


def test_survivors_expose_run():
    for mod in ("auto_apply", "openoutreach_monitor"):
        m = importlib.import_module(mod)
        assert callable(getattr(m, "run", None)), (
            f"{mod}.run missing (imported by job-finder.py)"
        )


if __name__ == "__main__":
    test_dead_files_are_gone()
    test_survivors_expose_run()
    print("ok")
