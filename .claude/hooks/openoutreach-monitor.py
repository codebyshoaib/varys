#!/usr/bin/env python3
"""
openoutreach-monitor.py — Watches OpenOutreach SQLite DB for new events.

Called by job-finder.py every 30 min. Detects:
  - New accepted LinkedIn connections (Connected state in crm_deal)
  - New inbound replies (chat_chatmessage where is_outgoing=False)
  - Campaign stats (state counts)

On new accepted connection → DM Kamal → save to Notion Job Tracker as LinkedIn lead.
On new reply → DM Kamal → update Job Tracker entry.

DB path: ~/.openoutreach/data/db.sqlite3
Schema: crm_lead, crm_deal, chat_chatmessage (NOT crm_linkedinprofile — that table doesn't exist)
"""

import json
import os
import sqlite3
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from kamil_log import klog, klog_error

OPENOUTREACH_DB  = Path.home() / ".openoutreach" / "data" / "db.sqlite3"
STATE_FILE       = Path("/tmp/kamil-openoutreach-state.json")
KAMIL_DIR        = Path(__file__).parent.parent.parent
KAMAL_DM         = "D0B415M06SK"
JOBS_DB          = "0d69c6ff-83d8-44c7-94c2-d341c4ded8d7"

SLACK_CONFIG     = Path.home() / ".claude" / "hooks" / ".slack"


