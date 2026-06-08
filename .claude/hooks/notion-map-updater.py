#!/usr/bin/env python3
"""
notion-map-updater.py — Keeps vault/notion-map.md current.

Two modes:
  --mode session  (stop hook): appends timestamped 1-line activity entry
  --mode daily    (2am cron):  full regenerate — scans all hooks for DB IDs,
                               updates Last full scan timestamp, rewrites file

Usage:
  python3 notion-map-updater.py --mode session --summary "posted content, updated harness"
  python3 notion-map-updater.py --mode daily
"""

import argparse
import re
import subprocess
from datetime import datetime
from pathlib import Path
import sys as _sys, time as _time
_sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
try:
    from agent_config import cfg as _cfg_map
except Exception:
    _cfg_map = lambda k, d=None: d
try:
    import kamil_log as _k
except Exception:
    _k = None

KAMIL_DIR  = Path(__file__).parent.parent.parent
MAP_FILE   = KAMIL_DIR / "vault" / "notion-map.md"
HOOKS_DIR  = Path(__file__).parent

# Known DB IDs with names — source of truth (normalized, no dashes)
KNOWN_DBS = {
    "18017a67136a4561ada9818c239b8f33": "My PRs",
    "0b71db855f914d18ac6d97c0f77fc21e": "Work Log",
    "6d14f1b6b8cd4ff68fd40efdfc3f304e": "Slack Inbox",
    _cfg_map("NOTION_HARNESS_DB_ID", "de10157da3e34ef58a74ea240f31fe98"): "Harness",
    "0d69c6ff83d844c794c2d341c4ded8d7": "Job Tracker",
    "c976d58ea4e34b0585f245529cdc4528": "People Intelligence",
    "94017dd157b44f3ca96423ad2ad989da": "Eval Log",
    "27e287b7a3d146c6b5e8eb0d862d746f": "Health Log",
    "68792d2dfff84691a4f646f5a8126149": "Content Calendar",
    "630d86afb17746f9ad6f9bc78afefa02": "Content Log",
    # Page IDs
    "364d8747b3b1813d8ac8c248800f0a4d": "Kamal's Agent Brain (page)",
    "365d8747b3b181b281b8ef5820e15881": "Kamil Self-Questions (page)",
    "369d8747b3b181d59775dcb4297d7dbd": "Master Plan / Freelance (page)",
    # Data source IDs
    "8749992f61404e728b487362533cb792": "Slack Inbox (data source)",
    "2e46d119159e46349195a7343e590dbe": "Eval Log (data source)",
    "2e46d119159e463491954a7343e590db": "Eval Log (data source alt)",
    "c00daef1c0724263b23de1b5e2ba596c": "People Intelligence (data source)",
    "a173fd5ab9534a53a0204545db41ccb5": "Harness (data source)",
    # NotebookLM notebook IDs (external, not Notion DBs — tracked here for reference)
    "76624bf582ce4f11b379e07f308c6c4a": "NLM: Instagram notebook",
    "a2e6473abc3c4737b1b93c67e1fb94ae": "NLM: Work/Taleemabad notebook",
    "a03e5a92d7064ffb9bd7a3498dc7779d": "NLM: Harness/Taleemabad notebook",
    "1a76701b9e16411f9c2eea73223a8695": "NLM: Reddit Jobs notebook (298 sources)",
}

# DB ID regex — matches both 32-char hex and UUID formats
DB_ID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    r'|[0-9a-f]{32}',
    re.IGNORECASE,
)

ACTIVITY_START = "<!-- ACTIVITY_LOG_START -->"
ACTIVITY_END   = "<!-- ACTIVITY_LOG_END -->"
LAST_SCAN_RE   = re.compile(r"Last full scan:.*")


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[notion-map {ts}] {msg}", flush=True)


def session_mode(summary: str):
    """Append a timestamped line to the Activity Log section."""
    if not MAP_FILE.exists():
        log(f"{MAP_FILE} not found — skipping")
        return

    content = MAP_FILE.read_text()
    ts      = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry   = f"- {ts} — {summary}"

    if ACTIVITY_START in content and ACTIVITY_END in content:
        content = content.replace(ACTIVITY_END, f"{entry}\n{ACTIVITY_END}")
    else:
        content += f"\n{entry}\n"

    MAP_FILE.write_text(content)
    log(f"Session entry added: {entry}")


def daily_mode():
    """
    Full scan:
    1. Scan all .py and .sh in hooks dir for Notion DB IDs
    2. Find any new IDs not in KNOWN_DBS — flag them
    3. Update Last full scan timestamp in the map file
    4. Append a daily scan summary to Activity Log
    5. Git commit the updated file
    """
    if not MAP_FILE.exists():
        log(f"{MAP_FILE} not found — cannot update")
        return

    content = MAP_FILE.read_text()

    # Scan hooks + root scripts for all DB IDs
    found_ids: dict[str, list[str]] = {}  # normalized_id -> [script names]
    scan_dirs = [HOOKS_DIR, KAMIL_DIR]
    for scan_dir in scan_dirs:
        pattern = "*.py" if scan_dir == HOOKS_DIR else "*.sh"
        for script in scan_dir.glob(pattern):
            try:
                text = script.read_text(errors="ignore")
            except Exception:
                continue
            for m in DB_ID_RE.finditer(text):
                raw   = m.group(0)
                norm  = raw.replace("-", "").lower()
                if norm not in found_ids:
                    found_ids[norm] = []
                found_ids[norm].append(script.name)

    # Find IDs not in our known map
    known_norm = set(KNOWN_DBS.keys())
    unknown    = {k: v for k, v in found_ids.items() if k not in known_norm}

    # Build summary
    ts    = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [f"Daily scan: {len(found_ids)} IDs across hooks"]
    if unknown:
        for uid, scripts in unknown.items():
            parts.append(f"⚠️ UNKNOWN `{uid}` in {', '.join(set(scripts))}")
    else:
        parts.append("all IDs accounted for ✅")

    summary = " | ".join(parts)

    # Update Last full scan line
    content = LAST_SCAN_RE.sub(f"Last full scan: {ts}", content)

    # Append activity entry
    entry = f"- {ts} — {summary}"
    if ACTIVITY_START in content and ACTIVITY_END in content:
        content = content.replace(ACTIVITY_END, f"{entry}\n{ACTIVITY_END}")
    else:
        content += f"\n{entry}\n"

    MAP_FILE.write_text(content)
    log(summary)

    # Git commit
    try:
        subprocess.run(["git", "add", str(MAP_FILE)], cwd=str(KAMIL_DIR), check=False)
        result = subprocess.run(
            ["git", "commit", "-m", f"chore: notion-map daily scan {ts}"],
            cwd=str(KAMIL_DIR), capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            log("Committed updated map")
        else:
            log(f"Git commit skipped: {result.stdout.strip()}")
    except Exception as e:
        log(f"Git commit error: {e}")


if __name__ == "__main__":
    _t0 = _time.time()
    try:
        p = argparse.ArgumentParser()
        p.add_argument("--mode", choices=["session", "daily"], required=True)
        p.add_argument("--summary", default="session ended",
                       help="Session mode: 1-line summary of what happened")
        args = p.parse_args()

        if args.mode == "session":
            session_mode(args.summary)
        else:
            daily_mode()
        if _k: _k.klog_cron("notion-map", status="ok", duration_ms=(_time.time()-_t0)*1000)
    except Exception as _e:
        if _k: _k.klog_error("notion-map-main", _e, component="notion-map", severity="ERROR")
        raise
