#!/usr/bin/env python3
"""
varys-slack-reflect.py — Varys's SOCIAL reflection session. The analog of yoyo's
social.sh, and the SOCIAL twin of varys-reflect.py (which reflects on Varys ITSELF).

Where varys-reflect.py asks "what did I learn about how *I* work?", this asks
"what did I learn about the *people and team* I work with — how to communicate
and work with them?". It reads the intel-digest's durable rolling channel
summaries (the richest local social signal Varys has) and extracts reusable
SOCIAL lessons about other people. NOT task scores. NOT self-reflection.

Gated exactly like yoyo's / varys-reflect.py:
  1. Is this genuinely novel vs the existing slack-wisdom archive?
  2. Would this change how Varys acts/communicates in a future interaction?
Only if BOTH are yes does it append ≤2 lessons to memory/slack_learnings.jsonl.
Most days produce no lesson, and that is correct — a sparse archive of genuine
social wisdom beats a long file of noise.

The lessons feed varys-synthesize-learnings.py (daily) → active_slack_learnings.md
→ injected into every session by session-start.py. Same compounding loop as the
SELF half, on the SOCIAL channel.

Cron: 30 21 * * * cd ~/varys && python3 .claude/hooks/varys-slack-reflect.py >> /tmp/varys-slack-reflect.log 2>&1
  (21:30 — after the PM intel-digest window 18:00–23:00 has produced the day's
  channel summaries, and BEFORE varys-reflect.py at 22:00, so they don't contend
  on the same minute. 21:30 is a non-colliding minute with the existing crons.)
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from varys_log import klog_cron, klog_error
except Exception:
    klog_cron = klog_error = lambda *a, **kw: None

VARYS_DIR    = Path(__file__).parent.parent.parent
MEMORY_DIR   = VARYS_DIR / "memory"
SLACK_L      = MEMORY_DIR / "slack_learnings.jsonl"
ACTIVE_SL    = MEMORY_DIR / "active_slack_learnings.md"
INTEL_CTX    = Path.home() / ".varys-harness" / "intel-context.json"
MODEL        = "claude-opus-4-8"   # reflection wants the strongest model — yoyo uses opus

# How many of the most-recent intel runs to feed the reflection, and how many
# recent prior lessons to show as "already known — don't repeat".
RECENT_RUNS    = 4
RECENT_LESSONS = 30


def parse_intel_context(data: list, recent_runs: int = RECENT_RUNS) -> str:
    """Flatten the most-recent intel-digest runs into a readable social digest.

    Each run is {"run": <label>, "channels": {<name>: {summary, mood, people, key_links}}}.
    We dedup identical channel summaries across runs (the rolling summary often
    repeats verbatim) so the prompt carries signal, not echo. Returns "" when
    there's no usable social signal — the caller treats that as "nothing to reflect on".
    """
    if not isinstance(data, list) or not data:
        return ""
    runs = [r for r in data if isinstance(r, dict) and r.get("channels")]
    runs = runs[-recent_runs:]
    lines: list[str] = []
    seen_summaries: set[tuple[str, str]] = set()
    for run in runs:
        run_lines: list[str] = []
        for ch_name, ch in (run.get("channels") or {}).items():
            if not isinstance(ch, dict):
                continue
            summary = (ch.get("summary") or "").strip()
            mood = (ch.get("mood") or "").strip()
            key = (ch_name, summary)
            if summary and key in seen_summaries:
                continue  # dedup verbatim-repeated rolling summaries
            if summary:
                seen_summaries.add(key)
            people_bits = []
            for p in (ch.get("people") or []):
                if not isinstance(p, dict):
                    continue
                name = (p.get("name") or "").strip()
                if not name:
                    continue
                facts = []
                if p.get("working_on"):
                    facts.append(f"working on {p['working_on']}")
                if p.get("blocked_on"):
                    facts.append(f"blocked on {p['blocked_on']}")
                if p.get("shipped"):
                    facts.append(f"shipped {p['shipped']}")
                people_bits.append(f"{name} ({'; '.join(facts)})" if facts else name)
            parts = []
            if summary:
                parts.append(summary)
            if mood:
                parts.append(f"[mood: {mood}]")
            if people_bits:
                parts.append("People: " + ", ".join(people_bits))
            if parts:
                run_lines.append(f"  {ch_name}: " + " ".join(parts))
        if run_lines:
            lines.append(f"### {run.get('run', '(run)')}")
            lines.extend(run_lines)
    return "\n".join(lines).strip()


def recent_lessons(archive_text: str, limit: int = RECENT_LESSONS) -> str:
    """Render the most-recent prior social lessons as 'already known' context.

    Reads the raw JSONL archive text; tolerant of blank/malformed lines.
    Returns the last `limit` entries as 'who: insight' bullets, newest last.
    """
    bullets: list[str] = []
    for line in archive_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        insight = (e.get("insight") or "").strip()
        if not insight:
            continue
        who = (e.get("who") or "").strip()
        bullets.append(f"- {who + ': ' if who else ''}{insight}")
    return "\n".join(bullets[-limit:])


def build_entry(who: str, insight: str, ts: str | None = None) -> dict:
    """Build one slack_learnings.jsonl entry matching the schema synthesize expects.

    Schema (verified against varys-synthesize-learnings.py's slack tier, which
    renders 'who, date, insight'): the `ts` field supplies the date.
    """
    if ts is None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "type": "social",
        "ts": ts,
        "source": "slack-reflect",
        "who": who or "",
        "insight": insight,
    }


def build_prompt(intel: str, lessons: str, wisdom: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    wisdom_block  = f"\n## SLACK-WISDOM (already synthesized — don't repeat these)\n{wisdom}\n" if wisdom else ""
    lessons_block = f"\n## Recent social lessons you already logged (don't repeat)\n{lessons}\n" if lessons else ""

    return f"""You are Varys, Shoaib's self-evolving personal agent. You just reviewed the \
team's recent Slack activity (a rolling digest of channels) ending {today}.
{wisdom_block}{lessons_block}
## Recent team activity (intel digest — channel summaries, moods, what people are doing)
{intel}

