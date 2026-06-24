#!/usr/bin/env python3
"""friction_signals — mechanical detectors for the two friction blind spots.

Learning (reflect-2026-06-24): the friction coach reads a free-text transcript and
*asks an LLM* to catch the quietly-overloaded and the incident-causers. It missed both
(Iqra, silently drowning in review pings; Haroon, who caused the 40-row overwrite) because
those signals are buried — the model anchors on whoever is loud/visible. Asking the prompt
to "catch these" is a guide without a sensor (see self-healer lesson: guides don't enforce).

Fix: compute the two signals mechanically from the raw messages, then inject them into the
analyzer's prompt as facts it cannot overlook:

  1. quietly-overloaded → INBOUND load (others @-mentioning you), NOT your outbound volume.
  2. incident-causer    → what BROKE that day (overwrite / revert / prod down / data loss),
                          not what got verbalized.

Pure functions over the Slack message dicts the coach already collects
({"user": "U..", "text": "..", "ts": ".."}). No network, no Slack SDK — unit-testable.
"""
import re

_MENTION_RE = re.compile(r"<@([UW][A-Z0-9]+)>")

# What BROKE — the incident-causer blind spot. Word-boundary matched, case-insensitive.
INCIDENT_PATTERNS = [
    r"overwr(ote|itten|ite)", r"revert(ed|s)?", r"roll(ed)?\s*back",
    r"prod(uction)?\s+(is\s+)?(down|broke|broken)", r"data\s*loss", r"wiped",
    r"clobber(ed)?", r"regress(ion|ed)", r"took\s+down", r"corrupt(ed|ion)?",
    r"deleted\s+\d+", r"\b\d+\s+(rows?|users?|records?)\s+(got\s+)?(overwr|wiped|lost|deleted)",
]
_INCIDENT_RE = re.compile("|".join(f"(?:{p})" for p in INCIDENT_PATTERNS), re.IGNORECASE)


def _author(m):
    return m.get("user") or (m.get("bot_profile") or {}).get("name") or m.get("username")


def inbound_load(messages):
    """Count how many times each user is @-mentioned BY SOMEONE ELSE.

    This is the quietly-overloaded signal: self-mentions don't count, and a person's own
    chattiness (outbound volume) is irrelevant — what matters is load aimed AT them.
    Returns {user_id: inbound_mention_count}.
    """
    counts = {}
    for m in messages:
        author = _author(m)
        for mentioned in _MENTION_RE.findall(m.get("text", "")):
            if mentioned == author:
                continue  # self-mention is not inbound load
            counts[mentioned] = counts.get(mentioned, 0) + 1
    return counts


def outbound_volume(messages):
    """Messages authored per user — the LOUD signal we must NOT mistake for load."""
    vol = {}
    for m in messages:
        a = _author(m)
        if a:
            vol[a] = vol.get(a, 0) + 1
    return vol


def quietly_overloaded(messages, min_inbound=3, max_outbound_ratio=0.5):
    """Users with high inbound load but low outbound voice — drowning in silence.

    A user is flagged when they receive >= min_inbound mentions AND speak less than
    max_outbound_ratio times their inbound count. Sorted by inbound load, descending.
    """
    inbound = inbound_load(messages)
    outbound = outbound_volume(messages)
    flagged = []
    for uid, n_in in inbound.items():
        if n_in >= min_inbound and outbound.get(uid, 0) < n_in * max_outbound_ratio:
            flagged.append({"user": uid, "inbound": n_in, "outbound": outbound.get(uid, 0)})
    return sorted(flagged, key=lambda x: x["inbound"], reverse=True)


def incident_signals(messages):
    """Messages describing something that BROKE — the incident-causer blind spot.

    Returns [{author, ts, keyword, snippet}] for each matching message, so the analyzer
    sees who was at the centre of a breakage even if no one verbalised it as friction.
    """
    hits = []
    for m in messages:
        text = m.get("text", "")
        match = _INCIDENT_RE.search(text)
        if match:
            hits.append({
                "author": _author(m),
                "ts": m.get("ts"),
                "keyword": match.group(0),
                "snippet": text[:200],
            })
    return hits


