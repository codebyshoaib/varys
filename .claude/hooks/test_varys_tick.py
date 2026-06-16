#!/usr/bin/env python3
"""Minimal check for the poller exit-code contract. Run: python3 test_varys_tick.py"""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("varys_tick", Path(__file__).parent / "varys-tick.py")
vt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vt)

assert vt.poller_outcome(0) == "ok"
assert vt.poller_outcome(2) == "skip"      # not configured -> don't abort the tick
assert vt.poller_outcome(1) == "abort"     # real failure -> rule 6 abort
assert vt.poller_outcome(137) == "abort"   # killed/timeout -> abort
print("ok")
