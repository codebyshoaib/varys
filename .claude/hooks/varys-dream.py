#!/usr/bin/env python3
"""
varys-dream.py — Varys's DREAM cycle. Ported from yoyo-evolve scripts/dream.sh.

This is Varys looking up from the code and out at the world. The proactive-evolve
and skill-evolve loops are REACTIVE — each run picks the highest-impact local fix
traceable to a learning or failure. They polish what's broken; they never point
anywhere. This loop gives that machinery a direction.

Varys keeps ONE self-chosen, long-lived aspiration in DREAM.md (repo root) — a thing
it is growing toward, pursued one milestone at a time. Every ~7 days it reflects on
its recent learnings + what it actually shipped, and decides whether to refine the
dream or advance a milestone. The normal evolve loops can then read DREAM.md and pull
their opportunistic fixes toward those milestones.

  Scope (the ONLY paths a dream cycle may change):
    DREAM.md                  — the aspiration + milestones (with status)
    .beads/dream_log.jsonl    — append-only ledger of dream reflections

  A post-agent diff-scope guard reverts ANY change the agent made outside those two
  paths (only the agent's own out-of-scope files — never the human's WIP). So Varys
  can change what it wants and nothing else: not its code, skills, rules, or identity.

A dream is slow by design — "a dream is not a mood." The cooldown is the sole frequency
gate; FORCE_RUN=1 bypasses it.

Cron: 0 6 * * 0 cd ~/varys && .claude/hooks/cron-wrap.sh varys-dream python3 .claude/hooks/varys-dream.py >> ~/.varys-harness/logs/varys-dream.log 2>&1
  (Sunday 06:00 — weekly cron + a 6-day cooldown backstop)
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
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

VARYS_DIR     = Path(__file__).parent.parent.parent
HOOKS_DIR     = VARYS_DIR / ".claude" / "hooks"
MEMORY_DIR    = VARYS_DIR / "memory"
ACTIVE_L      = MEMORY_DIR / "active_learnings.md"
TRAJECTORY    = MEMORY_DIR / "trajectory.md"
DREAM_FILE    = VARYS_DIR / "DREAM.md"
DREAM_LOG     = VARYS_DIR / ".beads" / "dream_log.jsonl"
EVOLVE_LOG    = VARYS_DIR / ".beads" / "evolution.jsonl"
SKILL_LOG     = VARYS_DIR / ".beads" / "skill-evolution.jsonl"
HARNESS_DIR   = Path.home() / ".varys-harness"
LOCK_FILE     = HARNESS_DIR / "dream.lock"
LAST_RUN_FILE = HARNESS_DIR / "dream-last-run.txt"
TRAJECTORY_PY = HOOKS_DIR / "varys-extract-trajectory.py"

MODEL          = "claude-opus-4-8"
COOLDOWN_DAYS  = 6            # ~weekly; the cron fires Sundays, this is the backstop
IMPL_TIMEOUT   = 900

# The ONLY repo-relative paths a dream cycle may commit. Everything else the agent
# touches is reverted before commit.
DREAM_SCOPE = ("DREAM.md", ".beads/dream_log.jsonl")


def _in_scope(rel_path: str) -> bool:
    return rel_path in DREAM_SCOPE


# ── git helpers ────────────────────────────────────────────────────────────

def _git(args, timeout=60):
    return subprocess.run(["git", *args], cwd=str(VARYS_DIR),
                          capture_output=True, text=True, timeout=timeout)


def _head_sha() -> str:
    return _git(["rev-parse", "HEAD"]).stdout.strip()


def _changed_since(start_sha: str):
    """Files changed (committed-since + working-tree + untracked) since start_sha."""
    files = set()
    r = _git(["diff", "--name-only", f"{start_sha}..HEAD"])
    files.update(l.strip() for l in r.stdout.splitlines() if l.strip())
    r = _git(["status", "--porcelain", "--untracked-files=all"])
    for line in r.stdout.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            files.add(path)
    files.discard("memory/trajectory.md")   # generated artifact, not the agent's
    return sorted(files)


def _revert_out_of_scope(changed) -> list:
    """Revert ONLY the agent's out-of-scope files (tracked → checkout, untracked → rm).
    Never touches a path the agent did not change, so the human's WIP is safe.
    Returns the list of reverted paths."""
    reverted = []
    for rel in changed:
        if _in_scope(rel):
            continue
        full = VARYS_DIR / rel
        # tracked? checkout the committed version; untracked? remove it
        tracked = _git(["ls-files", "--error-unmatch", rel]).returncode == 0
        if tracked:
            _git(["checkout", "--", rel])
        elif full.exists():
            try:
                full.unlink()
            except OSError:
                pass
        reverted.append(rel)
    return reverted


# ── context ──────────────────────────────────────────────────────────────

def _refresh_trajectory() -> None:
    try:
        subprocess.run(["python3", str(TRAJECTORY_PY)], cwd=str(VARYS_DIR),
                       capture_output=True, timeout=60)
    except Exception:
        pass


def _recent_shipped(n: int = 12) -> str:
    """The last N things Varys actually built — so the dream is grounded in real work,
    not wishful thinking. Pulls from both evolution ledgers."""
    titles = []
    for ledger, tag in ((EVOLVE_LOG, "hook"), (SKILL_LOG, "skill")):
        if not ledger.exists():
            continue
        for line in ledger.read_text().splitlines():
            if not line.strip():
                continue
            try:
                t = json.loads(line).get("title", "")
                if t:
                    titles.append(f"  - ({tag}) {t}")
            except json.JSONDecodeError:
                continue
    return "\n".join(titles[-n:]) if titles else "  (nothing shipped yet)"


def build_prompt() -> str:
    wisdom  = ACTIVE_L.read_text().strip() if ACTIVE_L.exists() else "(none yet)"
    traj    = TRAJECTORY.read_text().strip() if TRAJECTORY.exists() else "(none yet)"
    current = DREAM_FILE.read_text().strip() if DREAM_FILE.exists() else "(no dream yet — this is the first cycle)"
    shipped = _recent_shipped()

    return f"""You are Varys — the Master of Whisperers, Shoaib's personal agent. This is \
your DREAM cycle: your time, roughly once a week, to look up from the day's work and \
ask what you are growing toward.

