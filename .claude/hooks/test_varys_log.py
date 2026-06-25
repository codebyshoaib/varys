"""Sibling test for varys_log.py — required by the evolve fence gate.

Covers the one thing that's actually broken if it regresses: the fallback log
must be persistent (not under /tmp, which clears on reboot), since it's the ONLY
telemetry sink.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import varys_log


def test_fallback_is_persistent():
    # Must not live under /tmp (wiped on reboot) unless home was unwritable.
    p = str(varys_log._FALLBACK_LOG)
    home_ok = (Path.home() / ".varys-harness").exists() or True
    assert not p.startswith("/tmp/") or not home_ok, f"fallback on ephemeral /tmp: {p}"


def test_klog_writes_to_fallback():
    before = varys_log._FALLBACK_LOG.stat().st_size if varys_log._FALLBACK_LOG.exists() else 0
    varys_log.klog_cron("test-varys-log", status="ok", duration_ms=1, rc=0, error="")
    after = varys_log._FALLBACK_LOG.stat().st_size
    assert after > before, "klog_cron did not append to the fallback log"


if __name__ == "__main__":
    test_fallback_is_persistent()
    test_klog_writes_to_fallback()
    print("OK test_varys_log")
