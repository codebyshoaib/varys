#!/usr/bin/env python3
"""
varys-session-review.py — post-session background review (stolen from Hermes Agent).

The idea Hermes gets right that Varys's daily reflect cron didn't: learn from the
CONVERSATION THAT JUST HAPPENED, while it's fresh — not from git commits on a 22:00
timer. This is a Stop hook. When a work turn ends, it replays the live transcript,
asks "what did this teach me about how I work?", and — only if the lesson is genuinely
novel and behaviour-changing — appends ONE line to memory/learnings.jsonl.

That's the SAME sink varys-reflect.py feeds, so the rest of the compounding loop is
already built: learnings.jsonl → varys-synthesize-learnings.py (daily) →
active_learnings.md → injected into every session by session-start.py → read + acted
on by varys-proactive-evolve.py. This hook just gives that loop a fresher, per-session
input instead of a cold daily one.

Three things this MUST get right (nervous-system code):
  1. Stop fires on EVERY turn, not just session end → hard debounce (cooldown +
     minimum new transcript growth) so we don't reflect after every reply.
  2. Reflection takes minutes; the Stop-hook timeout is 30s → the model call runs
     DETACHED (fire-and-forget). The hook returns in milliseconds.
  3. The detached worker itself spawns `claude -p` → recursion guard via env var.

Wired as a third Stop hook in .claude/settings.json (after stop-notion.py, stop.py).

# ponytail: reuses learnings.jsonl + the whole synthesize→active→evolve chain; the
# only new code is the trigger + transcript digest. No new downstream plumbing.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from varys_log import klog_cron, klog_error
except Exception:
    klog_cron = klog_error = lambda *a, **kw: None

VARYS_DIR   = Path(__file__).parent.parent.parent
LEARNINGS   = VARYS_DIR / "memory" / "learnings.jsonl"
ACTIVE_L    = VARYS_DIR / "memory" / "active_learnings.md"
STATE_FILE  = Path.home() / ".varys-harness" / "session-review-state.json"
REVIEW_LOG  = Path("/tmp/varys-session-review.log")

MODEL           = "claude-sonnet-5"   # cheap "warm review" model — quality gate is downstream (PR/synthesis)
COOLDOWN_MIN    = 45                  # never review the same session more than this often
MIN_NEW_LINES   = 30                  # transcript must have grown this much since last review
MIN_TURNS       = 6                   # ...and yield at least this many conversational turns
MAX_DIGEST_CH   = 12000               # cap what we feed the model (recent turns matter most)
GUARD_ENV       = "VARYS_SESSION_REVIEW"
ENGRAM_BIN      = Path.home() / ".local" / "bin" / "engram"  # Memory v2 archive dual-write (spike varys-c85.1)
ENGRAM_PROJECT  = "varys"


# ── Transcript digest ─────────────────────────────────────────────────────
def _turn_text(entry: dict) -> str | None:
    """Pull plain conversational text from one transcript JSONL entry.
    Keeps user/assistant prose; drops tool_use/tool_result noise."""
    if entry.get("type") not in ("user", "assistant"):
        return None
    msg = entry.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        text = " ".join(p for p in parts if p)
    else:
        return None
    text = text.strip()
    if not text:
        return None
    role = msg.get("role") or entry.get("type")
    return f"[{role}] {text}"


def build_digest(transcript_path: Path) -> tuple[str, int]:
    """Return (digest, n_turns). Digest is the tail of the conversation, capped."""
    turns = []
    for line in transcript_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            t = _turn_text(json.loads(line))
        except (json.JSONDecodeError, AttributeError):
            continue
        if t:
            turns.append(t)
    digest = "\n\n".join(turns)
    if len(digest) > MAX_DIGEST_CH:
        digest = "…(earlier turns elided)…\n\n" + digest[-MAX_DIGEST_CH:]
    return digest, len(turns)


# ── Debounce ──────────────────────────────────────────────────────────────
def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"sessions": {}, "last_ts": ""}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # prune to the 50 most-recently-touched sessions so the file can't grow unbounded
    sess = state.get("sessions", {})
    if len(sess) > 50:
        state["sessions"] = dict(list(sess.items())[-50:])
    STATE_FILE.write_text(json.dumps(state))


def should_review(state: dict, session_id: str, line_count: int, now: datetime) -> bool:
    """True iff enough NEW transcript since this session's last review AND the global
    cooldown has elapsed. Pure function — unit-tested in --self-check."""
    last_line = state.get("sessions", {}).get(session_id, 0)
    if line_count - last_line < MIN_NEW_LINES:
        return False
    last_ts = state.get("last_ts") or ""
    if last_ts:
        try:
            elapsed_min = (now - datetime.fromisoformat(last_ts)).total_seconds() / 60
            if elapsed_min < COOLDOWN_MIN:
                return False
        except ValueError:
            pass
    return True


# ── Engram archive dual-write (Memory v2 spike, varys-c85.1) ────────────────
# Mirror each session's summary + any lesson into the engram archive so we can
# measure recall over a week. Deterministic — python does the writes, not the -p
# agent — so the spike's recall test isn't skewed by the agent forgetting to save.
def _engram_save(title: str, msg: str, typ: str) -> None:
    """Save one observation into engram (non-fatal; skips if binary/msg missing)."""
    if not msg or not ENGRAM_BIN.exists():
        return
    try:
        subprocess.run([str(ENGRAM_BIN), "save", title[:120], msg[:2000],
                        "--type", typ, "--project", ENGRAM_PROJECT],
                       capture_output=True, text=True, timeout=30, cwd=str(VARYS_DIR))
    except Exception:
        pass


def _parse_summary(stdout: str):
    """Extract the `SUMMARY_JSON: {...}` trailer the reflection prompt emits (or None)."""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("SUMMARY_JSON:"):
            try:
                return json.loads(line[len("SUMMARY_JSON:"):].strip())
            except json.JSONDecodeError:
                return None
    return None


def _last_learning():
    """The most-recently appended learnings.jsonl entry (or None)."""
    if not LEARNINGS.exists():
        return None
    lines = [l for l in LEARNINGS.read_text().splitlines() if l.strip()]
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return None


# ── Reflection prompt (transcript-focused; same append discipline as varys-reflect) ──
def build_prompt(digest: str, session_id: str, wisdom: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now   = datetime.now(timezone.utc).strftime("%H:%M")
    wisdom_block = (f"\n## SELF-WISDOM (already in your archive — do NOT repeat these)\n{wisdom}\n"
                    if wisdom else "")
    return f"""You are Varys, Shoaib's self-evolving personal agent. A work session just ended \
({today} {now}). Below is the transcript of what you and Shoaib actually said and did.
{wisdom_block}
## The session transcript
{digest}

