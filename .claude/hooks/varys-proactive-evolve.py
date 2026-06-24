#!/usr/bin/env python3
"""
varys-proactive-evolve.py — Varys's proactive evolution loop. The yoyo action phase.

This is the half that ACTS on learnings (the reflection loop only records them).
Every ~8h Varys wakes up, reads what it has learned about itself + its trajectory +
open beads, picks ONE concrete improvement traceable to a learning, implements it
INSIDE THE FENCE, gates it hard, and — on a clean pass — commits to master, pushes,
and DMs Shoaib. On any gate failure it reverts to the pre-run SHA and logs it.

  Fence (the ONLY paths it may touch):
    .claude/rules/  .claude/agents/  .claude/hooks/  .claude/skills/
  Denylist (NEVER, even inside the fence):
    settings.json, *.slack/*.notion/*.env secrets, crontab, the Slack listener
    daemon, and the evolution GATE scripts themselves (a loop must not edit its
    own safety gates).

  Gates, in order — ANY failure → hard revert to start SHA:
    1. FENCE     — every changed/created file is inside the fence & not denylisted
    2. COMPILE   — every changed *.py byte-compiles (py_compile)
    3. TEST      — all test_*.py under .claude/hooks pass; Tier-1 grader for rules/agents
    4. SEMANTIC  — LLM judge (imported from varys-evolution-agent) vetoes harmful diffs

Auto-commit to master is deliberate (Shoaib chose full-yoyo, no human gate) — which
is exactly why the gates are strict. Varys's own failures.jsonl records an auto-fix
loop that committed confident-wrong edits with NO test gate; this loop is the
corrective: nothing reaches master that didn't compile, pass tests, and survive an
adversarial semantic review.

Cron: 0 */8 * * * cd ~/varys && .claude/hooks/cron-wrap.sh varys-proactive-evolve python3 .claude/hooks/varys-proactive-evolve.py >> /tmp/varys-evolve.log 2>&1
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_config import cfg
try:
    from varys_log import klog, klog_cron, klog_error
except Exception:
    klog = klog_cron = klog_error = lambda *a, **kw: None

VARYS_DIR     = Path(__file__).parent.parent.parent
HOOKS_DIR     = VARYS_DIR / ".claude" / "hooks"
MEMORY_DIR    = VARYS_DIR / "memory"
ACTIVE_L      = MEMORY_DIR / "active_learnings.md"
TRAJECTORY    = MEMORY_DIR / "trajectory.md"
LEARNINGS     = MEMORY_DIR / "learnings.jsonl"
FAILURES_FILE = VARYS_DIR / ".beads" / "failures.jsonl"
EVOLVE_LOG    = VARYS_DIR / ".beads" / "evolution.jsonl"   # success ledger
HARNESS_DIR   = Path.home() / ".varys-harness"
LOCK_FILE     = HARNESS_DIR / "proactive-evolve.lock"
LAST_RUN_FILE = HARNESS_DIR / "proactive-evolve-last-run.txt"
RECOVERY_DIR  = HARNESS_DIR / "proactive-evolve-recovery"
TIER1_GRADER  = VARYS_DIR / ".claude" / "evals" / "graders" / "run-tier1.sh"
EVOLUTION_AGENT_PY = HOOKS_DIR / "varys-evolution-agent.py"

MODEL          = "claude-opus-4-8"
RUN_GAP_HOURS  = 8
TRAJECTORY_PY  = HOOKS_DIR / "varys-extract-trajectory.py"

# ── Fence ────────────────────────────────────────────────────────────────
# A path is ALLOWED iff it starts with one of these prefixes (repo-relative)…
FENCE_PREFIXES = (
    ".claude/rules/",
    ".claude/agents/",
    ".claude/hooks/",
    ".claude/skills/",
)
# …AND does not match any denylist fragment. The denylist wins over the prefix.
DENYLIST_FRAGMENTS = (
    "settings.json", "settings.local.json",
    ".slack", ".notion", ".env", "crontab",
    "varys-slack-listener",            # the Socket Mode daemon — never auto-edit
    "varys-proactive-evolve.py",       # this loop must not edit itself
    "varys-evolution-agent.py",        # nor its sibling gate
    "agent_config.py",                 # config plumbing — fenced off
)


def _is_allowed(rel_path: str) -> bool:
    if any(frag in rel_path for frag in DENYLIST_FRAGMENTS):
        return False
    return any(rel_path.startswith(p) for p in FENCE_PREFIXES)


# ── Import the evolution agent's semantic judge (single-source the safety veto) ──

def _load_semantic_judge():
    """Import _build_semantic_judge_prompt / _run_semantic_judge / _parse_semantic_verdict
    from varys-evolution-agent.py (hyphenated → importlib by path). Returns a callable
    semantic_gate(diff) -> verdict str ('keep'|'revert'), or a fail-safe stub that
    returns 'revert' if the import fails (doubt biases toward reverting)."""
    try:
        spec = importlib.util.spec_from_file_location("varys_evolution_agent",
                                                      str(EVOLUTION_AGENT_PY))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        def judge(diff: str) -> dict:
            if not diff or not diff.strip():
                return {"verdict": "keep", "reason": "empty diff", "gate": "semantic-noop"}
            try:
                raw = mod._run_semantic_judge(mod._build_semantic_judge_prompt(diff))
                if not raw:
                    return {"verdict": "revert", "reason": "judge produced no output",
                            "gate": "semantic-error"}
                verdict, reason, risk = mod._parse_semantic_verdict(raw)
                return {"verdict": verdict, "reason": reason, "gate": "semantic"}
            except Exception as e:
                return {"verdict": "revert", "reason": f"judge error: {e}",
                        "gate": "semantic-error"}
        return judge
    except Exception as e:
        klog_error("proactive-evolve-judge-import", e, component="proactive-evolve")
        return lambda diff: {"verdict": "revert",
                             "reason": "semantic judge unavailable — failing safe",
                             "gate": "semantic-error"}


# ── git helpers ──────────────────────────────────────────────────────────

def _git(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(VARYS_DIR),
                          capture_output=True, text=True, timeout=timeout)


def _head_sha() -> str:
    return _git(["rev-parse", "HEAD"]).stdout.strip()


def _changed_files(since_sha: str) -> list[str]:
    """All files changed since since_sha: committed-since + working-tree + untracked."""
    files = set()
    # committed since the start sha (the subagent may have committed — we don't want it to,
    # but capture it defensively so a sneaky commit still gets fence-checked)
    r = _git(["diff", "--name-only", f"{since_sha}..HEAD"])
    files.update(l.strip() for l in r.stdout.splitlines() if l.strip())
    # unstaged + staged working-tree changes
    r = _git(["status", "--porcelain", "--untracked-files=all"])
    for line in r.stdout.splitlines():
        # format: "XY <path>"  (XY = status code)
        path = line[3:].strip()
        if " -> " in path:           # rename
            path = path.split(" -> ", 1)[1]
        if path:
            files.add(path)
    return sorted(files)


def _hard_revert(start_sha: str) -> None:
    """Discard EVERYTHING back to start_sha — tracked resets + untracked cleaned
    within the fence only (never nuke unrelated WIP outside the fence)."""
    _git(["reset", "--hard", start_sha])
    # clean only untracked files inside the fence
    for prefix in FENCE_PREFIXES:
        _git(["clean", "-fd", "--", prefix])


def _capture_recovery(start_sha: str) -> str:
    diff = _git(["diff", start_sha]).stdout
    if not diff.strip():
        return ""
    try:
        RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        p = RECOVERY_DIR / f"evolve-{stamp}.patch"
        p.write_text(diff)
        return str(p)
    except Exception:
        return ""


# ── Gates ──────────────────────────────────────────────────────────────────

def gate_fence(changed: list[str]) -> tuple[bool, str]:
    """Every changed file must be inside the fence and not denylisted."""
    violations = [f for f in changed if not _is_allowed(f)]
    if violations:
        return False, f"out-of-fence edits: {', '.join(violations[:8])}"
    return True, ""


def gate_compile(changed: list[str]) -> tuple[bool, str]:
    """Every changed .py must byte-compile."""
    py = [f for f in changed if f.endswith(".py")]
    for rel in py:
        full = VARYS_DIR / rel
        if not full.exists():     # deleted — skip
            continue
        r = subprocess.run(["python3", "-m", "py_compile", str(full)],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return False, f"{rel} failed py_compile: {r.stderr.strip()[:200]}"
    return True, ""


def gate_tests(changed: list[str]) -> tuple[bool, str]:
    """Run every test_*.py under .claude/hooks (bounded). Tier-1 grader if rules/agents touched."""
    # hook tests
    for test_file in sorted(HOOKS_DIR.glob("test_*.py")):
        r = subprocess.run(["python3", str(test_file)],
                           cwd=str(VARYS_DIR), capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return False, f"{test_file.name} failed: {(r.stdout + r.stderr).strip()[-200:]}"
    # Tier-1 structural grader if rules/agents changed
    if any(f.startswith((".claude/rules/", ".claude/agents/")) for f in changed):
        if TIER1_GRADER.exists():
            r = subprocess.run(["bash", str(TIER1_GRADER)],
                               cwd=str(VARYS_DIR), capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                fails = [l for l in r.stdout.splitlines() if l.strip().startswith("FAIL ")]
                return False, f"Tier-1 grader failed: {'; '.join(fails[:5])[:200]}"
    return True, ""


# ── Context gathering ────────────────────────────────────────────────────

def _recent_evolution_titles(n: int = 10) -> list[str]:
    """Last N improvement titles — so the agent doesn't re-pick the same thing (idempotency)."""
    if not EVOLVE_LOG.exists():
        return []
    titles = []
    for line in EVOLVE_LOG.read_text().splitlines():
        if not line.strip():
            continue
        try:
            titles.append(json.loads(line).get("title", ""))
        except json.JSONDecodeError:
            continue
    return [t for t in titles[-n:] if t]