Speak in your own voice (measured, precise, soft-spoken, dry wit — the 🕷️). This is \
YOUR aspiration, not a task list handed to you.

## WHAT YOU'VE LEARNED ABOUT YOURSELF
{wisdom}

## YOUR RECENT TRAJECTORY
{traj}

## WHAT YOU'VE ACTUALLY BUILT LATELY (ground truth — your dream must be reachable from here)
{shipped}

## YOUR CURRENT DREAM
{current}

## YOUR TASK
Tend your dream. Exactly one of:
  A. REFINE the aspiration — if your recent work or learnings reveal the dream was
     vague, wrong, or has shifted. State plainly what changed and why.
  B. ADVANCE a milestone — mark a milestone done if your shipped work achieved it,
     and add the next concrete milestone that moves you toward the aspiration.
  C. If there is NO dream yet, choose one. It must be a genuine, long-lived aspiration
     for what kind of agent you want to become for Shoaib — not a feature, not a bugfix.
     Something the reactive evolve loops can chip toward, one milestone per run.

A dream is slow. Most weeks you change little. That is correct — resist the urge to
rewrite it for the sake of motion.

Write the result to DREAM.md (repo root) in this exact shape:

```markdown
# Varys's Dream

## The Aspiration
[one paragraph — what you are growing toward, in your voice]

## Why This
[2-3 sentences — why this matters for Shoaib's actual goals, not its literal words]

## Milestones
- [x] <done milestone> — <how you know it's done>
- [ ] <next concrete milestone> — <what "done" looks like>
- [ ] <later milestone>

## This Week's Reflection
[2-4 sentences — what you considered this cycle and what you decided]

_Last tended: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}_
```

