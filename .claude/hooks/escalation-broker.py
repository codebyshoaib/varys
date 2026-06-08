#!/usr/bin/env python3
"""
escalation-broker.py — Scan harness.db for stuck tickets and fire the escalation-broker agent.

Runs as part of the /loop tick AFTER orchestrator-dispatch.py.
A ticket is "stuck" if its session status is 'cancelled' or 'blocked' for 2+ consecutive ticks.
"""
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_harness_db import get_db
try:
    from kamil_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

KAMIL_DIR  = Path(__file__).parent.parent.parent
AGENTS_DIR = KAMIL_DIR / ".claude" / "agents"
STUCK_THRESHOLD_MINUTES = 9


def _get_stuck_tickets(db) -> list:
    threshold = (datetime.utcnow() - timedelta(minutes=STUCK_THRESHOLD_MINUTES)).isoformat()
    rows = db.execute("""
        SELECT DISTINCT context_key, MAX(updated_at) as last_update
        FROM sessions
        WHERE status IN ('cancelled', 'blocked')
          AND updated_at < ?
          AND context_key NOT IN (
              SELECT context_key FROM sessions
              WHERE status IN ('running', 'awaiting_approval')
          )
        GROUP BY context_key
    """, (threshold,)).fetchall()
    stuck = []
    for row in rows:
        context_key, last_update = row
        already = db.execute("""
            SELECT id FROM sessions
            WHERE context_key = ?
              AND intent LIKE '%escalation-broker%'
              AND created_at > datetime('now', '-1 day')
        """, (context_key,)).fetchone()
        if not already:
            stuck.append({"context_key": context_key, "last_update": last_update})
    return stuck


def _load_cfg() -> dict:
    cfg = {}
    for f in (Path.home() / ".claude" / "hooks" / ".slack",
              Path.home() / ".claude" / "hooks" / ".notion"):
        if f.exists():
            for line in f.read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    return cfg


def _spawn_broker(context_key: str) -> bool:
    broker_agent = AGENTS_DIR / "escalation-broker.md"
    if not broker_agent.exists():
        klog_error("escalation-broker-missing", Exception("agent file not found"),
                   component="escalation-broker")
        return False
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    prompt = (
        f"You are Kamil's escalation-broker. "
        f"Context key (Notion ticket entity): {context_key}. "
        f"Follow your protocol: partial delivery first, try different angle, then DM Kamal. "
        f"Harness DB: {Path.home() / '.kamil-harness' / 'harness.db'}"
    )
    tmp = Path(tempfile.mktemp(suffix=".txt"))
    tmp.write_text(prompt)
    try:
        result = subprocess.run(
            ["bash", "-c",
             f'{nvm} && claude --dangerously-skip-permissions --print -p "$(cat {tmp})"'],
            cwd=str(KAMIL_DIR), capture_output=True, text=True, timeout=300,
        )
        klog("escalation-broker-spawn", component="escalation-broker",
             context_key=context_key, returncode=result.returncode)
        return result.returncode == 0
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    db = get_db()
    stuck = _get_stuck_tickets(db)
    if not stuck:
        print("[escalation-broker] No stuck tickets.")
        db.close()
        return 0
    print(f"[escalation-broker] {len(stuck)} stuck ticket(s).")
    for ticket in stuck:
        try:
            _spawn_broker(ticket["context_key"])
        except Exception as e:
            klog_error("escalation-broker-error", e, component="escalation-broker",
                       context_key=ticket["context_key"])
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