def blind_spot_block(messages, name_map=None):
    """Render a prompt-injectable block of the two mechanically-computed blind spots.

    The coach prepends this to its transcript so the analyzer treats these as facts it
    must address, not signals it might infer. Empty string when nothing is detected.
    """
    name_map = name_map or {}

    def nm(uid):
        return name_map.get(uid, uid)

    overloaded = quietly_overloaded(messages)
    incidents = incident_signals(messages)
    if not overloaded and not incidents:
        return ""

    lines = ["MECHANICAL SIGNALS — do not overlook these, they are computed from raw counts:"]
    if overloaded:
        lines.append("  Quietly-overloaded (high inbound mentions, low outbound voice):")
        for o in overloaded:
            lines.append(f"    - {nm(o['user'])}: {o['inbound']} mentions IN, {o['outbound']} messages OUT")
    if incidents:
        lines.append("  Incident-causers (something broke; address the person at the centre):")
        for i in incidents:
            lines.append(f"    - {nm(i['author'])} [{i['keyword']}]: {i['snippet']}")
    return "\n".join(lines)


def demo():
    """Self-check on synthetic data — fails loudly if either detector regresses."""
    # Iqra: pinged 4x by others, speaks once → silently overloaded.
    # Bilal: loud (5 messages) but only mentioned once → NOT overloaded (the loud-but-fine trap).
    # Haroon: caused a 40-row overwrite → incident-causer, never says "blocked".
    msgs = [
        {"user": "U0ALI", "text": "<@U0IQRA> can you review my PR?", "ts": "1"},
        {"user": "U0SARA", "text": "<@U0IQRA> and another one please", "ts": "2"},
        {"user": "U0OMAR", "text": "<@U0IQRA> blocking on your review", "ts": "3"},
        {"user": "U0ZAIN", "text": "<@U0IQRA> last one I promise", "ts": "4"},
        {"user": "U0IQRA", "text": "ok will get to them", "ts": "5"},
        {"user": "U0BILAL", "text": "hey", "ts": "6"},
        {"user": "U0BILAL", "text": "anyone around", "ts": "7"},
        {"user": "U0BILAL", "text": "<@U0BILAL> note to self", "ts": "8"},  # self-mention ignored
        {"user": "U0BILAL", "text": "shipping the feature", "ts": "9"},
        {"user": "U0BILAL", "text": "done", "ts": "10"},
        {"user": "U0ALI", "text": "<@U0BILAL> nice", "ts": "11"},
        {"user": "U0HAROON", "text": "the user-mgmt merge overwrote 40 rows of contact numbers", "ts": "12"},
    ]

    inbound = inbound_load(msgs)
    assert inbound["U0IQRA"] == 4, inbound
    assert inbound.get("U0BILAL") == 1, inbound  # self-mention not counted

    over = quietly_overloaded(msgs)
    over_users = {o["user"] for o in over}
    assert "U0IQRA" in over_users, over          # the silently-drowning one is caught
    assert "U0BILAL" not in over_users, over     # the loud-but-fine one is NOT flagged

    inc = incident_signals(msgs)
    inc_authors = {i["author"] for i in inc}
    assert "U0HAROON" in inc_authors, inc         # incident-causer caught w/o "blocked"
    assert all(i["author"] != "U0IQRA" for i in inc), inc

    block = blind_spot_block(msgs, {"U0IQRA": "Iqra", "U0HAROON": "Haroon"})
    assert "Iqra" in block and "Haroon" in block, block
    assert "Quietly-overloaded" in block and "Incident-causers" in block, block

    # Nothing to report → empty block (no false noise).
    assert blind_spot_block([{"user": "U0X", "text": "hello"}]) == ""

    print("friction_signals demo: all assertions passed")


if __name__ == "__main__":
    demo()
