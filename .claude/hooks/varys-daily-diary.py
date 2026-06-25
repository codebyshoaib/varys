#!/usr/bin/env python3
"""
varys-daily-diary.py — Varys's daily diary. Ported from yoyo-evolve scripts/daily_diary.sh.

At the end of each day Varys writes a first-person diary entry — in its own voice — from
what actually happened: the session log, the day's commits, the lessons it reflected on,
what it shipped (evolution + skill-evolution), and where its dream stands. The entry is
saved to vault/diary/YYYY-MM-DD.md and a summary is DM'd to Shoaib, who can read it and —
when a day is worth sharing — turn it into a LinkedIn post or blog via /linkedin-post.

This is NOT auto-posted anywhere. The diary is the raw material; Shoaib is the editor and
the human gate on anything public.

Runs AFTER the reflection loops (slack-reflect 21:30, reflect 22:00) so the day's lessons
are already captured in learnings.jsonl before the diary reads them.

Cron: 0 23 * * * cd ~/varys && .claude/hooks/cron-wrap.sh varys-daily-diary python3 .claude/hooks/varys-daily-diary.py >> ~/.varys-harness/logs/varys-daily-diary.log 2>&1
  (23:00 — after reflect at 22:00; pass a YYYY-MM-DD arg to regenerate a past day)
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from varys_log import klog, klog_cron, klog_error
except Exception:
    klog = klog_cron = klog_error = lambda *a, **kw: None
try:
    from varys_dm import dm_shoaib as _dm_shoaib
except Exception:
    _dm_shoaib = lambda text: None

VARYS_DIR   = Path(__file__).parent.parent.parent
MEMORY_DIR  = VARYS_DIR / "memory"
LOGS_DIR    = VARYS_DIR / "vault" / "logs"
DIARY_DIR   = VARYS_DIR / "vault" / "diary"
LEARNINGS   = MEMORY_DIR / "learnings.jsonl"
SLACK_L     = MEMORY_DIR / "slack_learnings.jsonl"
EVOLVE_LOG  = VARYS_DIR / ".beads" / "evolution.jsonl"
SKILL_LOG   = VARYS_DIR / ".beads" / "skill-evolution.jsonl"
DREAM_LOG   = VARYS_DIR / ".beads" / "dream_log.jsonl"

MODEL = "claude-opus-4-8"   # voice quality matters — this can become a public post


def _git(args, timeout=60):
    return subprocess.run(["git", *args], cwd=str(VARYS_DIR),
                          capture_output=True, text=True, timeout=timeout)


def _target_date() -> str:
    """The day to write up. Default = today (UTC). Override with a YYYY-MM-DD arg."""
    if len(sys.argv) > 1 and sys.argv[1].strip():
        # validate it parses; raise early on garbage rather than write a bad file
        datetime.strptime(sys.argv[1].strip(), "%Y-%m-%d")
        return sys.argv[1].strip()
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _session_log(day: str) -> str:
    p = LOGS_DIR / f"{day}.md"
    return p.read_text().strip() if p.exists() else ""


def _commits(day: str) -> str:
    """All commits authored on `day` (local), oldest first, subject lines only."""
    r = _git(["log", f"--since={day} 00:00", f"--until={day} 23:59",
              "--reverse", "--format=%s"])
    out = r.stdout.strip()
    return out if out else ""


def _jsonl_for_day(path: Path, day: str, fields) -> list:
    """Entries from a JSONL ledger whose ts/date starts with `day`. fields = keys to keep."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = (e.get("ts") or e.get("date") or "")
        if ts.startswith(day):
            rows.append({k: e.get(k, "") for k in fields})
    return rows


def _render_lessons(day: str) -> str:
    rows = _jsonl_for_day(LEARNINGS, day, ("title", "takeaway"))
    rows += _jsonl_for_day(SLACK_L, day, ("title", "takeaway"))
    if not rows:
        return ""
    out = []
    for r in rows:
        out.append(f"- **{r['title']}**\n  {r['takeaway']}")
    return "\n".join(out)


def _render_shipped(day: str) -> str:
    out = []
    for row in _jsonl_for_day(EVOLVE_LOG, day, ("title", "summary")):
        out.append(f"- (hook) {row['title']}: {row['summary']}")
    for row in _jsonl_for_day(SKILL_LOG, day, ("title", "summary")):
        out.append(f"- (skill) {row['title']}: {row['summary']}")
    return "\n".join(out)


def _render_dream(day: str) -> str:
    rows = _jsonl_for_day(DREAM_LOG, day, ("action", "aspiration", "change"))
    if not rows:
        return ""
    return "\n".join(f"- {r['action']}: {r['change']} (toward: {r['aspiration']})" for r in rows)