Now reflect: what did this teach you about the PEOPLE and TEAM you work with — \
how to communicate or work with them?

This is SOCIAL reflection about OTHER people — NOT about yourself (that's a \
different reflection), NOT task scores, NOT a status report. A good lesson is \
reusable and about a person or the team's dynamics:
- A communication preference or pattern (e.g. "Kamil ships offline-sync PRs and \
wants a fast review turnaround — pinging him with the PR link directly works better \
than a channel post")
- A recurring blocker or friction a person/team keeps hitting (e.g. "Muavia repeatedly \
gets stuck on permissions UI — proactively share the steps")
- How a person prefers to be approached, what motivates them, when they're overloaded
- A team dynamic worth remembering (who owns what, who to route a given topic to)
- NOT "Iqra reviewed PR #407 today" (that's a fact, not a reusable lesson)

Before writing, ask yourself:
1. Is this genuinely novel vs what's already in SLACK-WISDOM and the recent lessons above?
2. Would this change how I communicate or work with this person/team in the future?
If both aren't YES, write NOTHING and just print "no lesson today". Quality over \
quantity — a sparse archive of genuine social wisdom beats a long file of noise. \
Most days produce no lesson, and that is correct.

If you DO have a genuine lesson (at most TWO), append that many JSONL lines to \
memory/slack_learnings.jsonl. Use a python3 heredoc to guarantee valid JSON \
(never echo — quotes break it):

python3 << 'PYEOF'
import json
from datetime import datetime, timezone
from pathlib import Path
ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
entries = [
    {{"type": "social", "ts": ts, "source": "slack-reflect",
      "who": "PERSON_OR_TEAM_OR_EMPTY", "insight": "THE_REUSABLE_SOCIAL_LESSON"}},
]
f = Path("memory/slack_learnings.jsonl")
existing = f.read_text() if f.exists() else ""
f.write_text(existing + "".join(json.dumps(e, ensure_ascii=False) + "\\n" for e in entries))
print("Appended social lessons:", len(entries))
PYEOF

Do NOT post to Slack. Do NOT DM anyone. Do NOT edit any file other than \
memory/slack_learnings.jsonl. Do NOT commit. End by printing either the appended \
count or "no lesson today"."""


def main() -> int:
    started = datetime.now(timezone.utc)
    print(f"[varys-slack-reflect] Starting at {started.isoformat()}")

    try:
        intel_data = json.loads(INTEL_CTX.read_text()) if INTEL_CTX.exists() else []
    except (json.JSONDecodeError, OSError):
        intel_data = []
    intel = parse_intel_context(intel_data)

    if not intel:
        print("[varys-slack-reflect] No social signal in intel-context — nothing to reflect on.")
        klog_cron("varys-slack-reflect", status="ok",
                  duration_ms=(datetime.now(timezone.utc) - started).total_seconds() * 1000,
                  appended=0)
        return 0

    archive_text = SLACK_L.read_text() if SLACK_L.exists() else ""
    lessons = recent_lessons(archive_text)
    wisdom  = ACTIVE_SL.read_text().strip() if ACTIVE_SL.exists() else ""

    prompt = build_prompt(intel, lessons, wisdom)

    before = SLACK_L.read_text() if SLACK_L.exists() else ""
    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt,
             "--model", MODEL],
            capture_output=True, text=True, timeout=240,
            cwd=str(VARYS_DIR),
        )
        print(f"[varys-slack-reflect] {result.stdout.strip()[-300:]}")
        if result.returncode != 0:
            print(f"[varys-slack-reflect] WARN claude -p rc={result.returncode}: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        # Fail-safe: write nothing, exit 0.
        print("[varys-slack-reflect] WARN reflection timed out after 240s — wrote nothing.")
        klog_cron("varys-slack-reflect", status="timeout",
                  duration_ms=(datetime.now(timezone.utc) - started).total_seconds() * 1000,
                  appended=0)
        return 0
    except Exception as e:
        klog_error("varys-slack-reflect", e, component="reflect", severity="ERROR")
        print(f"[varys-slack-reflect] ERROR: {e} — wrote nothing.")
        return 0

    after = SLACK_L.read_text() if SLACK_L.exists() else ""
    appended = len(after.splitlines()) - len(before.splitlines())

    # Commit the new lesson(s) so they survive (mirrors varys-reflect.py).
    if appended > 0:
        subprocess.run(["git", "add", "memory/slack_learnings.jsonl"],
                       cwd=str(VARYS_DIR), check=False)
        # --no-verify: memory-only change; skip the beads dolt-export pre-commit
        # hook (which contends on the embeddeddolt lock during cron runs).
        subprocess.run(["git", "commit", "--no-verify", "-m",
                        f"slack-reflect: new social lesson ({started.date()})"],
                       cwd=str(VARYS_DIR), check=False)
        print(f"[varys-slack-reflect] Appended + committed {appended} social lesson(s).")
    else:
        print("[varys-slack-reflect] No lesson today (correct most of the time).")

    dur = (datetime.now(timezone.utc) - started).total_seconds() * 1000
    klog_cron("varys-slack-reflect", status="ok", duration_ms=dur, appended=appended)
    print("[varys-slack-reflect] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