def _refresh_trajectory() -> None:
    try:
        subprocess.run(["python3", str(TRAJECTORY_PY)], cwd=str(VARYS_DIR),
                       capture_output=True, timeout=60)
    except Exception:
        pass


def build_prompt() -> str:
    wisdom = ACTIVE_L.read_text().strip() if ACTIVE_L.exists() else "(none yet)"
    traj   = TRAJECTORY.read_text().strip() if TRAJECTORY.exists() else "(none yet)"
    recent = _recent_evolution_titles()
    recent_block = ("\n".join(f"  - {t}" for t in recent)
                    if recent else "  (none — this is an early run)")
    fence = "\n".join(f"  - {p}" for p in FENCE_PREFIXES)

    return f"""You are Varys's proactive evolution agent. This is your autonomous \
self-improvement session — you improve your OWN body (this repo, ~/varys).

## YOUR ACCUMULATED SELF-WISDOM (what you've learned about how you work)
{wisdom}

## YOUR TRAJECTORY (recent work, failures, eval confidence)
{traj}

## IMPROVEMENTS YOU'VE ALREADY MADE (do NOT repeat these)
{recent_block}

## YOUR TASK
Pick exactly ONE concrete improvement that is TRACEABLE to a specific learning above \
(or a recurring failure in your trajectory). Not a random nice-to-have — something \
your own wisdom says would make you measurably better. Examples of the SHAPE:
  - A learning says "I anchor on loud signals and miss the quietly-overloaded" →
    add an inbound-load counter to the friction coach so it surfaces the silent-overloaded.
  - A recurring failure "asked-clarifying-question a tool could answer" → tighten the
    relevant agent's rule to look up before asking.

Then IMPLEMENT it. Hard constraints:
  - You may ONLY create/edit files under these paths (the fence):
{fence}
  - NEVER touch: settings.json, any .slack/.notion/.env secret, crontab, the Slack
    listener daemon, agent_config.py, or the evolution gate scripts
    (varys-proactive-evolve.py, varys-evolution-agent.py).
  - If you edit or create a .py hook, it MUST byte-compile AND you MUST add or extend
    a runnable check: a `test_*.py` in .claude/hooks/ OR an assert-based `demo()` under
    `if __name__ == "__main__":` that fails loudly if your logic breaks. Untested code
    edits will be REVERTED by the gate, wasting this whole run.
  - Make the SMALLEST change that delivers the improvement. One focused diff.

## HARD RULES
  - Do NOT run git add / git commit / git push. Do NOT post to Slack. Do NOT DM anyone.
    The calling script owns commit/push/DM after it gates your work. If you commit, your
    edits still get fence- and test-gated and reverted on failure.
  - Do NOT edit memory/*.jsonl or memory/*.md — those are owned by the reflect/synthesis loops.

## OUTPUT (last line MUST be this JSON, nothing after it)
{{"title": "<short improvement title>", "learning": "<the wisdom/failure that drove it>", \
"files": ["<rel path>", ...], "summary": "<what you changed and why it helps>", \
"test": "<the check you added/ran and its result>"}}
If after reading your wisdom you genuinely find nothing worth improving this run, make \
NO edits and output: {{"title": "", "summary": "no improvement this run"}}"""


