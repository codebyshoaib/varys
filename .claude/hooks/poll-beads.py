#!/usr/bin/env python3
"""
poll-beads.py — Poll beads (bd) work queue for ready tickets.

Replaces poll-harness-notion.py in the tick pipeline.
Same exit-code contract:
  0 = ran ok
  2 = not configured (bd missing)
  other = abort tick

Reads: bd ready --json
Writes: harness.db events + entities for each ready bead.

Design rules:
  - Deterministic event IDs: "beads-<bead_id>"
  - INSERT OR IGNORE — re-polling is always safe
  - If bd binary missing: exit 2 (skip, tick continues)
  - Any other failure: exit 1 (abort tick — rule 6)
"""

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from varys_harness_db import get_db, register_entity
try:
    from varys_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None


def _find_bd() -> str | None:
    """Return path to bd binary, or None if not found."""
    found = shutil.which("bd")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "bd"
    if candidate.exists():
        return str(candidate)
    return None


def main() -> int:
    bd_bin = _find_bd()
    if not bd_bin:
        print("[poll-beads] bd not found — skipping (exit 2)", file=sys.stderr)
        return 2

    # Determine repo root (varys repo) for bd cwd
    repo_dir = Path(__file__).resolve().parent.parent.parent

    try:
        r = subprocess.run(
            [bd_bin, "ready", "--json"],
            capture_output=True, text=True,
            cwd=str(repo_dir), timeout=15,
        )
    except Exception as e:
        print(f"[poll-beads] ERROR running bd ready: {e}", file=sys.stderr)
        klog_error("poll-beads-run", e, component="orchestrator")
        return 1

    if r.returncode != 0:
        print(f"[poll-beads] bd ready exited {r.returncode}: {r.stderr[:200]}", file=sys.stderr)
        klog_error("poll-beads-rc", None, component="orchestrator",
                   rc=r.returncode, stderr=r.stderr[:200])
        return 1

    output = r.stdout.strip()
    if not output:
        print("[poll-beads] No ready beads.")
        klog("poll-beads", component="orchestrator", action="poll", beads=0, new_events=0)
        return 0

    try:
        beads = json.loads(output)
    except json.JSONDecodeError as e:
        print(f"[poll-beads] ERROR parsing bd output: {e}\nOutput: {output[:200]}", file=sys.stderr)
        klog_error("poll-beads-parse", e, component="orchestrator")
        return 1

    if not isinstance(beads, list):
        print(f"[poll-beads] ERROR: expected JSON array, got {type(beads).__name__}", file=sys.stderr)
        return 1

    db = get_db()
    new_events = 0

    for bead in beads:
        bead_id = bead.get("id", "")
        title   = bead.get("title", "")
        status  = bead.get("status", "open")

        if not bead_id:
            continue

        # Register entity: source='beads', external_id=bead_id, url="beads:<bead_id>"
        entity_id = register_entity(db, "beads", bead_id, "ticket", f"beads:{bead_id}")

        # Deterministic event ID: "beads-<bead_id>"
        event_id = f"beads-{bead_id}"
        payload  = json.dumps({"id": bead_id, "title": title, "status": status})

        db.execute(
            "INSERT OR IGNORE INTO events "
            "(id, source, type, context_key, payload, status, received_at) "
            "VALUES (?, 'beads', 'ticket.created', ?, ?, 'pending', datetime('now'))",
            (event_id, entity_id, payload),
        )
        if db.execute("SELECT changes()").fetchone()[0] > 0:
            new_events += 1
            print(f"[poll-beads] ticket.created: {title[:60]}")
        db.commit()

    print(f"[poll-beads] Done. {len(beads)} ready beads, {new_events} new events.")
    klog("poll-beads", component="orchestrator", action="poll",
         beads=len(beads), new_events=new_events)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
