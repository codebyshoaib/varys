#!/usr/bin/env python3
"""
varys_notion.py — Shared Notion API utility for all Varys hooks.

Enforces:
  - 350ms inter-call delay  (Notion = 3 req/sec; 350ms gives safety margin)
  - Retry-once on 429 using Retry-After header
  - Clean interface: notion_request(req) → (status_code, body_bytes)

Usage:
    from varys_notion import notion_request
    status, body = notion_request(req)

All hooks that call the Notion REST API directly must use this instead of
bare urllib.request.urlopen() calls.
"""

import time
import urllib.request
import urllib.error

_last_call: float = 0.0
_RATE_LIMIT_DELAY = 0.35  # seconds — keeps us under 3 req/sec with safety margin


def notion_request(req: urllib.request.Request) -> tuple[int, bytes]:
    """
    Execute a Notion API request with rate limiting and one retry on 429.

    Args:
        req: A fully constructed urllib.request.Request (URL, headers, data, method).

    Returns:
        (status_code: int, body: bytes)

    Raises:
        urllib.error.HTTPError  — on non-200/429 HTTP errors (caller decides how to handle)
        urllib.error.URLError   — on network failures
        OSError                 — on timeout
    """
    global _last_call

    # Rate limit: enforce 350ms between consecutive Notion calls
    elapsed = time.time() - _last_call
    if elapsed < _RATE_LIMIT_DELAY:
        time.sleep(_RATE_LIMIT_DELAY - elapsed)
    _last_call = time.time()

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read()

    except urllib.error.HTTPError as e:
        if e.code == 429:
            # Rate limited — wait Retry-After seconds then try once more
            retry_after = int(e.headers.get("Retry-After", "5"))
            time.sleep(retry_after)
            _last_call = time.time()
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, r.read()
        raise
