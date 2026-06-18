#!/usr/bin/env python3
"""
varys-apply-learnings.py — Varys's Application Agent.

After every research seed, this agent reads the new learnings and asks:
"Given what Varys just learned, what should change in how he builds?"

Then creates concrete Notion Harness tickets for each gap found.

This is the loop Shoaib described:
  Research → Learn → Apply → Improve → Better research next time

Called:
  - By brain_seed_from_content.py after seeding (inline)
  - Daily at 8am via cron (reviews all recent learnings)
  - Manually: python3 varys-apply-learnings.py [--days 7]
"""

import json
import os
import sqlite3
import subprocess
import sys
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_config import cfg
from varys_log import klog, klog_error
from varys_notion import notion_request

BRAIN_DB        = Path.home() / ".varys-harness" / "brain.db"
HARNESS_DB_ID   = cfg("NOTION_HARNESS_DB_ID", "de10157da3e34ef58a74ea240f31fe98")
NOTION_API      = "https://api.notion.com/v1"
SHOAIB_DM        = os.environ.get("USER_SLACK_DM", "")  # set USER_SLACK_DM in ~/.agent-config.json
SLACK_CFG       = Path.home() / ".claude" / "hooks" / ".slack"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_slack_token() -> str:
    if SLACK_CFG.exists():
        for line in SLACK_CFG.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def _notion_token() -> str:
    for path in [Path(__file__).parent.parent / ".claude" / "settings.json",
                 Path.home() / ".claude" / "settings.json"]:
        if not path.exists():
            continue
        try:
            cfg = json.loads(path.read_text())
            for name, srv in cfg.get("mcpServers", {}).items():
                if "notion" in name.lower():
                    for k, v in srv.get("env", {}).items():
                        if "token" in k.lower() or "key" in k.lower():
                            return v
        except Exception:
            pass
    notion_cfg = Path.home() / ".claude" / "hooks" / ".notion"
    if notion_cfg.exists():
        for line in notion_cfg.read_text().splitlines():
            if line.startswith("NOTION_API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("NOTION_TOKEN", "")


def get_recent_learnings(days: int = 1) -> list[dict]:
    """Fetch learning entities + all their facts from brain.db."""
    if not BRAIN_DB.exists():
        return []
    db = sqlite3.connect(str(BRAIN_DB))
    rows = db.execute("""
        SELECT e.id, e.name, f.predicate, f.object_val
        FROM entities e
        JOIN facts f ON f.subject_id = e.id
        WHERE e.type = 'learning'
          AND e.created_at >= datetime('now', ?)
        ORDER BY e.created_at DESC
    """, (f"-{days} days",)).fetchall()
    db.close()

    grouped = {}
    for eid, name, pred, val in rows:
        if eid not in grouped:
            grouped[eid] = {"id": eid, "name": name, "insights": [],
                            "lessons": [], "patterns": [], "tools": [], "summary": ""}
        if pred == "key_insight":
            grouped[eid]["insights"].append(val)
        elif pred == "lesson_learned":
            grouped[eid]["lessons"].append(val)
        elif pred == "pattern":
            grouped[eid]["patterns"].append(val)
        elif pred == "one_line_summary":
            grouped[eid]["summary"] = val
    return list(grouped.values())


def analyse_gaps(learnings: list[dict]) -> list[dict]:
    """Ask Claude to compare learnings against Varys's current harness and find gaps."""
    if not learnings:
        return []

    # Build a compact learning digest for Claude
    digest = []
    for l in learnings:
        digest.append(f"Topic: {l['name']}")
        if l["summary"]:
            digest.append(f"  Summary: {l['summary']}")
        for ins in l["insights"][:3]:
            digest.append(f"  Insight: {ins}")
        for lesson in l["lessons"]:
            digest.append(f"  Lesson: {lesson}")
        digest.append("")

    current_harness = """
Varys's current harness (what actually exists today):
- varys-listener.py: Socket Mode Slack daemon, started with nohup (not durable execution)
- orchestrator-dispatch.py: spawns claude subagents for Notion tickets
- varys-observer.py: hourly cron, detects anomalies, auto-fixes within a fence
- block-bad-commands.py: PreToolUse hook blocks git add -A, rm -rf, etc.
- brain.db: SQLite knowledge graph (entities + facts + links)
- stop.py: session end → git commit only, no learning extraction
- session-start.py: surfaces Slack inbox + Notion DBs
- content-scheduler.py: daily LinkedIn pipeline
- No adversarial agents checking Varys's own outputs
- No durable execution (agents die on reboot)
- No LLM-based fact extraction from session logs
- No auto-created Harness tickets when Varys makes repeated mistakes
- AGENTS.md / CLAUDE.md has rules but they are not all traceable to past failures
"""

    prompt = (
        f"You are reviewing Varys's AI agent harness. Here is what Varys just learned from research:\n\n"
        f"{chr(10).join(digest)}\n\n"
        f"{current_harness}\n\n"
        f"Identify 3-5 concrete gaps: things the research says should exist but don't in Varys's harness. "
        f"For each gap, output a JSON object with:\n"
        f"  title: short action title (max 10 words)\n"
        f"  what_to_build: 1-2 sentences of exactly what to implement\n"
        f"  why: which lesson/insight justifies this (quote it)\n"
        f"  priority: P0/P1/P2\n"
        f"  effort: small/medium/large\n\n"
        f"Output ONLY a JSON array of these objects. No explanation. No markdown."
    )

    try:
        r = subprocess.run(
            ["claude", "--dangerously-skip-permissions",
             "--model", "claude-sonnet-4-6",
             "--print", "-p", prompt],
            capture_output=True, text=True, timeout=90,
        )
        raw = r.stdout.strip()
        start = raw.find("[")
        end   = raw.rfind("]") + 1
        if start >= 0 and end > start:
            gaps = json.loads(raw[start:end])
            print(f"[apply-learnings] Found {len(gaps)} gaps to act on")
            return gaps
    except Exception as e:
        print(f"[apply-learnings] Gap analysis failed: {e}")
    return []


def _fetch_existing_ticket_titles(notion_token: str) -> "set[str] | None":
    """Return normalised set of existing [Auto] ticket titles from Harness DB. None on error."""
    titles  = set()
    cursor  = None
    while True:
        payload = {
            "filter":    {"property": "Feature", "title": {"contains": "[Auto]"}},
            "page_size": 100,
        }
        if cursor:
            payload["start_cursor"] = cursor
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{NOTION_API}/databases/{HARNESS_DB_ID}/query", data=data,
            headers={
                "Authorization":  f"Bearer {notion_token}",
                "Content-Type":   "application/json",
                "Notion-Version": "2022-06-28",
            },
        )
        try:
            # TODO: migrate to varys_notion.notion_request() (orchestrator.md Hard Rule #3)
            with urllib.request.urlopen(req, timeout=10) as r:
                result = json.loads(r.read())
        except Exception as e:
            print(f"[apply-learnings] Could not fetch existing titles (aborting to avoid duplicates): {e}")
            return None
        for page in result.get("results", []):
            raw = page["properties"].get("Feature", {}).get("title", [])
            if raw:
                titles.add(raw[0]["plain_text"].lower())
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")
    return titles