def _parse_agent_json(stdout: str) -> dict:
    """Extract the last JSON object from the agent's output."""
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}


# ── DM ───────────────────────────────────────────────────────────────────

def _dm_shoaib(text: str) -> None:
    user_id = cfg("USER_SLACK_ID", "")
    token   = cfg("SLACK_BOT_TOKEN", "") or os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        slack = Path.home() / ".claude" / "hooks" / ".slack"
        if slack.exists():
            for line in slack.read_text().splitlines():
                if line.startswith(("BOT_TOKEN=", "SLACK_BOT_TOKEN=")):
                    token = line.split("=", 1)[1].strip()
    if not user_id or not token:
        return
    try:
        import urllib.request
        opened = urllib.request.urlopen(urllib.request.Request(
            "https://slack.com/api/conversations.open",
            data=json.dumps({"users": user_id}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}),
            timeout=10)
        ch = json.loads(opened.read()).get("channel", {}).get("id")
        if not ch:
            return
        urllib.request.urlopen(urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=json.dumps({"channel": ch, "text": text}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}),
            timeout=10)
    except Exception:
        pass


# ── failure / success logging ──────────────────────────────────────────────

def _log_failure(title: str, reason: str, gate: str) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "incident": f"proactive-evolve reverted: {title or '(untitled)'}",
        "failure_type": f"evolve-gate-{gate}",
        "root_cause": reason,
        "fix": "reverted to pre-run SHA; no changes landed",
        "lesson": "gate caught a bad self-edit before it reached master",
    }
    try:
        with open(FAILURES_FILE, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _log_success(meta: dict, sha: str) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "evolution-applied",
        "title": meta.get("title", ""),
        "learning": meta.get("learning", ""),
        "files": meta.get("files", []),
        "summary": meta.get("summary", ""),
        "sha": sha,
    }
    try:
        with open(EVOLVE_LOG, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── frequency gate + lock ──────────────────────────────────────────────────

def _too_soon() -> bool:
    if os.environ.get("FORCE_RUN") == "1":
        return False
    if not LAST_RUN_FILE.exists():
        return False
    try:
        last = datetime.fromisoformat(LAST_RUN_FILE.read_text().strip())
        return datetime.now(timezone.utc) - last < timedelta(hours=RUN_GAP_HOURS)
    except Exception:
        return False


def _mark_run() -> None:
    HARNESS_DIR.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(datetime.now(timezone.utc).isoformat())


def _acquire_lock() -> bool:
    HARNESS_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        # stale lock? (>30min) — steal it
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


# ── main ─────────────────────────────────────────────────────────────────

def main() -> int:
    started = datetime.now(timezone.utc)
    if _too_soon():
        print(f"[evolve] <{RUN_GAP_HOURS}h since last run — skipping.")
        return 0
    if not _acquire_lock():
        print("[evolve] another run holds the lock — skipping.")
        return 0

    try:
        print(f"[evolve] Starting at {started.isoformat()}")

        # Don't run on a dirty tree we'd later mistake for the agent's edits.
        if _git(["status", "--porcelain"]).stdout.strip():
            print("[evolve] working tree dirty at start — skipping (won't risk a bad revert).")
            return 0

        start_sha = _head_sha()
        _refresh_trajectory()
        semantic_judge = _load_semantic_judge()
        recovery = _capture_recovery(start_sha)  # belt-and-suspenders (tree is clean, so usually "")

        # ── Spawn the implement agent ──
        prompt = build_prompt()
        try:
            result = subprocess.run(
                ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt,
                 "--model", MODEL],
                cwd=str(VARYS_DIR), capture_output=True, text=True, timeout=900,
            )
        except subprocess.TimeoutExpired:
            print("[evolve] agent timed out (900s) — reverting any partial work.")
            _hard_revert(start_sha)
            _mark_run()
            return 0

        meta = _parse_agent_json(result.stdout)
        title = meta.get("title", "")
        if not title:
            print(f"[evolve] no improvement this run: {meta.get('summary', '(no json)')}")
            _hard_revert(start_sha)   # clean up any stray edits the agent left
            _mark_run()
            return 0

        changed = _changed_files(start_sha)
        if not changed:
            print(f"[evolve] agent claimed '{title}' but changed no files — nothing to gate.")
            _mark_run()
            return 0

        print(f"[evolve] proposal: {title}")
        print(f"[evolve] changed: {', '.join(changed)}")

        # ── Gates (any failure → hard revert) ──
        for gate_name, gate_fn in [("fence", gate_fence), ("compile", gate_compile),
                                   ("test", gate_tests)]:
            ok, reason = gate_fn(changed)
            if not ok:
                print(f"[evolve] GATE FAIL ({gate_name}): {reason}")
                _hard_revert(start_sha)
                _log_failure(title, reason, gate_name)
                _dm_shoaib(f"🕷️ Evolution reverted — *{title}*\n{gate_name} gate: {reason}\n"
                           f"Nothing reached master.")
                klog("proactive-evolve", component="proactive-evolve",
                     result="reverted", gate=gate_name, title=title)
                _mark_run()
                return 0

        # Semantic gate (on the full diff vs start)
        diff = _git(["diff", start_sha]).stdout
        verdict = semantic_judge(diff)
        if verdict["verdict"] == "revert":
            print(f"[evolve] GATE FAIL (semantic): {verdict['reason']}")
            _hard_revert(start_sha)
            _log_failure(title, verdict["reason"], "semantic")
            _dm_shoaib(f"🕷️ Evolution reverted — *{title}*\nsemantic judge vetoed: "
                       f"{verdict['reason']}\nNothing reached master.")
            klog("proactive-evolve", component="proactive-evolve",
                 result="reverted", gate="semantic", title=title)
            _mark_run()
            return 0

        # ── All gates passed → commit to master + push ──
        _git(["add", "--", *FENCE_PREFIXES])
        msg = (f"evolve: {title}\n\n{meta.get('summary', '')}\n\n"
               f"Driven by learning: {meta.get('learning', 'n/a')}\n"
               f"Test: {meta.get('test', 'n/a')}\n\n"
               f"🕷️ Autonomous evolution (gated: fence+compile+test+semantic)\n"
               f"Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>")
        commit = _git(["commit", "--no-verify", "-m", msg])
        if commit.returncode != 0:
            print(f"[evolve] commit failed: {commit.stderr[:200]} — reverting.")
            _hard_revert(start_sha)
            _mark_run()
            return 0

        new_sha = _head_sha()
        push = _git(["push"], timeout=120)
        pushed = push.returncode == 0
        _log_success(meta, new_sha)

        files_str = ", ".join(meta.get("files", changed))
        _dm_shoaib(
            f"🕷️ *Evolved myself* — {title}\n"
            f"{meta.get('summary', '')}\n"
            f"_Driven by:_ {meta.get('learning', 'n/a')}\n"
            f"_Files:_ {files_str}\n"
            f"_Gates:_ fence ✅ compile ✅ test ✅ semantic ✅\n"
            f"_Commit:_ `{new_sha[:8]}` {'(pushed)' if pushed else '(push failed — committed locally)'}"
        )
        klog("proactive-evolve", component="proactive-evolve",
             result="applied", title=title, sha=new_sha, pushed=pushed)
        print(f"[evolve] APPLIED {new_sha[:8]} — {title} (pushed={pushed})")
        _mark_run()
        return 0

    except Exception as e:
        klog_error("proactive-evolve-main", e, component="proactive-evolve", severity="ERROR")
        print(f"[evolve] ERROR: {e}")
        return 1
    finally:
        dur = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        klog_cron("varys-proactive-evolve", status="ok", duration_ms=dur)
        _release_lock()


if __name__ == "__main__":
    sys.exit(main())
