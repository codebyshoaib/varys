#!/usr/bin/env python3
"""
varys-extract-trajectory.py — Build the VARYS TRAJECTORY block injected into
evolution planning and session-start context.

Adapted from yoyo-evolve/scripts/extract_trajectory.py. Aggregates:
  - Recent bead/ticket outcomes (failures.jsonl, decisions.jsonl)
  - Nightly eval confidence from /tmp/varys-learn.log
  - Recent git commits (last 14 days)
  - Active beads snapshot

Output: memory/trajectory.md — ~1–2KB markdown blob, hard-capped at 100 lines / 2KB.
Always exits 0 — failure modes degrade per section and write a safe fallback.

Usage: python3 varys-extract-trajectory.py
  Called by varys-proactive-evolve.py before each evolution session,
  and injected into session-start.py alongside active_learnings.md.
"""

import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

VARYS_DIR     = Path(__file__).parent.parent.parent
MEMORY_DIR    = VARYS_DIR / "memory"
FAILURES_FILE = VARYS_DIR / ".beads" / "failures.jsonl"
DECISIONS_FILE= VARYS_DIR / ".beads" / "decisions.jsonl"
LEARN_LOG     = Path("/tmp/varys-learn.log")
OUT_PATH      = MEMORY_DIR / "trajectory.md"

WINDOW_DAYS      = 14
WINDOW_SESSIONS  = 10
TOTAL_LINE_CAP   = 100
TOTAL_BYTE_CAP   = 2048


def warn(msg: str) -> None:
    print(f"extract-trajectory: WARN: {msg}", file=sys.stderr)


def run_cmd(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           start_new_session=True)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        warn(f"timed out after {timeout}s: {' '.join(cmd[:3])}...")
        return 124, "", "timeout"
    except (FileNotFoundError, OSError) as e:
        warn(f"command failed: {' '.join(cmd[:3])}... — {e}")
        return 1, "", str(e)


def truncate_lines(s: str, n: int) -> str:
    lines = s.splitlines()
    if len(lines) <= n:
        return s
    return "\n".join(lines[:n] + [f"... ({len(lines) - n} more lines truncated)"])


# ── Section 1: Recent failures and lessons ───────────────────────────────

def load_failures() -> list[dict]:
    if not FAILURES_FILE.exists():
        return []
    entries = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS * 2)
    for line in FAILURES_FILE.read_text().splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
            ts_str = e.get("ts") or e.get("date") or ""
            if ts_str:
                # Accept date-only (YYYY-MM-DD) or ISO datetime
                try:
                    if "T" in ts_str:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    else:
                        ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                    if ts < cutoff:
                        continue
                except ValueError:
                    pass
            entries.append(e)
        except json.JSONDecodeError:
            continue
    return entries[-WINDOW_SESSIONS:]


def render_failures(entries: list[dict]) -> str:
    if not entries:
        return ""
    lines = [f"## Recent failures / lessons (last {WINDOW_DAYS * 2} days)"]
    for e in entries:
        date = (e.get("ts") or e.get("date") or "")[:10]
        incident = e.get("incident", "")[:80]
        lesson = e.get("lesson", "")[:80]
        lines.append(f"{date}: {incident}")
        if lesson:
            lines.append(f"  → lesson: {lesson}")
    return "\n".join(lines)


# ── Section 2: Nightly eval confidence from learn log ───────────────────

def load_eval_confidence() -> list[str]:
    """Extract last 7 confidence lines from /tmp/varys-learn.log."""
    if not LEARN_LOG.exists():
        return []
    lines = LEARN_LOG.read_text().splitlines()
    conf_lines = [l for l in lines if "confidence=" in l or "Confidence:" in l]
    return conf_lines[-7:]


def render_eval_confidence(conf_lines: list[str]) -> str:
    if not conf_lines:
        return ""
    lines = ["## Nightly eval confidence (last 7 runs)"]
    for l in conf_lines:
        # Trim log prefix
        l = re.sub(r"^\[varys-learn\]\s*", "", l).strip()
        lines.append(f"  {l}")
    return "\n".join(lines)


