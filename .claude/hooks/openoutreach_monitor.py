#!/usr/bin/env python3
"""
openoutreach-monitor.py — Watches OpenOutreach SQLite DB for new events.

Called by job-finder.py every 30 min. Detects:
  - New accepted LinkedIn connections (CONNECTED state)
  - New replies from leads (conversation activity)
  - Campaign stats (sent, accepted rate)

On new accepted connection → DM Kamal → save to Notion Job Tracker as LinkedIn lead.
On new reply → DM Kamal → update Job Tracker entry.

DB path: ~/.openoutreach/data/db.sqlite3
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
    """
    if not OPENOUTREACH_DB.exists():
        return {"running": False}

    try:
        conn  = sqlite3.connect(str(OPENOUTREACH_DB))
        conn.row_factory = sqlite3.Row
        cur   = conn.cursor()

        # Get table names to understand schema version
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]

        result = {"running": True, "tables": tables,
                  "new_connections": [], "new_replies": [], "stats": {}}

        # Try to read LinkedIn profiles in CONNECTED state
        if "crm_linkedinprofile" in tables:
            cur.execute("""
                SELECT id, first_name, last_name, headline, company, profile_url,
                       state, created_at, updated_at
                FROM crm_linkedinprofile
                WHERE state IN ('CONNECTED', 'COMPLETED')
                ORDER BY updated_at DESC
                LIMIT 50
            """)
            result["new_connections"] = [dict(r) for r in cur.fetchall()]

        # Try to read conversation/message activity
        if "crm_message" in tables:
            cur.execute("""
                SELECT id, profile_id, content, direction, created_at
                FROM crm_message
                WHERE direction = 'INBOUND'
                ORDER BY created_at DESC
                LIMIT 20
            """)
            result["new_replies"] = [dict(r) for r in cur.fetchall()]

        # Campaign stats
        if "crm_linkedinprofile" in tables:
            cur.execute("SELECT state, COUNT(*) as cnt FROM crm_linkedinprofile GROUP BY state")
            result["stats"] = {r["state"]: r["cnt"] for r in cur.fetchall()}

        conn.close()
        return result

    except Exception as e:
        return {"running": True, "error": str(e)}


def get_conversation_context(lead_id: int, limit: int = 5) -> str:
    """Return last `limit` messages for a lead as formatted string. Fails silently."""
    if not OPENOUTREACH_DB.exists():
        return ""
    try:
        conn = sqlite3.connect(str(OPENOUTREACH_DB))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # chat_chatmessage.object_id = crm_lead.id (Django ContentType FK)
        # is_outgoing: True = we sent, False = prospect replied
        # Must also filter by content_type_id to avoid cross-model collisions
        cur.execute(
            "SELECT id FROM django_content_type WHERE app_label='crm' AND model='lead'"
        )
        ct_row = cur.fetchone()
        if ct_row is None:
            conn.close()
            return ""
        ct_id = ct_row["id"]
        cur.execute("""
            SELECT content, creation_date, is_outgoing
            FROM chat_chatmessage
            WHERE object_id = ? AND content_type_id = ?
            ORDER BY creation_date DESC
            LIMIT ?
        """, (lead_id, ct_id, limit))
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return ""
        lines = ["*Conversation (latest first):*"]
        for row in rows:
            content = (row["content"] or "")[:200]
            ts = (row["creation_date"] or "")[:16]
            direction = "You" if row["is_outgoing"] else "Prospect"
            lines.append(f"  [{ts}] {direction}: {content}")
        return "\n".join(lines)
    except Exception:
        return ""


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
            name    = f"{c.get('first_name','')} {c.get('last_name','')}".strip()
            title   = c.get("headline", "")[:60]
            company = c.get("company", "")
            url     = c.get("profile_url", "")
            lines.append(f"• *{name}* — {title}")
            if company:
                lines.append(f"  {company}")
            if url:
                lines.append(f"  {url}")
            lines.append("")
            save_linkedin_lead_to_notion(name, title, company, url, "OpenOutreach connection")
            seen_connected.add(str(c["id"]))
            new_events += 1

        if len(new_connections) > 5:
            lines.append(f"_(+{len(new_connections)-5} more — check Notion Job Tracker)_")

        lines.append("_Reply \"followup [name]\" and I'll write a message._\n🤖 Kamil")
        slack_dm(token, "\n".join(lines))

    # New inbound replies
    new_replies = [
        r for r in data.get("new_replies", [])
        if str(r["id"]) not in seen_replies
    ]

    if new_replies:
        lines = ["💬 *LinkedIn replies via OpenOutreach:*\n"]
        for r in new_replies[:3]:
            content = r.get("content", "")[:120]
            lines.append(f"• \"{content}\"")
            profile_id = r.get("profile_id")
            if profile_id:
                try:
                    _conn = sqlite3.connect(str(OPENOUTREACH_DB))
                    _conn.row_factory = sqlite3.Row
                    _row = _conn.execute(
                        "SELECT self_lead_id FROM linkedin_linkedinprofile WHERE id=?",
                        (profile_id,)
                    ).fetchone()
                    _conn.close()
                    lead_id = _row["self_lead_id"] if _row and _row["self_lead_id"] else None
                except Exception:
                    lead_id = None
                if lead_id:
                    ctx = get_conversation_context(int(lead_id))
                    if ctx:
                        lines.append(ctx)
            seen_replies.add(str(r["id"]))
            new_events += 1
        lines.append("\n_Check OpenOutreach admin to respond: http://localhost:8000/admin_")
        lines.append("🤖 Kamil")
        slack_dm(token, "\n".join(lines))

    # Log new connections and replies to Axiom
    if new_connections:
        for c in new_connections:
            name = f"{c.get('first_name','')} {c.get('last_name','')}".strip()
            klog("linkedin_connection_accepted", component="openoutreach-monitor",
                 name=name, headline=c.get("headline","")[:80],
                 company=c.get("company",""), state=c.get("state",""))
    if new_replies:
        for r in new_replies:
            klog("linkedin_reply_received", component="openoutreach-monitor",
                 content_preview=r.get("content","")[:100])

    # Stats logging
    stats = data.get("stats", {})
    if stats:
        sent      = stats.get("PENDING", 0) + stats.get("CONNECTED", 0) + stats.get("COMPLETED", 0)
        connected = stats.get("CONNECTED", 0) + stats.get("COMPLETED", 0)
        rate      = round(connected / sent * 100) if sent > 0 else 0
        print(f"[openoutreach-monitor] Stats: {sent} sent, {connected} connected ({rate}% acceptance)", flush=True)
        klog("openoutreach_stats", component="openoutreach-monitor",
             sent=sent, connected=connected, acceptance_rate_pct=rate,
             qualified=stats.get("QUALIFIED", 0), pending=stats.get("PENDING", 0))

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