def _is_duplicate(gap: dict, existing_titles: set[str]) -> bool:
    """Return True if a ticket for this gap already exists."""
    raw_title  = gap["title"].strip()
    clean      = raw_title[7:].strip() if raw_title.lower().startswith("[auto]") else raw_title
    normalised = f"[auto] {clean.lower()}"
    return normalised in existing_titles


def create_harness_ticket(gap: dict, notion_token: str) -> str:
    """Create a Notion Harness ticket for a gap. Returns page ID."""
    title    = f"[Auto] {gap['title']}"
    body     = f"{gap['what_to_build']}\n\nWhy: {gap['why']}\nEffort: {gap['effort']}"
    priority = gap.get("priority", "P1")

    props = {
        "Feature":      {"title":     [{"text": {"content": title}}]},
        "Phase":        {"select":    {"name": "Backlog"}},
        "Plan Summary": {"rich_text": [{"text": {"content": body[:1800]}}]},
    }

    data = json.dumps({
        "parent":     {"database_id": HARNESS_DB_ID},
        "properties": props,
    }).encode()

    try:
        req = urllib.request.Request(
            f"{NOTION_API}/pages", data=data,
            headers={
                "Authorization":  f"Bearer {notion_token}",
                "Content-Type":   "application/json",
                "Notion-Version": "2022-06-28",
            },
        )
        # TODO: migrate to varys_notion.notion_request() (orchestrator.md Hard Rule #3)
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())
            page_id = result.get("id", "")
            print(f"[apply-learnings] Harness ticket created: {title[:60]} → {page_id[:8]}")
            return page_id
    except Exception as e:
        print(f"[apply-learnings] Notion ticket creation failed: {e}")
        return ""