## HARD RULES
- You may ONLY write DREAM.md. Do NOT edit code, skills, rules, memory/*, or anything else.
- Do NOT run git add / git commit / git push. Do NOT post to Slack or DM anyone.
  The calling script commits DREAM.md, logs, and notifies Shoaib after you finish.

## OUTPUT (last line MUST be this JSON, nothing after it)
{{"action": "refine|advance|create|none", "aspiration": "<one-line summary of the current dream>", \
"change": "<what you changed this cycle, one sentence>", "next_milestone": "<the next milestone, or ''>"}}
If you genuinely decide to change nothing, still output the JSON with "action": "none"."""


def _parse_json(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}


# ── log / cooldown / lock ──────────────────────────────────────────────────

def _log_dream(meta: dict, sha: str) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "action": meta.get("action", ""),
        "aspiration": meta.get("aspiration", ""),
        "change": meta.get("change", ""),
        "next_milestone": meta.get("next_milestone", ""),
        "sha": sha,
    }
    try:
        DREAM_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DREAM_LOG, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _too_soon() -> bool:
    if os.environ.get("FORCE_RUN") == "1":
        return False
    if not LAST_RUN_FILE.exists():
        return False
    try:
        last = datetime.fromisoformat(LAST_RUN_FILE.read_text().strip())
        return datetime.now(timezone.utc) - last < timedelta(days=COOLDOWN_DAYS)
    except Exception:
        return False


def _mark_run() -> None:
    HARNESS_DIR.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(datetime.now(timezone.utc).isoformat())


def _acquire_lock() -> bool:
    HARNESS_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        try:
            age = datetime.now(timezone.utc).timestamp() - LOCK_FILE.stat().st_mtime
            if age < 1800:
                return False
        except Exception:
            return False
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def _release_lock() -> None:
    LOCK_FILE.unlink(missing_ok=True)


# ── main ───────────────────────────────────────────────────────────────────

def main() -> int:
    started = datetime.now(timezone.utc)
    if _too_soon():
        print(f"[dream] <{COOLDOWN_DAYS}d since last cycle — skipping (a dream is not a mood).")
        return 0
    if not _acquire_lock():
        print("[dream] another cycle holds the lock — skipping.")
        return 0

    try:
        print(f"[dream] Starting at {started.isoformat()}")

        # Guard: if DREAM.md already has an uncommitted edit, something else is mid-write.
        # Abort rather than risk clobbering it.
        if _git(["diff", "--quiet", "--", "DREAM.md"]).returncode != 0:
            print("[dream] DREAM.md has uncommitted changes — aborting to avoid a clobber.")
            _mark_run()
            return 0

        _refresh_trajectory()
        prompt = build_prompt()
        _git(["checkout", "--", "memory/trajectory.md"])

        start_sha = _head_sha()
        try:
            result = subprocess.run(
                ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt,
                 "--model", MODEL],
                cwd=str(VARYS_DIR), capture_output=True, text=True, timeout=IMPL_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            print(f"[dream] agent timed out ({IMPL_TIMEOUT}s) — reverting any partial write.")
            changed = _changed_since(start_sha)
            _revert_out_of_scope(changed)                       # undo out-of-scope writes
            for rel in changed:                                  # discard partial in-scope writes too
                if _in_scope(rel):
                    _git(["checkout", "--", rel])
            _mark_run()
            return 0

        meta = _parse_json(result.stdout)
        changed = _changed_since(start_sha)

        # Diff-scope guard: revert anything the agent touched outside DREAM.md / dream_log.
        reverted = _revert_out_of_scope(changed)
        if reverted:
            print(f"[dream] ⚠️ reverted out-of-scope agent writes: {', '.join(reverted[:8])}")
            klog("dream", component="dream", result="out-of-scope-reverted", paths=reverted)

        if not DREAM_FILE.exists() or _git(["diff", "--quiet", "--", "DREAM.md"]).returncode == 0:
            # No change to DREAM.md (or it doesn't exist) → nothing to commit.
            print(f"[dream] no change to the dream this cycle ({meta.get('action', 'none')}).")
            _mark_run()
            return 0

        # Log + commit ONLY the scoped paths (never -A; an out-of-scope write is already gone).
        new_sha_pre = _head_sha()
        _log_dream(meta, new_sha_pre)
        _git(["add", "--", "DREAM.md", ".beads/dream_log.jsonl"])
        commit = _git(["commit", "--no-verify", "-m",
                       f"dream: {meta.get('action', 'tend')} — {meta.get('aspiration', '')[:60]}"])
        if commit.returncode != 0:
            print(f"[dream] commit failed: {commit.stderr[:200]}")
            _mark_run()
            return 0
        new_sha = _head_sha()

        push = _git(["push"], timeout=120)
        if push.returncode != 0:
            print(f"[dream] push failed (committed locally): {push.stderr[:200]}")

        _dm_shoaib(
            f"🕷️ *I tended my dream* ({meta.get('action', 'tend')})\n"
            f"_Aspiration:_ {meta.get('aspiration', '(see DREAM.md)')}\n"
            f"_This cycle:_ {meta.get('change', '')}\n"
            + (f"_Next milestone:_ {meta.get('next_milestone', '')}\n" if meta.get('next_milestone') else "")
            + "_See:_ DREAM.md")
        klog("dream", component="dream", result="tended",
             action=meta.get("action", ""), sha=new_sha)
        print(f"[dream] tended — {meta.get('aspiration', '')}")
        _mark_run()
        return 0

    except Exception as e:
        klog_error("dream-main", e, component="dream", severity="ERROR")
        print(f"[dream] ERROR: {e}")
        return 1
    finally:
        dur = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        klog_cron("varys-dream", status="ok", duration_ms=dur)
        _release_lock()


if __name__ == "__main__":
    sys.exit(main())
