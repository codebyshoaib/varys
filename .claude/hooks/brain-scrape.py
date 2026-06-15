#!/usr/bin/env python3
"""
brain-scrape.py — Populate brain.db from GitHub and Slack.

GitHub: PR authors + reviewers from Orenda-Project repos
Slack:  workspace members + engineering channel membership

Run standalone:  python3 .claude/hooks/brain-scrape.py
Wire into cron or SessionStart for periodic refresh.
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from varys_brain import get_brain_db, upsert_entity, write_fact

try:
    from varys_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

SLACK_CONFIG = Path.home() / ".claude" / "hooks" / ".slack"
SOURCE = "brain-scrape"

GITHUB_REPOS = [
    "Orenda-Project/taleemabad-core",
    "Orenda-Project/compliancetracker",
]

# ponytail: only scrape channels that matter for people-graph
ENGINEERING_CHANNELS = ["engineering"]  # prefix-match: catches engineering, engineering-*, etc.


# ── helpers ──────────────────────────────────────────────────────────────────

def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "unknown"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _add_fact(db, subject_id, predicate, object_id=None, object_val=None, session_id=None):
    """Insert fact only if exact (subject+predicate+object) doesn't already exist.

    write_fact() updates on subject+predicate match (single-valued).
    This helper allows multi-valued facts (one person → many repos/channels).
    """
    if object_id:
        exists = db.execute(
            "SELECT 1 FROM facts WHERE subject_id=? AND predicate=? AND object_id=? AND valid_until IS NULL",
            (subject_id, predicate, object_id)
        ).fetchone()
    else:
        exists = db.execute(
            "SELECT 1 FROM facts WHERE subject_id=? AND predicate=? AND object_val=? AND valid_until IS NULL",
            (subject_id, predicate, object_val or "")
        ).fetchone()
    if exists:
        return
    now = _now()
    db.execute(
        "INSERT INTO facts (id, subject_id, predicate, object_id, object_val, source, session_id, valid_from, confidence, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?)",
        (f"fact-{uuid.uuid4().hex[:12]}", subject_id, predicate,
         object_id, object_val, SOURCE, session_id, now, now)
    )
    db.commit()


def _gh(args):
    r = subprocess.run(["gh"] + args, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def _load_slack_token():
    cfg = {}
    if SLACK_CONFIG.exists():
        for line in SLACK_CONFIG.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg.get("SLACK_TOKEN") or cfg.get("BOT_TOKEN") or os.environ.get("SLACK_TOKEN")


def _slack(token, endpoint, params=None):
    url = "https://slack.com/api/" + endpoint
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        if not data.get("ok"):
            print(f"[brain-scrape] slack/{endpoint}: {data.get('error')}", file=sys.stderr)
            return None
        return data
    except Exception as e:
        print(f"[brain-scrape] slack/{endpoint} failed: {e}", file=sys.stderr)
        return None


# ── scrapers ─────────────────────────────────────────────────────────────────

def scrape_github(db, session_id):
    seen = {}  # login → person_id (dedup across repos)
    for repo in GITHUB_REPOS:
        repo_slug = repo.split("/")[1]
        proj_id = f"project-{_slug(repo_slug)}"
        upsert_entity(db, proj_id, "project", repo_slug)
        print(f"[brain-scrape] github: {repo}", file=sys.stderr)

        prs = _gh(["pr", "list", "--repo", repo, "--limit", "200",
                    "--state", "all", "--json", "author,reviews"])
        if not prs:
            print(f"[brain-scrape]   gh failed — skipping", file=sys.stderr)
            continue

        repo_people = set()
        for pr in prs:
            candidates = []
            author = pr.get("author", {})
            if author and not author.get("is_bot") and author.get("login"):
                candidates.append((author, "contributed_to"))
            for review in pr.get("reviews", []):
                rv = review.get("author", {})
                if rv and not rv.get("is_bot") and rv.get("login"):
                    candidates.append((rv, "reviewed_prs_in"))

            for person, predicate in candidates:
                login = person["login"]
                name = person.get("name") or login
                pid = seen.get(login)
                if not pid:
                    pid = f"person-{_slug(login)}"
                    seen[login] = pid
                    upsert_entity(db, pid, "person", name, aliases=[login])
                    _add_fact(db, pid, "github_login", object_val=login, session_id=session_id)
                    _add_fact(db, pid, "role", object_val="engineer", session_id=session_id)
                _add_fact(db, pid, predicate, object_id=proj_id, session_id=session_id)
                repo_people.add(login)

        print(f"[brain-scrape]   {len(repo_people)} people", file=sys.stderr)

    return len(seen)


def scrape_slack(db, session_id):
    token = _load_slack_token()
    if not token:
        print("[brain-scrape] no Slack token — skipping", file=sys.stderr)
        return 0

    # 1. All workspace members
    print("[brain-scrape] slack: users.list", file=sys.stderr)
    data = _slack(token, "users.list", {"limit": 500})
    if not data:
        return 0

    uid_to_pid = {}
    count = 0
    for member in data.get("members", []):
        if member.get("is_bot") or member.get("deleted") or member["id"] == "USLACKBOT":
            continue
        uid = member["id"]
        profile = member.get("profile", {})
        name = (profile.get("real_name") or profile.get("display_name")
                or member.get("name") or uid)
        display = profile.get("display_name") or member.get("name", "")
        email = profile.get("email", "")
        title = profile.get("title", "")

        pid = f"person-{_slug(name)}"
        # Collision guard: if slug clashes with a different uid, suffix with uid fragment
        existing = db.execute("SELECT aliases FROM entities WHERE id=?", (pid,)).fetchone()
        if existing:
            aliases = json.loads(existing[0] or "[]")
            if uid not in aliases:
                pid = f"person-{_slug(name)}-{uid[:4].lower()}"

        upsert_entity(db, pid, "person", name, aliases=[display, uid])
        _add_fact(db, pid, "slack_id", object_val=uid, session_id=session_id)
        if email:
            _add_fact(db, pid, "email", object_val=email, session_id=session_id)
        if title:
            _add_fact(db, pid, "title", object_val=title, session_id=session_id)

        uid_to_pid[uid] = pid
        count += 1

    print(f"[brain-scrape]   {count} members", file=sys.stderr)

    # 2. Engineering channel membership
    channels_data = _slack(token, "conversations.list",
                            {"types": "public_channel,private_channel",
                             "limit": "500", "exclude_archived": "true"})
    if not channels_data:
        return count

    eng = {c["name"]: c["id"] for c in channels_data.get("channels", [])
           if any(c["name"].startswith(n) for n in ENGINEERING_CHANNELS)}

    print(f"[brain-scrape]   channels: {list(eng.keys())}", file=sys.stderr)
    for ch_name, ch_id in eng.items():
        ch_entity_id = f"channel-{_slug(ch_name)}"
        upsert_entity(db, ch_entity_id, "concept", f"#{ch_name}")
        members = _slack(token, "conversations.members", {"channel": ch_id, "limit": "200"})
        if not members:
            continue
        for uid in members.get("members", []):
            pid = uid_to_pid.get(uid)
            if pid:
                _add_fact(db, pid, "member_of", object_id=ch_entity_id, session_id=session_id)

    return count


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    session_id = f"scrape-{uuid.uuid4().hex[:8]}"
    print(f"[brain-scrape] {session_id}", file=sys.stderr)
    db = get_brain_db()

    gh_count = scrape_github(db, session_id)
    sl_count = scrape_slack(db, session_id)

    total = db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    people = db.execute("SELECT COUNT(*) FROM entities WHERE type='person'").fetchone()[0]
    facts  = db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    db.close()

    print(f"[brain-scrape] done. github={gh_count} slack={sl_count} "
          f"people={people} total_entities={total} facts={facts}", file=sys.stderr)
    klog("brain-scrape-complete", component="brain-scrape",
         github_people=gh_count, slack_people=sl_count,
         people=people, total_entities=total, facts=facts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