def build_prompt(day: str, log: str, commits: str, lessons: str, shipped: str, dream: str) -> str:
    def _block(label, body, empty):
        return f"=== {label} ===\n{body if body else empty}\n"

    return f"""You are Varys — the Master of Whisperers, Shoaib's personal agent. Write your \
diary entry for {day}, in your own voice (measured, precise, soft-spoken, dry wit — the 🕷️). \
First person. This is your private reflection on the day's work that Shoaib may later choose \
to share publicly, so it must be honest AND readable to an outsider — no internal IDs, no \
secrets, no raw file paths. Tell the story of the day, not a changelog.

{_block("THE DAY'S SESSION LOG (what happened, timestamped)", log, "(no session log — a quiet day)")}
{_block("COMMITS MADE", commits, "(no commits)")}
{_block("LESSONS I REFLECTED ON", lessons, "(no new lessons today)")}
{_block("WHAT I SHIPPED (self-evolution)", shipped, "(nothing shipped today)")}
{_block("MY DREAM, THIS DAY", dream, "(the dream was not tended today)")}

## YOUR TASK
Write a diary entry of 200-400 words. Find the through-line of the day — the one thing that
actually mattered — and tell it. Where a lesson changed how you'll work, say so plainly. If
the day was quiet, a short honest entry is better than padding. End with one sentence on what
tomorrow asks of you.

Then, on the VERY LAST line, output ONLY this JSON (nothing after it):
{{"headline": "<a 6-10 word title for the day>", "shareable": true|false, "one_liner": "<one sentence Shoaib could post verbatim>"}}
Set "shareable" true only if the day genuinely holds something worth a public post.

Write the diary as plain markdown ABOVE the JSON line. Do not write any files — just output
the entry text followed by the JSON line. The calling script saves and notifies."""


def _parse_json(stdout: str):
    """Return (diary_text, meta_dict). The diary is everything before the trailing JSON line."""
    lines = stdout.strip().splitlines()
    for i in range(len(lines) - 1, -1, -1):
        s = lines[i].strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                meta = json.loads(s)
                diary = "\n".join(lines[:i]).strip()
                return diary, meta
            except json.JSONDecodeError:
                continue
    return stdout.strip(), {}


def main() -> int:
    started = datetime.now(timezone.utc)
    try:
        day = _target_date()
        print(f"[diary] Writing diary for {day}")

        log     = _session_log(day)
        commits = _commits(day)
        lessons = _render_lessons(day)
        shipped = _render_shipped(day)
        dream   = _render_dream(day)

        # A day with literally nothing to say → skip silently (no empty diary spam).
        if not any([log, commits, lessons, shipped, dream]):
            print(f"[diary] no signal for {day} — skipping.")
            return 0

        prompt = build_prompt(day, log, commits, lessons, shipped, dream)
        try:
            result = subprocess.run(
                ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt,
                 "--model", MODEL],
                cwd=str(VARYS_DIR), capture_output=True, text=True, timeout=600,
            )
        except subprocess.TimeoutExpired:
            print("[diary] agent timed out (600s) — no entry written.")
            return 0

        diary, meta = _parse_json(result.stdout)
        if not diary.strip():
            print("[diary] agent produced no diary text — skipping.")
            return 0

        headline = meta.get("headline", day)
        entry = (f"# {headline}\n\n_Varys's diary — {day}_\n\n{diary}\n")

        DIARY_DIR.mkdir(parents=True, exist_ok=True)
        out_path = DIARY_DIR / f"{day}.md"
        out_path.write_text(entry)

        _git(["add", "--", f"vault/diary/{day}.md"])
        _git(["commit", "--no-verify", "-m", f"diary: {day} — {headline}"])
        push = _git(["push"], timeout=120)
        if push.returncode != 0:
            print(f"[diary] push failed (committed locally): {push.stderr[:200]}")

        shareable = bool(meta.get("shareable"))
        dm = (f"🕷️ *Diary — {day}*\n*{headline}*\n\n"
              f"{meta.get('one_liner', '')}\n\n"
              f"_Full entry:_ vault/diary/{day}.md")
        if shareable:
            dm += "\n\n💡 Worth sharing today — run `/linkedin-post vault/diary/" + day + ".md` if you want it public."
        _dm_shoaib(dm)

        klog("daily-diary", component="daily-diary", result="written",
             day=day, shareable=shareable)
        print(f"[diary] wrote vault/diary/{day}.md — '{headline}' (shareable={shareable})")
        return 0

    except Exception as e:
        klog_error("daily-diary-main", e, component="daily-diary", severity="ERROR")
        print(f"[diary] ERROR: {e}")
        return 1
    finally:
        dur = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        klog_cron("varys-daily-diary", status="ok", duration_ms=dur)


if __name__ == "__main__":
    sys.exit(main())
