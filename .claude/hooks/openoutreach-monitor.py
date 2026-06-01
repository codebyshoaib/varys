#!/usr/bin/env python3
"""
openoutreach-monitor.py — Watches OpenOutreach SQLite DB for new events.

Called by job-finder.py every 30 min. Detects:
  - New accepted LinkedIn connections (Connected state in crm_deal)
  - New inbound replies (chat_chatmessage where is_outgoing=0)
  - Stuck task queue (pending tasks that never started — happens after restart)

On new inbound reply:
  1. Pauses automation for that deal (sets state → Completed, outcome → bad_timing)
     so the bot stops firing automated messages at someone who replied
  2. DMs Kamal with: profile, full conversation thread, drafted value-first reply
  3. Saves message ID to state — no duplicate alerts

On new accepted connection:
  → DM Kamal, save to Notion Job Tracker

DB path: /home/oye/.openoutreach/data/db.sqlite3
  = Docker volume mount of /app/data/db.sqlite3 inside the container
  Path.home() / ".openoutreach/data/db.sqlite3" resolves correctly on this host.

Schema (correct):
  crm_deal          — id, state, outcome, profile_summary, chat_summary, lead_id, campaign_id
  crm_lead          — id, linkedin_url, public_identifier, urn
  chat_chatmessage  — id, content, is_outgoing, creation_date, linkedin_urn, object_id
  NOT crm_linkedinprofile — that table does not exist
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

# DB is at ~/.openoutreach/data/db.sqlite3 on the host.
# This is a Docker bind-mount of /app/data inside the openoutreach container.
# Verified: docker inspect shows /home/oye/.openoutreach/data -> /app/data
OPENOUTREACH_DB  = Path.home() / ".openoutreach" / "data" / "db.sqlite3"
STATE_FILE       = Path("/tmp/kamil-openoutreach-state.json")
KAMIL_DIR        = Path(__file__).parent.parent.parent
KAMAL_DM         = "D0B415M06SK"
JOBS_DB          = "0d69c6ff-83d8-44c7-94c2-d341c4ded8d7"
SLACK_CONFIG     = Path.home() / ".claude" / "hooks" / ".slack"


# ---------------------------------------------------------------------------
# Slack helpers
# ---------------------------------------------------------------------------

def load_token() -> str:
    if SLACK_CONFIG.exists():
        for line in SLACK_CONFIG.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def slack_dm(token: str, text: str) -> str:
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


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_connected_ids": [], "last_reply_ids": [], "last_run": ""}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Phase 3 — Reply handoff
# ---------------------------------------------------------------------------

def _get_conversation_for_lead(conn, lead_id: int) -> list[dict]:
    """Load full conversation thread for a lead from chat_chatmessage."""
    cur = conn.cursor()
    cur.execute("""
        SELECT content, is_outgoing, creation_date
        FROM chat_chatmessage
        WHERE object_id = ?
        ORDER BY creation_date ASC
    """, (lead_id,))
    return [
        {
            "content": r[0] or "",
            "is_outgoing": bool(r[1]),
            "creation_date": r[2] or "",
        }
        for r in cur.fetchall()
    ]


def _format_conversation(messages: list[dict], now: datetime) -> str:
    """Format conversation as a readable thread with relative timestamps."""
    lines = []
    for m in messages:
        speaker = "You" if m["is_outgoing"] else "Them"
        ts = m["creation_date"][:16] if m["creation_date"] else "?"
        # Relative time
        try:
            t = datetime.fromisoformat(m["creation_date"])
            diff = now - t
            if diff.days > 0:
                age = f"{diff.days}d ago"
            elif diff.seconds > 3600:
                age = f"{diff.seconds // 3600}h ago"
            else:
                age = f"{diff.seconds // 60}m ago"
        except Exception:
            age = ts
        content = (m["content"] or "").strip()[:200]
        lines.append(f"  {speaker} ({age}): {content}")
    return "\n".join(lines) if lines else "  (no messages found)"


def _draft_value_first_reply(profile_summary: dict | None, handle: str) -> str:
    """
    Draft a value-first reply based on profile facts.
    Picks the most relevant repetitive task for their role.
    """
    facts = (profile_summary or {}).get("facts", []) if isinstance(profile_summary, dict) else []
    facts_text = " ".join(facts).lower()

    # Role → task mapping
    task_map = [
        (["agency", "marketing agency", "outreach agency"],
         "manually pulling client reports and sending campaign updates"),
        (["recruitment", "hiring", "talent"],
         "manually screening candidates and chasing responses"),
        (["real estate", "broker", "property"],
         "manually following up with leads and qualifying buyers"),
        (["e-commerce", "ecommerce", "shopify", "store"],
         "manually handling support tickets and order issues"),
        (["customer support", "support manager", "cx"],
         "manually triaging tickets and writing first responses"),
        (["sales ops", "sales operations", "crm", "revenue ops"],
         "manually routing leads and updating CRM records"),
        (["operations", "ops manager", "process"],
         "manually tracking tasks across spreadsheets and tools"),
        (["founder", "ceo", "owner", "co-founder"],
         "manually doing work that should already be automated"),
        (["product manager", "pm", "product"],
         "manually chasing status updates and compiling reports"),
    ]

    task = "manually handling repetitive operational work"
    for keywords, matched_task in task_map:
        if any(kw in facts_text for kw in keywords):
            task = matched_task
            break

    return (
        f"Hey — I build small AI agents that handle {task}. "
        f"I made a quick demo for a similar use case — happy to send it over if it's relevant. "
        f"What does your current setup look like for that?"
    )


def _pause_deal_automation(handle: str) -> bool:
    """
    Stop automated follow-ups for a deal by setting state=Completed, outcome=bad_timing.
    Runs via Django shell inside the container. Returns True if successful.
    """
    script = (
        f"from crm.models import Deal; "
        f"d = Deal.objects.filter(lead__public_identifier='{handle}').first(); "
        f"d and (setattr(d, 'state', 'Completed') or setattr(d, 'outcome', 'bad_timing') or d.save()); "
        f"print('paused' if d else 'not_found')"
    )
    try:
        result = subprocess.run(
            ["docker", "exec", "openoutreach", "python", "manage.py", "shell", "-c", script],
            capture_output=True, text=True, timeout=15
        )
        output = result.stdout.strip()
        print(f"[openoutreach-monitor] pause_deal {handle}: {output}", flush=True)
        return "paused" in output
    except Exception as e:
        print(f"[openoutreach-monitor] pause_deal {handle} failed: {e}", flush=True)
        return False


def handle_inbound_replies(conn, token: str, seen_reply_ids: set) -> tuple[list[str], int]:
    """
    Detect new inbound messages on Connected/Qualified deals.
    For each new reply:
      - Pause automation (set deal Completed/bad_timing)
      - DM Kamal with full context + drafted reply
    Returns (updated seen_ids_list, new_event_count).
    """
    cur = conn.cursor()
    now = datetime.now()

    # Get all inbound messages on active deals (Connected or Qualified)
    cur.execute("""
        SELECT
            m.id, m.content, m.creation_date, m.linkedin_urn, m.object_id,
            d.id as deal_id, d.state, d.profile_summary,
            l.public_identifier, l.linkedin_url
        FROM chat_chatmessage m
        JOIN crm_lead l ON m.object_id = l.id
        JOIN crm_deal d ON d.lead_id = l.id
        WHERE m.is_outgoing = 0
          AND d.state IN ('Connected', 'Qualified')
        ORDER BY m.creation_date DESC
        LIMIT 30
    """)
    rows = cur.fetchall()

    new_events = 0
    for row in rows:
        msg_id = str(row[0])
        if msg_id in seen_reply_ids:
            continue

        content      = (row[1] or "").strip()
        handle       = row[8] or "unknown"
        linkedin_url = row[9] or f"https://linkedin.com/in/{handle}"
        deal_state   = row[6] or ""

        # Parse profile_summary
        try:
            profile_summary = json.loads(row[7]) if row[7] else {}
        except Exception:
            profile_summary = {}

        facts = (profile_summary.get("facts") or [])[:5]
        profile_text = "\n".join(f"  - {f}" for f in facts) if facts else "  (no profile data)"

        # Full conversation thread
        lead_id = row[4]
        conversation = _get_conversation_for_lead(conn, lead_id)
        thread_text = _format_conversation(conversation, now)

        # Draft value-first reply
        draft = _draft_value_first_reply(profile_summary, handle)

        # 1. Pause automation BEFORE alerting Kamal
        paused = _pause_deal_automation(handle)
        pause_note = "⏸ Automation paused." if paused else "⚠️ Could not pause automation — pause manually."

        # 2. DM Kamal
        lines = [
            f"🔥 *{handle} just replied on LinkedIn*",
            "",
            f"*Profile:*",
            profile_text,
            f"  {linkedin_url}",
            "",
            f"*Conversation:*",
            thread_text,
            "",
            f"*Suggested reply:*",
            f'"{draft}"',
            "",
            pause_note,
            f'Reply *"followup {handle}"* and I\'ll send this. Or respond manually on LinkedIn.',
            "🤖 Kamil",
        ]
        slack_dm(token, "\n".join(lines))

        seen_reply_ids.add(msg_id)
        new_events += 1

        klog("linkedin_reply_received", component="openoutreach-monitor",
             handle=handle, deal_state=deal_state, automation_paused=paused,
             content_preview=content[:100])

        print(f"[openoutreach-monitor] Reply from @{handle} — automation {'paused' if paused else 'NOT paused'}", flush=True)

    return list(seen_reply_ids), new_events


# ---------------------------------------------------------------------------
# Stuck task queue detection
# ---------------------------------------------------------------------------

def check_stuck_tasks(conn, token: str):
    """
    Warn if tasks are queued but not starting — happens after container restart.
    Fires once per stuck state (tracks in state file).
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM linkedin_task
        WHERE status = 'pending' AND started_at IS NULL
          AND scheduled_at < datetime('now', '-2 hours')
    """)
    stuck = cur.fetchone()[0]
    if stuck > 5:
        print(f"[openoutreach-monitor] ⚠️  {stuck} stuck pending tasks (not started in 2+ hours)", flush=True)
        slack_dm(token,
            f"⚠️ *OpenOutreach: {stuck} tasks are stuck* (pending but never started).\n"
            f"The daemon may have stopped. Check: `docker logs openoutreach --tail 20`\n"
            f"Restart if needed: `docker restart openoutreach`\n🤖 Kamil"
        )


# ---------------------------------------------------------------------------
# New connections
# ---------------------------------------------------------------------------

def save_linkedin_lead_to_notion(name: str, title: str, company: str,
                                  profile_url: str, message: str):
    today = datetime.now().strftime("%Y-%m-%d")
    props = {
        "Job Title":        f"LinkedIn: {name} — {title or 'Unknown role'}",
        "Company":          company or "Unknown",
        "Platform":         "linkedin",
        "Status":           "new",
        "Score":            60,
        "Why It Matches":   f"Accepted OpenOutreach connection. Message: {message[:200]}",
        "Proposal Written": "no",
        "date:Date Found:start": today,
    }
    prompt = (
        f"Use mcp__claude_ai_Notion__notion-create-pages to add ONE page to DB {JOBS_DB}.\n"
        f"Properties:\n{json.dumps(props, indent=2)}\nReply only \"ok\"."
    )
    env = os.environ.copy()
    env["KAMIL_LINKEDIN_PROMPT"] = prompt
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    subprocess.Popen(
        ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$KAMIL_LINKEDIN_PROMPT"'],
        cwd=str(KAMIL_DIR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def handle_new_connections(conn, token: str, seen_connected_ids: set) -> tuple[list[str], int]:
    """Detect new Connected/Qualified deals and DM Kamal."""
    cur = conn.cursor()
    cur.execute("""
        SELECT d.id, d.state, d.profile_summary, l.linkedin_url, l.public_identifier
        FROM crm_deal d
        JOIN crm_lead l ON d.lead_id = l.id
        WHERE d.state IN ('Connected', 'Qualified')
        ORDER BY d.update_date DESC
        LIMIT 50
    """)
    rows = cur.fetchall()

    new_events = 0
    new_rows = [r for r in rows if str(r[0]) not in seen_connected_ids]

    if new_rows:
        lines = ["🤝 *New LinkedIn connections (OpenOutreach):*\n"]
        for r in new_rows[:5]:
            deal_id    = str(r[0])
            state_val  = r[1] or ""
            handle     = r[4] or ""
            url        = r[3] or f"https://linkedin.com/in/{handle}"
            try:
                summary = json.loads(r[2]) if r[2] else {}
                facts   = (summary.get("facts") or [])[:2]
                summary_text = " | ".join(facts)
            except Exception:
                summary_text = ""
            lines.append(f"• *{handle}* ({state_val})")
            if summary_text:
                lines.append(f"  {summary_text}")
            lines.append(f"  {url}\n")
            save_linkedin_lead_to_notion(handle, summary_text, "", url, "OpenOutreach connection")
            seen_connected_ids.add(deal_id)
            new_events += 1

        if len(new_rows) > 5:
            lines.append(f"_(+{len(new_rows)-5} more — check Notion Job Tracker)_")
        lines.append('_Reply "followup [name]" and I\'ll write a value-first message._\n🤖 Kamil')
        slack_dm(token, "\n".join(lines))

    return list(seen_connected_ids), new_events


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def ensure_prompt_patched():
    """Re-apply value-first template patch if container was restarted."""
    restore = Path(__file__).parent / "openoutreach-restore-prompt.py"
    if restore.exists():
        subprocess.run([sys.executable, str(restore)], capture_output=True, timeout=20)


def run(token: str) -> int:
    if not OPENOUTREACH_DB.exists():
        print(f"[openoutreach-monitor] DB not found at {OPENOUTREACH_DB}", flush=True)
        return 0

    # Phase 2c — re-apply prompt patch if container was restarted
    ensure_prompt_patched()

    state = load_state()

    try:
        conn = sqlite3.connect(str(OPENOUTREACH_DB))
        conn.row_factory = sqlite3.Row
    except Exception as e:
        klog_error(context="openoutreach-db", exc=e, component="openoutreach-monitor")
        return 0

    try:
        # Stats
        cur = conn.cursor()
        cur.execute("SELECT state, COUNT(*) as cnt FROM crm_deal GROUP BY state")
        stats = {r[0]: r[1] for r in cur.fetchall()}
        connected = stats.get("Connected", 0) + stats.get("Qualified", 0)
        total     = sum(stats.values())
        rate      = round(connected / total * 100) if total > 0 else 0
        print(f"[openoutreach-monitor] Stats: {total} total, {connected} active ({rate}% acceptance)", flush=True)
        klog("openoutreach_stats", component="openoutreach-monitor",
             total=total, connected=connected, acceptance_rate_pct=rate,
             qualified=stats.get("Qualified", 0), pending=stats.get("Pending", 0),
             failed=stats.get("Failed", 0))

        # Phase 3 — Reply handoff (runs first — protect active conversations)
        seen_reply_ids = set(state.get("last_reply_ids", []))
        seen_reply_ids, reply_events = handle_inbound_replies(conn, token, seen_reply_ids)
        state["last_reply_ids"] = list(seen_reply_ids)

        # New connections
        seen_connected = set(state.get("last_connected_ids", []))
        seen_connected, conn_events = handle_new_connections(conn, token, seen_connected)
        state["last_connected_ids"] = list(seen_connected)

        # Stuck task queue check
        check_stuck_tasks(conn, token)

        new_events = reply_events + conn_events

    except Exception as e:
        klog_error(context="openoutreach-monitor", exc=e, component="openoutreach-monitor")
        print(f"[openoutreach-monitor] Error: {e}", flush=True)
        new_events = 0
    finally:
        conn.close()

    state["last_run"] = datetime.now().isoformat()
    save_state(state)

    return new_events


if __name__ == "__main__":
    token = load_token()
    if not token:
        print("[openoutreach-monitor] No BOT_TOKEN found", flush=True)
        sys.exit(1)
    count = run(token)
    print(f"[openoutreach-monitor] {count} new events", flush=True)