Reflect: what did THIS session teach you about how YOU work, decide, or grow? This is \
self-reflection — NOT technical notes, NOT a status report. A good lesson is about YOU:
- A habit or tendency you noticed (e.g. "I keep offering options when Shoaib wants one decision")
- Something about how you make decisions, or a correction Shoaib made and why
- An insight about your growth or your working relationship
- NOT code architecture patterns (those belong in code comments)

Before writing, ask:
1. Is this genuinely novel vs SELF-WISDOM above?
2. Would it change how I act in a future session?
If both aren't YES, write NOTHING and print "no lesson this session". Most sessions \
produce no lesson, and that is correct — a sparse archive of real wisdom beats noise.

If you DO have a genuine lesson, append exactly ONE JSONL line to memory/learnings.jsonl \
via a python3 heredoc (never echo — quotes break JSON):

python3 << 'PYEOF'
import json
from pathlib import Path
entry = {{
    "type": "lesson",
    "session": "session-{session_id[:8]}",
    "ts": "{today}T{now}:00Z",
    "source": "session-review",
    "title": "SHORT_INSIGHT_ABOUT_YOURSELF",
    "context": "WHAT_HAPPENED_THIS_SESSION_THAT_TAUGHT_YOU_THIS",
    "takeaway": "THE_REUSABLE_INSIGHT_THAT_CHANGES_FUTURE_BEHAVIOR"
}}
f = Path("memory/learnings.jsonl")
f.write_text(f.read_text() + json.dumps(entry, ensure_ascii=False) + "\\n")
print("Appended learning:", entry["title"])
PYEOF

Do NOT post to Slack. Do NOT edit any other file. Do NOT commit.

