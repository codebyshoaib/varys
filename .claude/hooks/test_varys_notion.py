#!/usr/bin/env python3
"""
test_varys_notion.py — hermetic self-check for the shared Notion rate-limit utility.

Hermetic: NO real network. We monkeypatch the module's time.sleep / time.time and
urllib.request.urlopen so we can observe the 350ms-spacing math and the 429-retry path
without making a single HTTP call.

Covers the invariant this module exists to enforce (orchestrator rule 3):
  - >=350ms is slept between consecutive Notion calls when they arrive too close together
  - no artificial sleep when enough time has already elapsed
  - a 429 is retried exactly once, honouring Retry-After, and returns the retry's body
  - a non-429 HTTPError propagates (caller decides)

Run: python3 .claude/hooks/test_varys_notion.py
"""
import importlib.util
import urllib.error
import urllib.request
from pathlib import Path

HOOKS = Path(__file__).parent
spec = importlib.util.spec_from_file_location("varys_notion", HOOKS / "varys_notion.py")
vn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vn)


class _Resp:
    """Minimal context-manager stand-in for an http response."""
    def __init__(self, status, body):
        self.status, self._body = status, body
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return self._body


def _patch_clock(vn_mod, sleeps: list, now_box: list):
    """Patch the module's time so sleep() is recorded and time() is a controllable counter."""
    vn_mod.time.sleep = lambda s: (sleeps.append(s), now_box.__setitem__(0, now_box[0] + s))
    vn_mod.time.time = lambda: now_box[0]


def test_rate_limit_sleeps_when_calls_too_close():
    sleeps, now = [], [1000.0]
    _patch_clock(vn, sleeps, now)
    urllib.request.urlopen = lambda req, timeout=15: _Resp(200, b"ok")
    vn._last_call = 0.0
    # First call: last_call is far in the past (0 vs now 1000) → no sleep.
    vn.notion_request(urllib.request.Request("https://api.notion.com/v1/x"))
    assert sleeps == [], f"first call should not sleep; slept {sleeps}"
    # Immediate second call: _last_call == now → elapsed 0 → must sleep ~0.35s.
    vn.notion_request(urllib.request.Request("https://api.notion.com/v1/x"))
    assert len(sleeps) == 1 and abs(sleeps[0] - vn._RATE_LIMIT_DELAY) < 1e-9, sleeps
    print("PASS test_rate_limit_sleeps_when_calls_too_close")


def test_no_sleep_when_enough_time_elapsed():
    sleeps, now = [], [2000.0]
    _patch_clock(vn, sleeps, now)
    urllib.request.urlopen = lambda req, timeout=15: _Resp(200, b"ok")
    vn._last_call = 2000.0 - 1.0  # a full second ago → well past 350ms → no sleep
    vn.notion_request(urllib.request.Request("https://api.notion.com/v1/x"))
    assert sleeps == [], f"should not sleep when >350ms elapsed; slept {sleeps}"
    print("PASS test_no_sleep_when_enough_time_elapsed")


def test_429_retried_once_with_retry_after():
    sleeps, now = [], [3000.0]
    _patch_clock(vn, sleeps, now)
    calls = {"n": 0}

    def _fake_urlopen(req, timeout=15):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "rate limited",
                                         {"Retry-After": "2"}, None)
        return _Resp(200, b"second-try-body")

    urllib.request.urlopen = _fake_urlopen
    vn._last_call = 3000.0 - 10  # ensure no pre-call spacing sleep confuses the assert
    status, body = vn.notion_request(urllib.request.Request("https://api.notion.com/v1/x"))
    assert calls["n"] == 2, f"429 must be retried exactly once (saw {calls['n']} calls)"
    assert status == 200 and body == b"second-try-body", (status, body)
    assert 2 in sleeps, f"must honour Retry-After (2s); sleeps={sleeps}"
    print("PASS test_429_retried_once_with_retry_after")


def test_non_429_http_error_propagates():
    sleeps, now = [], [4000.0]
    _patch_clock(vn, sleeps, now)

    def _fake_urlopen(req, timeout=15):
        raise urllib.error.HTTPError(req.full_url, 404, "not found", {}, None)

    urllib.request.urlopen = _fake_urlopen
    vn._last_call = 4000.0 - 10
    try:
        vn.notion_request(urllib.request.Request("https://api.notion.com/v1/x"))
    except urllib.error.HTTPError as e:
        assert e.code == 404, e.code
    else:
        raise AssertionError("a non-429 HTTPError must propagate to the caller")
    print("PASS test_non_429_http_error_propagates")


if __name__ == "__main__":
    test_rate_limit_sleeps_when_calls_too_close()
    test_no_sleep_when_enough_time_elapsed()
    test_429_retried_once_with_retry_after()
    test_non_429_http_error_propagates()
    print("\nALL VARYS_NOTION TESTS PASSED")
