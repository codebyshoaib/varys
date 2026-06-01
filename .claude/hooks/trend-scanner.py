#!/usr/bin/env python3
"""
trend-scanner.py — Scans web for trending topics for a given track.

Usage:
    from trend_scanner import scan_trends
    results = scan_trends("fitness")
    # returns: [{"topic": str, "score": int, "reason": str}, ...]

Score 0-100:
    +35  trending on Reddit/Twitter right now (recency=today)
    +20  this week recency
    +25  viral/trending/popular keywords in summary
    +15  guide/tips/tutorial keywords
    +20  niche word matches (4pts each, max 20)
    +15  current month/year in summary
    +5   baseline
    cap at 100
Only returns score >= 50.
"""

import json
import subprocess
import sys
from datetime import datetime
import sys as _sys, time as _time
_sys.path.insert(0, "/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks")
try:
    import kamil_log as _k
except Exception:
    _k = None

TRACK_NICHES = {
    "fitness": "calisthenics bodyweight fitness swimming hiking cycling workout",
    "tech":    "Claude AI coding Python Django software engineering developer tools",
    "vlog":    "Islamabad Pakistan daily life food travel vlog",
}

TRACK_SEARCH_QUERIES = {
    "fitness": [
        "calisthenics trending workout site:reddit.com",
        "bodyweight fitness viral tips {month} {year}",
        "swimming hiking cycling trending social media {year}",
    ],
    "tech": [
        "Claude AI developer tips trending site:reddit.com",
        "Python Django coding viral post {month} {year}",
        "AI tools developer trending Twitter {month} {year}",
    ],
    "vlog": [
        "Islamabad things to do {month} {year}",
        "Pakistan travel vlog trending {year}",
        "Islamabad food street events {month}",
    ],
}


def _web_search(query: str) -> str:
    prompt = (
        f"Search the web for: {query}\n"
        f"Return a JSON list of up to 5 results, each with: "
        f'[{{"title": "...", "summary": "...", "url": "...", "recency": "today|this week|this month|older"}}]\n'
        f"Return ONLY valid JSON array, no other text."
    )
    try:
        r = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt],
            capture_output=True, text=True, timeout=60
        )
        return r.stdout.strip()
    except Exception:
        return "[]"


def _score_result(result: dict, track: str) -> int:
    score = 5
    summary = (result.get("summary", "") + result.get("title", "")).lower()
    recency = result.get("recency", "older")
    niche_words = TRACK_NICHES.get(track, "").lower().split()

    if recency == "today":
        score += 35
    elif recency == "this week":
        score += 20
    elif recency == "this month":
        score += 10

    if any(w in summary for w in ["viral", "trending", "popular", "top", "best"]):
        score += 25
    elif any(w in summary for w in ["guide", "tips", "how to", "tutorial"]):
        score += 15

    matches = sum(1 for w in niche_words if w in summary)
    score += min(matches * 4, 20)

    current_month = datetime.now().strftime("%B").lower()
    current_year  = str(datetime.now().year)
    if current_month in summary or current_year in summary:
        score += 15

    return min(score, 100)


def _extract_topic(result: dict) -> str:
    title = result.get("title", "")
    for noise in ["- Reddit", "| Twitter", "- YouTube", " r/", " via "]:
        title = title.split(noise)[0]
    return title.strip()[:80]


def scan_trends(track: str) -> list[dict]:
    if track not in TRACK_SEARCH_QUERIES:
        return []

    month = datetime.now().strftime("%B")
    year  = str(datetime.now().year)
    candidates: list[dict] = []

    for query_tmpl in TRACK_SEARCH_QUERIES[track]:
        query = query_tmpl.format(month=month, year=year)
        raw   = _web_search(query)
        try:
            results = json.loads(raw)
            if not isinstance(results, list):
                continue
        except Exception:
            continue

        for r in results:
            score = _score_result(r, track)
            if score < 50:
                continue
            topic  = _extract_topic(r)
            reason = f"Found: '{r.get('title','')}' (recency={r.get('recency','?')}, score={score})"
            candidates.append({"topic": topic, "score": score, "reason": reason})

    seen: set[str] = set()
    unique = []
    for c in candidates:
        key = c["topic"].lower()[:40]
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return sorted(unique, key=lambda x: x["score"], reverse=True)


if __name__ == "__main__":
    _t0 = _time.time()
    try:
        track = sys.argv[1] if len(sys.argv) > 1 else "fitness"
        results = scan_trends(track)
        print(f"\nTrending topics for '{track}':")
        for r in results:
            print(f"  [{r['score']:3d}] {r['topic']}")
            print(f"         {r['reason']}")
        if _k: _k.klog_cron("trend-scanner", status="ok", duration_ms=(_time.time()-_t0)*1000)
    except Exception as _e:
        if _k: _k.klog_error("trend-scanner-main", _e, component="trend-scanner", severity="ERROR")
        raise