# ── Section 3: Recent git commits ────────────────────────────────────────

TASK_COMMIT_RE = re.compile(r"^(feat|fix|refactor|chore|docs|style|test|perf)\(([^)]+)\):\s+(.+)$")


def collect_recent_commits() -> list[str]:
    rc, stdout, _ = run_cmd(
        ["git", "log", f"--since={WINDOW_DAYS} days ago", "--format=%s", "--no-merges"],
        timeout=10,
    )
    if rc != 0:
        return []
    return [l.strip() for l in stdout.splitlines() if l.strip()][:20]


def render_commits(commits: list[str]) -> str:
    if not commits:
        return ""
    lines = [f"## Recent commits (last {WINDOW_DAYS} days, {len(commits)} total)"]
    for c in commits[:8]:
        lines.append(f"  - {c[:100]}")
    if len(commits) > 8:
        lines.append(f"  ... and {len(commits) - 8} more")
    return "\n".join(lines)


# ── Section 4: Active beads snapshot ────────────────────────────────────

def load_active_beads() -> list[dict]:
    # bd outputs JSONL (one JSON object per line), not a JSON array
    rc, stdout, _ = run_cmd(["bd", "ready"], timeout=8)
    if rc != 0 or not stdout.strip():
        return []
    beads = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            b = json.loads(line)
            beads.append(b)
        except json.JSONDecodeError:
            # bd ready may output plain text — just capture lines
            beads.append({"title": line[:80], "status": "open"})
    return beads[:10]


def render_beads(beads: list[dict]) -> str:
    if not beads:
        return ""
    lines = [f"## Active beads ({len(beads)} open/in-progress)"]
    for b in beads:
        status = b.get("status", "")
        title  = (b.get("title") or "")[:70]
        lines.append(f"  [{status}] {title}")
    return "\n".join(lines)


# ── Section 5: Recent decisions ──────────────────────────────────────────

def load_recent_decisions() -> list[dict]:
    if not DECISIONS_FILE.exists():
        return []
    entries = []
    for line in DECISIONS_FILE.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries[-5:]


def render_decisions(entries: list[dict]) -> str:
    if not entries:
        return ""
    lines = ["## Recent architecture decisions"]
    for e in entries:
        date = (e.get("date") or "")[:10]
        dec  = (e.get("decision") or "")[:90]
        lines.append(f"  {date}: {dec}")
    return "\n".join(lines)


# ── Final assembly ───────────────────────────────────────────────────────

def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Clear stale output (same pattern as yoyo)
    OUT_PATH.unlink(missing_ok=True)

    header = (
        f"# VARYS TRAJECTORY\n\n"
        f"Last computed: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')}. "
        f"Window: last {WINDOW_SESSIONS} sessions / {WINDOW_DAYS} days.\n"
    )

    failures  = load_failures()
    conf      = load_eval_confidence()
    commits   = collect_recent_commits()
    beads     = load_active_beads()
    decisions = load_recent_decisions()

    sections: list[str] = []
    for fn, data in [
        (render_failures,    failures),
        (render_eval_confidence, conf),
        (render_commits,     commits),
        (render_beads,       beads),
        (render_decisions,   decisions),
    ]:
        s = fn(data)
        if s:
            sections.append(s)

    if not sections:
        body = "(no trajectory data yet — beads, eval log, and git log are all empty)"
    else:
        body = "\n\n".join(sections)

    output = header + "\n" + body + "\n"

    # Hard-cap (same as yoyo)
    output = truncate_lines(output, TOTAL_LINE_CAP)
    marker = "\n... (truncated to fit token budget)\n"
    if len(output.encode()) > TOTAL_BYTE_CAP:
        b = output.encode()[:TOTAL_BYTE_CAP - len(marker.encode())]
        idx = b.rfind(b"\n")
        if idx > 0:
            b = b[:idx]
        output = b.decode("utf-8", errors="ignore") + marker

    try:
        OUT_PATH.write_text(output)
    except OSError as e:
        warn(f"could not write {OUT_PATH}: {e}")
        return 1

    print(f"[varys-trajectory] wrote {OUT_PATH} ({len(output.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