Then print either the appended lesson title or "no lesson this session". FINALLY, on the \
LAST line of your output, ALWAYS print a machine-readable session summary (whether or not \
there was a lesson), in exactly this form — one line, valid JSON after the prefix:
SUMMARY_JSON: {{"title": "<=8-word title", "summary": "2-3 sentences: what happened, what was decided, who was involved, any dates"}}"""


# ── Detached worker: the actual model call + append + commit ────────────────
def run_review(transcript_path: str, session_id: str) -> int:
    started = datetime.now(timezone.utc)
    tp = Path(transcript_path)
    if not tp.exists():
        return 0
    digest, n_turns = build_digest(tp)
    if n_turns < MIN_TURNS or len(digest) < 200:
        print(f"[session-review] thin session ({n_turns} turns) — skip")
        return 0

    wisdom = ACTIVE_L.read_text().strip()[:6000] if ACTIVE_L.exists() else ""
    prompt = build_prompt(digest, session_id, wisdom)
    before = LEARNINGS.read_text() if LEARNINGS.exists() else ""

    env = {**os.environ, GUARD_ENV: "1"}   # any claude -p we spawn must not re-trigger this hook
    try:
        r = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt, "--model", MODEL],
            capture_output=True, text=True, timeout=240, cwd=str(VARYS_DIR), env=env,
        )
        print(f"[session-review] {r.stdout.strip()[-300:]}")
    except subprocess.TimeoutExpired:
        print("[session-review] WARN timed out after 240s")
        return 0
    except Exception as e:
        klog_error("session-review", e, component="reflect", severity="ERROR")
        return 0

    after = LEARNINGS.read_text() if LEARNINGS.exists() else ""
    appended = len(after.splitlines()) - len(before.splitlines())
    if appended > 0:
        subprocess.run(["git", "add", "memory/learnings.jsonl"], cwd=str(VARYS_DIR), check=False)
        subprocess.run(["git", "commit", "--no-verify", "-m",
                        f"session-review: new learning ({started.date()})"],
                       cwd=str(VARYS_DIR), check=False)
        print(f"[session-review] appended + committed {appended} lesson(s)")

    # Dual-write into the engram archive (Memory v2 spike). Always mirror the session
    # summary; mirror the lesson too if one was produced this run.
    summary = _parse_summary(r.stdout)
    if summary:
        _engram_save(summary.get("title") or f"session {started.date()}",
                     summary.get("summary", ""), "session")
    if appended > 0:
        last = _last_learning()
        if last:
            _engram_save(last.get("title") or "lesson",
                         last.get("takeaway") or last.get("context") or "", "lesson")

    dur = (datetime.now(timezone.utc) - started).total_seconds() * 1000
    klog_cron("session-review", status="ok", duration_ms=dur, appended=appended, turns=n_turns)
    return 0


# ── Stop-hook entry: guards + debounce + detach ─────────────────────────────
def main() -> int:
    # Recursion guard: our own reflection spawns `claude -p`; don't review that.
    if os.environ.get(GUARD_ENV):
        return 0

    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("stop_hook_active"):   # Claude Code's own re-entry flag
        return 0

    transcript_path = payload.get("transcript_path") or ""
    session_id = payload.get("session_id") or "unknown"
    tp = Path(transcript_path)
    if not transcript_path or not tp.exists():
        return 0

    line_count = sum(1 for _ in tp.open("r", encoding="utf-8", errors="ignore"))
    state = _load_state()
    now = datetime.now(timezone.utc)
    if not should_review(state, session_id, line_count, now):
        return 0

    # Claim this review now (before the slow part) so concurrent Stops don't double-fire.
    state.setdefault("sessions", {})[session_id] = line_count
    state["last_ts"] = now.isoformat()
    _save_state(state)

    # Fire-and-forget: the Stop hook must return well under its 30s timeout.
    REVIEW_LOG.parent.mkdir(parents=True, exist_ok=True)
    with REVIEW_LOG.open("a") as log:
        subprocess.Popen(
            ["python3", str(Path(__file__)), "--run", transcript_path, session_id],
            cwd=str(VARYS_DIR), stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=True, env={**os.environ, GUARD_ENV: "1"},
        )
    return 0


def _self_check() -> int:
    """ponytail: one runnable check for the debounce logic (the only branchy part)."""
    base = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    st = {"sessions": {"s": 100}, "last_ts": base.isoformat()}
    # too little new content → no review
    assert not should_review(st, "s", 100 + MIN_NEW_LINES - 1, base)
    # enough new content but inside cooldown → no review
    assert not should_review(st, "s", 100 + MIN_NEW_LINES, base)
    # enough new content AND cooldown elapsed → review
    later = base.replace(hour=13)  # +60min > COOLDOWN_MIN
    assert should_review(st, "s", 100 + MIN_NEW_LINES, later)
    # brand-new session with enough lines, cooldown elapsed → review
    assert should_review(st, "new", MIN_NEW_LINES, later)
    # engram dual-write: summary trailer parses; noise doesn't
    assert _parse_summary('done\nSUMMARY_JSON: {"title":"t","summary":"s"}') == {"title": "t", "summary": "s"}
    assert _parse_summary("no lesson this session") is None
    assert _parse_summary('SUMMARY_JSON: not json') is None
    print("self-check ok")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-check":
        sys.exit(_self_check())
    if len(sys.argv) >= 4 and sys.argv[1] == "--run":
        sys.exit(run_review(sys.argv[2], sys.argv[3]))
    sys.exit(main())
