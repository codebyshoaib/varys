#!/usr/bin/env python3
"""Best-effort: surface open beads so a Claude session can mirror them to the Notion
Harness DB (de10157da3e34ef58a74ea240f31fe98). Pure read + print. Never blocks work."""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_config import cfg

STATUS = Path(__file__).resolve().parents[1] / ".." / ".beads" / "status.jsonl"
HARNESS_DB = cfg("NOTION_HARNESS_DB_ID", "de10157da3e34ef58a74ea240f31fe98")

def main():
    try:
        open_beads = []
        for line in STATUS.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("status") in ("open", "in_progress"):
                open_beads.append(d)
        if not open_beads:
            sys.exit(0)
        print(f"[beads] {len(open_beads)} open bead(s). Mirror to Notion Harness DB {HARNESS_DB} via mcp__claude_ai_Notion__* if not already present:")
        for d in open_beads[-10:]:
            print(f"  [{d.get('priority','?')}] {d.get('id')}: {d.get('title')} ({d.get('status')})")
    except Exception:
        pass
    sys.exit(0)

if __name__ == "__main__":
    main()
