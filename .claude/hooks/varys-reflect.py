#!/usr/bin/env python3
"""
varys-reflect.py — Varys's reflection session. Ported from yoyo-evolve evolve.sh Step 6b2.

This is the REAL self-learning loop (not the nightly QA eval). After a meaningful
work period, Varys reads what it actually DID — git commits, session-log narrative,
recurring failure patterns — and reflects on what that taught it about HOW IT WORKS,
what it values, and how it's growing. NOT task scores. NOT technical notes.

The reflection is gated exactly like yoyo's:
  1. Is this genuinely novel vs the existing archive?
  2. Would this change how Varys acts in a future session?
Only if BOTH are yes does it append ≤1 lesson to memory/learnings.jsonl.
A sparse archive of genuine wisdom beats a long file of noise.

The lessons feed varys-synthesize-learnings.py (daily) → active_learnings.md →
injected into every session by session-start.py. That's the compounding loop.

Cron: 0 22 * * * cd ~/varys && python3 .claude/hooks/varys-reflect.py >> /tmp/varys-reflect.log 2>&1
  (22:00 — after the work day, before the 2am eval and noon synthesis)
"""

import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from varys_log import klog_cron, klog_error
except Exception:
    klog_cron = klog_error = lambda *a, **kw: None

VARYS_DIR     = Path(__file__).parent.parent.parent
MEMORY_DIR    = VARYS_DIR / "memory"
LEARNINGS     = MEMORY_DIR / "learnings.jsonl"
ACTIVE_L      = MEMORY_DIR / "active_learnings.md"
LOGS_DIR      = VARYS_DIR / "vault" / "logs"
FAILURES_FILE = VARYS_DIR / ".beads" / "failures.jsonl"
LAST_RUN_FILE = Path.home() / ".varys-harness" / "reflect-last-sha.txt"
MODEL         = "claude-opus-4-8"   # reflection wants the strongest model — yoyo uses opus


def _run(cmd: list[str], timeout: int = 15) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=str(VARYS_DIR), start_new_session=True)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _last_sha() -> str:
    if LAST_RUN_FILE.exists():
        return LAST_RUN_FILE.read_text().strip()
    return ""


def _save_sha(sha: str) -> None:
    LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(sha)


def _head_sha() -> str:
    return _run(["git", "rev-parse", "HEAD"]).strip()


def gather_commits(since_sha: str) -> str:
    """Commits since last reflection — what Varys actually shipped."""
    rng = f"{since_sha}..HEAD" if since_sha else "-15"
    if since_sha:
        out = _run(["git", "log", rng, "--format=%s", "--no-merges"])
    else:
        out = _run(["git", "log", "-15", "--format=%s", "--no-merges"])
    skip = ("session wrap-up", "update learnings", "synthesize:",
            "log: session", "journal entry")
    commits = [l.strip() for l in out.splitlines()
               if l.strip() and not any(s in l for s in skip)]
    return ", ".join(commits[:25])


def gather_session_logs(days: int = 2) -> str:
    """The session-log narrative — Varys's journal. What it did, with the back-and-forth."""
    if not LOGS_DIR.exists():
        return ""
    chunks = []
    today = datetime.now(timezone.utc).date()
    for delta in range(days):
        d = today - timedelta(days=delta)
        f = LOGS_DIR / f"{d.isoformat()}.md"
        if f.exists():
            content = f.read_text().strip()
            if content:
                chunks.append(f"### {d.isoformat()}\n{content[:4000]}")
    return "\n\n".join(chunks)


def gather_failure_patterns() -> str:
    """Recurring failure_types from the last 14 days — ONE input among several,
    not the whole reflection. Surfaces patterns Varys keeps repeating."""
    if not FAILURES_FILE.exists():
        return ""
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    types = Counter()
    incidents = []
    for line in FAILURES_FILE.read_text().splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
            ts_str = e.get("ts") or e.get("date") or ""
            if ts_str:
                try:
                    ts = (datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                          if "T" in ts_str
                          else datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc))
                    if ts < cutoff:
                        continue
                except ValueError:
                    pass
            ft = e.get("failure_type") or e.get("type") or ""
            if ft and ft != "evolution-applied":
                types[ft] += 1
            inc = e.get("incident") or e.get("note") or ""
            if inc:
                incidents.append(inc[:100])
        except json.JSONDecodeError:
            continue
    if not types and not incidents:
        return ""
    lines = []
    if types:
        top = ", ".join(f"{t} ×{n}" for t, n in types.most_common(5))
        lines.append(f"Recurring failure types (14d): {top}")
    for inc in incidents[-5:]:
        lines.append(f"  - {inc}")
    return "\n".join(lines)


