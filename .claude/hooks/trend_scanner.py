#!/usr/bin/env python3
"""
trend_scanner.py — Finds trending topics for a track from REAL internet sources.

Cron-safe: uses public endpoints only (no API key, no nested Claude).
  - Reddit RSS  (top.rss?t=day / t=week)  → primary, all tracks
  - Hacker News Algolia search (JSON)     → bonus signal, tech track

Reddit JSON is blocked (403) from datacenter IPs; Reddit RSS (.rss) is NOT — so
we parse the Atom feed. Per-feed failures are swallowed so one dead subreddit
never zeroes a whole run.

Usage:
    from trend_scanner import scan_trends
    results = scan_trends("fitness")
    # -> [{"topic": str, "score": int, "reason": str}, ...]  (score >= 50, sorted desc)

Score 0-100:
    +30  recency = today  (from t=day feed)
    +18  recency = this week
    +25  engagement words in title (transformation, viral, insane, "I built", PR, first ...)
    +15  guide/tips/how-to/tutorial words
    +20  niche-word matches (4 pts each, max 20)
    +10  current month or year in title
    +5   baseline
    cap 100. Only score >= 50 returned.
"""

import html
import json
import threading
import time
import urllib.error
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

UA = "Mozilla/5.0 (X11; Linux x86_64) kamil-trendscanner/1.0 (content-pipeline)"

# Subreddits chosen for view/follower potential per channel (see @oykamal playbook).
TRACK_SUBREDDITS = {
    "fitness": ["bodyweightfitness", "calisthenics", "Fitness", "running", "swimming", "hiking"],
    "tech":    ["Python", "django", "programming", "ClaudeAI", "ChatGPTCoding", "webdev"],
    "vlog":    ["islamabad", "pakistan", "solotravel", "Pakistan", "streetphotography"],
}

TRACK_NICHES = {
    "fitness": "calisthenics bodyweight fitness swimming hiking cycling workout pull-up transformation routine running",
    "tech":    "claude ai coding python django software developer tools agent llm prompt build",
    "vlog":    "islamabad pakistan daily life food travel vlog hike trail margalla",
}

# Engagement-signal words — titles that historically drive views/saves/follows.
HOT_WORDS = [
    "transformation", "viral", "insane", "crazy", "shocking", "nobody",
    "i built", "i made", "i tried", "secret", "underrated", "first time",
    "before and after", "results", "mistake", "stop doing", "the truth",
    "pr", "personal best", "finally", "after years", "changed my life",
]
GUIDE_WORDS = ["guide", "tips", "how to", "how i", "tutorial", "beginner", "step by step", "routine"]

# Titles that are not usable content topics — recurring megathreads, admin posts, etc.
JUNK_MARKERS = [
    "weekly thread", "daily thread", "daily discussion", "weekly discussion",
    "monday daily", "weekly whiteboard", "megathread", "moronic monday",
    "rules", "read before", "mod post", "monthly thread", "simple questions",
    "no stupid questions", "what are you working on", "feedback thread",
]


def _is_junk(title: str) -> bool:
    t = title.lower()
    return any(m in t for m in JUNK_MARKERS)


# Reddit 403s under rapid parallel hits. Serialize + throttle all Reddit fetches
# across the 3 track threads, and back off on 403/429.
_REDDIT_LOCK = threading.Lock()


def _fetch(url: str, timeout: int = 15, retries: int = 3) -> str:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 429, 500, 502, 503):
                time.sleep(1.5 * (attempt + 1))  # 1.5s, 3s, 4.5s
                continue
            raise
        except Exception as e:
            last = e
            time.sleep(1.0 * (attempt + 1))
    if last:
        raise last
    return ""


def _reddit_rss(sub: str, period: str, limit: int = 10) -> list[dict]:
    """Fetch a subreddit's top Atom feed. Returns [{title,url,updated}]. [] on any failure."""
    url = f"https://www.reddit.com/r/{sub}/top.rss?t={period}&limit={limit}"
    try:
        with _REDDIT_LOCK:          # serialize across the 3 track threads
            xml = _fetch(url)
            time.sleep(0.6)          # throttle: one reddit hit max every ~0.6s globally
        root = ET.fromstring(xml)
    except Exception:
        return []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for e in root.findall("a:entry", ns):
        t = e.find("a:title", ns)
        link = e.find("a:link", ns)
        upd = e.find("a:updated", ns)
        title = html.unescape(t.text) if (t is not None and t.text) else ""
        if not title:
            continue
        out.append({
            "title":   title,
            "url":     link.get("href") if link is not None else "",
            "updated": upd.text if (upd is not None and upd.text) else "",
            "source":  f"r/{sub}",
        })
    return out