def _format_slack_message(created: list[dict], learning_names: list[str]) -> str:
    topics = ", ".join(f"*{n.split(']')[-1].strip()[:30]}*" for n in learning_names)
    lines  = [f"🧠 *Varys learned + applied:* {topics}\n"]
    for item in created:
        g         = item["gap"]
        page_id   = item.get("page_id", "")
        notion_url = (
            f"https://notion.so/{page_id.replace('-', '')}"
            if page_id else ""
        )
        lines.append(f"• *[{g.get('priority','P1')}]* {g['title']}")
        lines.append(f"  _{g['what_to_build'][:100]}_")
        lines.append(f"  > {g.get('why','')[:120]}")
        if notion_url:
            lines.append(f"  <{notion_url}|Open in Notion>")
    lines.append(f"\n{len(created)} ticket(s) created — Varys will build these.\n🤖 Varys")
    return "\n".join(lines)


def slack_dm(token: str, text: str):
    if not token:
        return
    data = json.dumps({"channel": SHOAIB_DM, "text": text}).encode()
    req  = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", data=data,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type":  "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
    except Exception:
        pass


def run(days: int = 1, notify_slack: bool = True):
    """Main entry point. Analyse recent learnings, create Harness tickets for gaps."""
    learnings = get_recent_learnings(days)
    if not learnings:
        print(f"[apply-learnings] No learnings from last {days} day(s) — nothing to apply")
        return

    print(f"[apply-learnings] Analysing {len(learnings)} learning(s) for actionable gaps...")
    gaps = analyse_gaps(learnings)
    if not gaps:
        print("[apply-learnings] No gaps identified")
        return

    notion_token = _notion_token()
    slack_token  = _load_slack_token()
    if notion_token:
        existing = _fetch_existing_ticket_titles(notion_token)
        if existing is None:
            print("[apply-learnings] Cannot confirm existing tickets — aborting to prevent duplicates")
            return
    else:
        existing = set()
    created      = []

    for gap in gaps:
        if _is_duplicate(gap, existing):
            print(f"[apply-learnings] Skip duplicate: {gap['title']}")
            continue
        page_id = create_harness_ticket(gap, notion_token) if notion_token else ""
        if page_id:
            raw_t = gap["title"].strip()
            clean_t = raw_t[7:].strip() if raw_t.lower().startswith("[auto]") else raw_t
            existing.add(f"[auto] {clean_t.lower()}")
            created.append({"gap": gap, "page_id": page_id})
            klog("apply_learning_ticket", component="varys-apply-learnings",
                 title=gap["title"], priority=gap.get("priority"), page_id=page_id[:8])
        else:
            print(f"[apply-learnings] Notion creation failed for: {gap['title']}")
            klog("apply_learning_ticket_failed", component="varys-apply-learnings",
                 title=gap["title"], priority=gap.get("priority"))

    if notify_slack and slack_token and created:
        text = _format_slack_message(created, [l["name"] for l in learnings])
        slack_dm(slack_token, text)

    print(f"[apply-learnings] Done — {len(created)} Harness ticket(s) created")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--days",         type=int, default=1, help="Look back N days")
    p.add_argument("--no-slack",     action="store_true")
    args = p.parse_args()
    run(days=args.days, notify_slack=not args.no_slack)