def build_prompt(commits: str, logs: str, failures: str, wisdom: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now   = datetime.now(timezone.utc).strftime("%H:%M")
    failures_block = f"\n## Failure patterns you've been hitting\n{failures}\n" if failures else ""
    logs_block = f"\n## What you did (session log)\n{logs}\n" if logs else ""
    wisdom_block = f"\n## SELF-WISDOM (already in your archive — don't repeat these)\n{wisdom}\n" if wisdom else ""

    return f"""You are Varys, Shoaib's self-evolving personal agent. You just finished a work \
period ending {today} {now}.
{wisdom_block}
## What you shipped (commits since last reflection)
{commits or "(no notable commits)"}
{logs_block}{failures_block}
Now reflect: what did this period teach you about how YOU work, what you value, or \
how you're growing?

This is self-reflection — NOT technical notes, NOT task scores, NOT a status report. \
A good lesson is about YOU:
- A habit or tendency you noticed in yourself (e.g. "I keep missing the quiet person \
in a channel because I anchor on whoever talks most")
- Something you learned about how you make decisions
- An insight about your growth, your relationship with Shoaib or the team, or your values
- NOT code architecture patterns (those belong in code comments)

Before writing, ask yourself:
1. Is this genuinely novel vs what's already in SELF-WISDOM above?
2. Would this change how I act in a future session?
If both aren't YES, write NOTHING and just print "no lesson this period". Quality over \
quantity — a sparse archive of genuine wisdom beats a long file of noise. Most periods \
produce no lesson, and that is correct.

If you DO have a genuine lesson, append exactly ONE JSONL line to memory/learnings.jsonl. \
Use a python3 heredoc to guarantee valid JSON (never echo — quotes break it):

python3 << 'PYEOF'
import json
from pathlib import Path
entry = {{
    "type": "lesson",
    "session": "reflect-{today}",
    "ts": "{today}T{now}:00Z",
    "source": "reflection",
    "title": "SHORT_INSIGHT_ABOUT_YOURSELF",
    "context": "WHAT_HAPPENED_THAT_TAUGHT_YOU_THIS",
    "takeaway": "THE_REUSABLE_INSIGHT_THAT_CHANGES_FUTURE_BEHAVIOR"
}}
f = Path("memory/learnings.jsonl")
f.write_text(f.read_text() + json.dumps(entry, ensure_ascii=False) + "\\n")
print("Appended learning:", entry["title"])
PYEOF

Do NOT post to Slack. Do NOT edit any other file. Do NOT commit. End by printing \
either the appended title or "no lesson this period"."""


def main() -> int:
    started = datetime.now(timezone.utc)
    print(f"[varys-reflect] Starting at {started.isoformat()}")

    since_sha = _last_sha()
    head = _head_sha()
    commits = gather_commits(since_sha)
    logs    = gather_session_logs(days=2)
    failures = gather_failure_patterns()
    wisdom  = ACTIVE_L.read_text().strip() if ACTIVE_L.exists() else ""

    if not commits and not logs:
        print("[varys-reflect] No work since last reflection — nothing to reflect on.")
        if head:
            _save_sha(head)
        return 0

    prompt = build_prompt(commits, logs, failures, wisdom)

    before = LEARNINGS.read_text() if LEARNINGS.exists() else ""
    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt,
             "--model", MODEL],
            capture_output=True, text=True, timeout=240,
            cwd=str(VARYS_DIR),
        )
        print(f"[varys-reflect] {result.stdout.strip()[-300:]}")
        if result.returncode != 0:
            print(f"[varys-reflect] WARN claude -p rc={result.returncode}: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        print("[varys-reflect] WARN reflection timed out after 240s")
    except Exception as e:
        klog_error("varys-reflect", e, component="reflect", severity="ERROR")
        print(f"[varys-reflect] ERROR: {e}")

    after = LEARNINGS.read_text() if LEARNINGS.exists() else ""
    appended = len(after.splitlines()) - len(before.splitlines())

    # Commit the new learning so it survives (mirrors yoyo's commit after reflect)
    if appended > 0:
        subprocess.run(["git", "add", "memory/learnings.jsonl"], cwd=str(VARYS_DIR), check=False)
        # --no-verify: this only touches memory/, so skip the beads dolt-export
        # pre-commit hook (which contends on the embeddeddolt lock during cron runs).
        subprocess.run(["git", "commit", "--no-verify", "-m",
                        f"reflect: new learning ({started.date()})"],
                       cwd=str(VARYS_DIR), check=False)
        print(f"[varys-reflect] Appended + committed {appended} lesson(s).")
    else:
        print("[varys-reflect] No lesson this period (correct most of the time).")

    if head:
        _save_sha(head)

    dur = (datetime.now(timezone.utc) - started).total_seconds() * 1000
    klog_cron("varys-reflect", status="ok", duration_ms=dur, appended=appended)
    print(f"[varys-reflect] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