def load_token() -> str:
    if SLACK_CONFIG.exists():
        for line in SLACK_CONFIG.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def slack_dm(token: str, text: str) -> str:
    """Send DM, return message ts."""
    data = json.dumps({"channel": KAMAL_DM, "text": text}).encode()
    req  = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", data=data,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
            return resp.get("ts", "")
    except Exception:
        return ""


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_connected_ids": [], "last_reply_ids": [], "last_run": ""}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def save_linkedin_lead_to_notion(name: str, title: str, company: str,
                                  profile_url: str, message: str):
    """Save accepted LinkedIn connection to Notion Job Tracker."""
    today = datetime.now().strftime("%Y-%m-%d")
    props = {
        "Job Title":       f"LinkedIn: {name} — {title or 'Unknown role'}",
        "Company":         company or "Unknown",
        "Platform":        "linkedin",
        "Status":          "new",
        "Score":           60,
        "Why It Matches":  f"Accepted OpenOutreach connection. Message: {message[:200]}",
        "Proposal Written": "no",
        "date:Date Found:start": today,
    }
    prompt = f"""Use mcp__claude_ai_Notion__notion-create-pages to add ONE page to DB {JOBS_DB}.
Properties:
{json.dumps(props, indent=2)}
Reply only "ok"."""

    env = os.environ.copy()
    env["KAMIL_LINKEDIN_PROMPT"] = prompt
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    subprocess.Popen(
        ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$KAMIL_LINKEDIN_PROMPT"'],
        cwd=str(KAMIL_DIR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def check_openoutreach() -> dict:
    """
    Query OpenOutreach DB for new activity.
    Returns dict with new_connections, new_replies, stats.

    Schema note:
      crm_deal  — state IN ('Connected','Qualified','Pending','Failed')
      crm_lead  — linkedin_url, public_identifier
      chat_chatmessage — is_outgoing=False means inbound reply
    """
    if not OPENOUTREACH_DB.exists():
        return {"running": False}

    try:
        conn  = sqlite3.connect(str(OPENOUTREACH_DB))
        conn.row_factory = sqlite3.Row
        cur   = conn.cursor()

        result = {"running": True, "new_connections": [], "new_replies": [], "stats": {}}

        # Connected deals — joined with lead for profile URL
        cur.execute("""
            SELECT d.id, d.state, d.profile_summary, d.chat_summary, d.outcome,
                   d.creation_date, d.update_date,
                   l.linkedin_url, l.public_identifier
            FROM crm_deal d
            JOIN crm_lead l ON d.lead_id = l.id
            WHERE d.state IN ('Connected', 'Qualified')
            ORDER BY d.update_date DESC
            LIMIT 50
        """)
        result["new_connections"] = [dict(r) for r in cur.fetchall()]

        # Inbound chat messages
        cur.execute("""
            SELECT id, content, creation_date, linkedin_urn
            FROM chat_chatmessage
            WHERE is_outgoing = 0
            ORDER BY creation_date DESC
            LIMIT 20
        """)
        result["new_replies"] = [dict(r) for r in cur.fetchall()]

        # Campaign stats
        cur.execute("SELECT state, COUNT(*) as cnt FROM crm_deal GROUP BY state")
        result["stats"] = {r["state"]: r["cnt"] for r in cur.fetchall()}

        conn.close()
        return result

    except Exception as e:
        return {"running": True, "error": str(e)}


def run(token: str) -> int:
    """Main monitor run. Returns count of new events."""
    if not OPENOUTREACH_DB.exists():
        return 0

    state  = load_state()
    data   = check_openoutreach()

    if not data.get("running"):
        return 0

    if "error" in data:
        print(f"[openoutreach-monitor] DB error: {data['error']}", flush=True)
        klog_error(context="openoutreach-db", exc=Exception(data["error"]), component="openoutreach-monitor")
        return 0

    klog("openoutreach_run", component="openoutreach-monitor",
         stats=data.get("stats", {}),
         new_connections=len(data.get("new_connections", [])),
         new_replies=len(data.get("new_replies", [])))

    seen_connected = set(state.get("last_connected_ids", []))
    seen_replies   = set(state.get("last_reply_ids", []))
    new_events     = 0

    # New accepted connections
    new_connections = [
        c for c in data.get("new_connections", [])
        if str(c["id"]) not in seen_connected
    ]

    if new_connections:
        lines = ["🤝 *LinkedIn connections accepted on OpenOutreach:*\n"]
        for c in new_connections[:5]:
            identifier = c.get("public_identifier", "")
            url        = c.get("linkedin_url", "")
            summary    = (c.get("profile_summary") or "")[:80]
            state_val  = c.get("state", "")
            lines.append(f"• *{identifier}* ({state_val})")
            if summary:
                lines.append(f"  {summary}")
            if url:
                lines.append(f"  {url}")
            lines.append("")
            save_linkedin_lead_to_notion(identifier, summary, "", url, "OpenOutreach connection")
            seen_connected.add(str(c["id"]))
            new_events += 1

        if len(new_connections) > 5:
            lines.append(f"_(+{len(new_connections)-5} more — check Notion Job Tracker)_")

        lines.append("_Reply \"followup [name]\" and I'll write a value-first message._\n🤖 Kamil")
        slack_dm(token, "\n".join(lines))

    # New inbound replies
    new_replies = [
        r for r in data.get("new_replies", [])
        if str(r["id"]) not in seen_replies
    ]

    if new_replies:
        lines = ["💬 *LinkedIn replies via OpenOutreach:*\n"]
        for r in new_replies[:3]:
            content = (r.get("content") or "")[:120]
            urn     = r.get("linkedin_urn", "")
            lines.append(f"• \"{content}\"")
            if urn:
                lines.append(f"  URN: {urn}")
            seen_replies.add(str(r["id"]))
            new_events += 1
        lines.append("\n_Check OpenOutreach at http://localhost:6080 to respond_")
        lines.append("🤖 Kamil")
        slack_dm(token, "\n".join(lines))

    # Stats
    stats = data.get("stats", {})
    if stats:
        connected = stats.get("Connected", 0) + stats.get("Qualified", 0)
        total     = sum(stats.values())
        rate      = round(connected / total * 100) if total > 0 else 0
        print(f"[openoutreach-monitor] Stats: {total} total, {connected} connected ({rate}% acceptance)", flush=True)
        klog("openoutreach_stats", component="openoutreach-monitor",
             total=total, connected=connected, acceptance_rate_pct=rate,
             qualified=stats.get("Qualified", 0), pending=stats.get("Pending", 0),
             failed=stats.get("Failed", 0))

    state["last_connected_ids"] = list(seen_connected)
    state["last_reply_ids"]     = list(seen_replies)
    state["last_run"]           = datetime.now().isoformat()
    save_state(state)

    return new_events


if __name__ == "__main__":
    token = load_token()
    if token:
        count = run(token)
        print(f"[openoutreach-monitor] {count} new events", flush=True)
    else:
        print("[openoutreach-monitor] No BOT_TOKEN", flush=True)