def _hn_search(query: str, since_days: int = 7) -> list[dict]:
    """HN Algolia story search within since_days, sorted by points. [] on failure."""
    since = int(time.time()) - since_days * 86400
    q = urllib.parse.quote(query)
    url = (f"https://hn.algolia.com/api/v1/search?query={q}"
           f"&tags=story&numericFilters=created_at_i>{since}")
    try:
        d = json.loads(_fetch(url))
    except Exception:
        return []
    out = []
    for h in d.get("hits", []):
        title = h.get("title") or ""
        if not title:
            continue
        out.append({
            "title":    title,
            "url":      h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
            "points":   h.get("points", 0),
            "comments": h.get("num_comments", 0),
            "source":   "HackerNews",
        })
    # only meaningfully-upvoted stories
    return [h for h in out if h.get("points", 0) >= 20]


def _score(item: dict, track: str, recency: str) -> int:
    score = 5
    title = item.get("title", "").lower()
    niche = TRACK_NICHES.get(track, "").lower().split()

    if recency == "today":
        score += 30
    elif recency == "this week":
        score += 18
    else:
        score += 5

    if any(w in title for w in HOT_WORDS):
        score += 25
    elif any(w in title for w in GUIDE_WORDS):
        score += 15

    score += min(sum(1 for w in niche if w in title) * 4, 20)

    month = datetime.now(timezone.utc).strftime("%B").lower()
    year = str(datetime.now(timezone.utc).year)
    if month in title or year in title:
        score += 10

    # HN points are a strong real signal — bump high-scoring stories
    pts = item.get("points", 0)
    if pts >= 200:
        score += 15
    elif pts >= 80:
        score += 8

    return min(score, 100)


def _clean_topic(title: str) -> str:
    t = title
    for noise in [" - Reddit", " | Twitter", " - YouTube", " [OC]", " [Transformation]"]:
        t = t.replace(noise, "")
    return t.strip()[:80]


def scan_trends(track: str) -> list[dict]:
    """Return trending topics (score>=50, deduped, sorted desc) for a track."""
    if track not in TRACK_SUBREDDITS:
        return []

    candidates: list[dict] = []

    # 1. Reddit RSS — today (high recency weight) then this-week
    for period, recency in (("day", "today"), ("week", "this week")):
        for sub in TRACK_SUBREDDITS[track]:
            for item in _reddit_rss(sub, period):
                s = _score(item, track, recency)
                if s < 50:
                    continue
                candidates.append({
                    "topic":  _clean_topic(item["title"]),
                    "score":  s,
                    "reason": f"Trending on {item['source']} ({recency}, score={s})",
                })
            time.sleep(0.4)  # be polite to reddit

    # 2. Hacker News — tech track only (thin signal for fitness/vlog)
    if track == "tech":
        for q in ["Claude AI", "Python", "Django", "AI agent coding", "developer tools"]:
            for item in _hn_search(q):
                s = _score(item, track, "this week")
                if s < 50:
                    continue
                candidates.append({
                    "topic":  _clean_topic(item["title"]),
                    "score":  s,
                    "reason": (f"HN: {item['points']}pts/{item['comments']}c (score={s})"),
                })

    # dedupe by topic prefix, keep highest score
    best: dict[str, dict] = {}
    for c in candidates:
        key = c["topic"].lower()[:40]
        if key not in best or c["score"] > best[key]["score"]:
            best[key] = c

    return sorted(best.values(), key=lambda x: x["score"], reverse=True)


if __name__ == "__main__":
    import sys
    track = sys.argv[1] if len(sys.argv) > 1 else "fitness"
    results = scan_trends(track)
    print(f"\nTrending topics for '{track}': {len(results)} found\n")
    for r in results:
        print(f"  [{r['score']:3d}] {r['topic']}")
        print(f"         {r['reason']}")
