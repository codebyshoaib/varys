#!/usr/bin/env python3
"""
varys-skill-evolve.py — Varys's skill-evolution loop. Evolves .claude/skills/varys/*.md.

Every ~8h Varys wakes up, reads its skill files + session logs + failures, picks ONE skill
to refine/extend/split/or create, implements the change INSIDE THE FENCE, gates it, and —
on a clean pass — pushes a branch and opens a PR, then DMs Shoaib the link.

  Fence (the ONLY path it may touch):
    .claude/skills/varys/
  Denylist (NEVER, even inside the fence):
    non-.md files, varys-skill-evolve.py itself (can't edit its own gates)

  Gates, in order — ANY failure → hard revert:
    1. FENCE     — every changed file is under .claude/skills/varys/ and is .md
    2. CONTENT   — each changed .md is non-empty, starts with a # title, and is < 200 lines
    3. SEMANTIC  — LLM judge (varys_semantic_gate.semantic_gate) vetoes harmful diffs

  No gate_compile (markdown) and no gate_tests (no .py files touched).

Cron: 0 4,12,20 * * * cd ~/varys && .claude/hooks/cron-wrap.sh varys-skill-evolve python3 .claude/hooks/varys-skill-evolve.py >> ~/.varys-harness/logs/varys-skill-evolve.log 2>&1
"""

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

VARYS_DIR        = Path(__file__).parent.parent.parent
MEMORY_DIR       = VARYS_DIR / "memory"
ACTIVE_L         = MEMORY_DIR / "active_learnings.md"
TRAJECTORY       = MEMORY_DIR / "trajectory.md"
FAILURES_FILE    = VARYS_DIR / ".beads" / "failures.jsonl"
SKILL_EVOLVE_LOG = VARYS_DIR / ".beads" / "skill-evolution.jsonl"  # success ledger
HARNESS_DIR      = Path.home() / ".varys-harness"
LOCK_FILE        = HARNESS_DIR / "skill-evolve.lock"
LAST_RUN_FILE    = HARNESS_DIR / "skill-evolve-last-run.txt"
WORKTREES_DIR    = HARNESS_DIR / "skill-evolve-worktrees"
TRAJECTORY_PY    = VARYS_DIR / ".claude" / "hooks" / "varys-extract-trajectory.py"

MODEL           = "claude-opus-4-8"
RUN_GAP_HOURS   = 8
IMPL_TIMEOUT    = 700   # seconds for the skill agent

# The working dir for all gate/git ops. Redirected to an isolated worktree during a run.
_WORK_DIR = VARYS_DIR

# ── Fence ─────────────────────────────────────────────────────────────────
SKILL_DIR_PREFIX = ".claude/skills/varys/"

DENYLIST_FRAGMENTS = (
    "varys-skill-evolve.py",  # the loop must not edit its own gates
    ".slack", ".notion", ".env", "crontab",
    "settings.json", "settings.local.json",
)


def _is_allowed(rel_path: str) -> bool:
    if any(frag in rel_path for frag in DENYLIST_FRAGMENTS):
        return False
    if not rel_path.startswith(SKILL_DIR_PREFIX):
        return False
    if not rel_path.endswith(".md"):
        return False
    return True


# ── Import the shared semantic judge ──────────────────────────────────────

def _load_semantic_judge():
    """Return the leaf semantic gate from the shared module.
    On import failure return a fail-safe stub that reverts (doubt biases toward reverting)."""
    try:
        from varys_semantic_gate import semantic_gate
        return semantic_gate
    except Exception as e:
        klog_error("skill-evolve-judge-import", e, component="skill-evolve")
        return lambda diff: {"verdict": "revert",
                             "reason": "semantic judge unavailable — failing safe",
                             "risk": "high", "gate": "semantic-error"}


# ── git helpers ───────────────────────────────────────────────────────────

def _git(args: list, timeout: int = 60):
    return subprocess.run(["git", *args], cwd=str(_WORK_DIR),
                          capture_output=True, text=True, timeout=timeout)


def _head_sha() -> str:
    return _git(["rev-parse", "HEAD"]).stdout.strip()


def _changed_files(since_sha: str) -> list:
    """All files changed since since_sha: committed-since + working-tree + untracked."""
    files = set()
    r = _git(["diff", "--name-only", f"{since_sha}..HEAD"])
    files.update(l.strip() for l in r.stdout.splitlines() if l.strip())
    r = _git(["status", "--porcelain", "--untracked-files=all"])
    for line in r.stdout.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            files.add(path)
    files.discard("memory/trajectory.md")
    files = {f for f in files if not f.startswith("session_plan")}
    return sorted(files)


# ── Gates ─────────────────────────────────────────────────────────────────

def gate_fence(changed: list) -> tuple:
    """Every changed file must be under .claude/skills/varys/ and be a .md file."""
    violations = [f for f in changed if not _is_allowed(f)]
    if violations:
        return False, f"out-of-fence edits: {', '.join(violations[:8])}"
    return True, ""


def gate_content(changed: list) -> tuple:
    """Every changed .md must have a # title, be non-empty, and be < 200 lines."""
    for rel in changed:
        if not rel.endswith(".md"):
            continue
        full = _WORK_DIR / rel
        if not full.exists():  # deleted — skip
            continue
        text = full.read_text(errors="replace")
        lines = text.splitlines()
        if not text.strip():
            return False, f"{rel} is empty"
        if not any(l.startswith("# ") for l in lines[:3]):
            return False, f"{rel} missing # title in first 3 lines"
        if len(lines) > 200:
            return False, f"{rel} is {len(lines)} lines (max 200 — split it)"
    return True, ""


# ── Context gathering ─────────────────────────────────────────────────────

def _recent_skill_evolution_titles(n: int = 10) -> list:
    """Last N skill improvement titles — prevents re-picking the same one."""
    if not SKILL_EVOLVE_LOG.exists():
        return []
    titles = []
    for line in SKILL_EVOLVE_LOG.read_text().splitlines():
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
    recent = _recent_skill_evolution_titles()
    recent_block = ("\n".join(f"  - {t}" for t in recent)
                    if recent else "  (none — this is an early run)")
    return (
        f"You are Varys's skill-evolution agent. Improve ONE skill file in"
        f" .claude/skills/varys/.\n\n"
        f"## YOUR SELF-WISDOM\n{wisdom}\n\n"
        f"## YOUR TRAJECTORY\n{traj}\n\n"
        f"## RECENT SKILL IMPROVEMENTS (do NOT repeat)\n{recent_block}\n\n"
        f"## TASK\n"
        f"Read all .md files under .claude/skills/varys/. Cross-reference:\n"
        f"1. .claude/rules/skills-router.md — what skills are expected to exist?\n"
        f"2. .beads/failures.jsonl — do any failures mention a skill behaving poorly?\n"
        f"3. memory/active_learnings.md — is any lesson NOT yet captured in a skill?\n\n"
        f"Pick ONE skill to improve (ranked by impact):\n"
        f"  A. EXTEND an existing skill that's missing a section (most common)\n"
        f"  B. SPLIT a skill that's >100 lines into two focused files\n"
        f"  C. REFINE a skill with rules that are too vague to act on\n"
        f"  D. CREATE a new skill for a gap in skills-router.md\n\n"
        f"DO NOT delete any skill file. If a skill should be retired, note it in the"
        f" summary and file a bead (type 'skill-retirement-proposal' in"
        f" .beads/failures.jsonl).\n\n"
        f"FENCE: ONLY edit/create files under .claude/skills/varys/. Nothing else.\n\n"
        f"After making your change verify: file is non-empty, starts with a `# Title`"
        f" line, is < 200 lines, and no section references a path that doesn't exist"
        f" in .claude/.\n\n"
        f"OUTPUT (last line MUST be this JSON):\n"
        f'{{"title": "...", "learning": "...", "files": [...], "summary": "...", "test": "..."}}\n'
        f'If nothing needs improving: {{"title": "", "summary": "no skill improvement this run"}}'
    )


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


from varys_dm import dm_shoaib as _dm_shoaib


# ── failure / success logging ─────────────────────────────────────────────

def _log_failure(title: str, reason: str, gate: str) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "incident": f"skill-evolve reverted: {title or '(untitled)'}",
        "failure_type": f"skill-evolve-gate-{gate}",
        "root_cause": reason,
        "fix": "reverted to pre-run SHA; no changes landed",
        "lesson": "gate caught a bad skill self-edit before it reached master",
    }
    try:
        with open(FAILURES_FILE, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _log_success(meta: dict, sha: str) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "skill-evolution-applied",
        "title": meta.get("title", ""),
        "learning": meta.get("learning", ""),
        "files": meta.get("files", []),
        "summary": meta.get("summary", ""),
        "sha": sha,
    }
    try:
        with open(SKILL_EVOLVE_LOG, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── frequency gate + lock ─────────────────────────────────────────────────

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


# ── branch / PR plumbing ──────────────────────────────────────────────────

def _slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:48] or "skill-improvement"


def _resolve_base() -> tuple:
    """Fetch origin and pick the base ref. Returns (base_ref_name, base_sha)."""
    _git(["fetch", "origin"], timeout=120)
    for ref in ("origin/master", "origin/main", "master", "main"):
        r = _git(["rev-parse", "--verify", "--quiet", ref])
        if r.returncode == 0 and r.stdout.strip():
            return ref, r.stdout.strip()
    return "HEAD", _head_sha()


def _open_pr(branch: str, base: str, title: str, body: str) -> str:
    """Open a PR via gh. Returns the PR URL, or '' on failure."""
    base_branch = base.split("/", 1)[1] if base.startswith("origin/") else base
    if base_branch in ("HEAD",):
        base_branch = "master"
    r = subprocess.run(
        ["gh", "pr", "create", "--base", base_branch, "--head", branch,
         "--title", title, "--body", body],
        cwd=str(VARYS_DIR), capture_output=True, text=True, timeout=120)
    out = (r.stdout + r.stderr).strip()
    m = re.search(r"https://github\.com/\S+/pull/\d+", out)
    return m.group(0) if m else ""


# ── main ──────────────────────────────────────────────────────────────────

def main() -> int:
    started = datetime.now(timezone.utc)
    if _too_soon():
        print(f"[skill-evolve] <{RUN_GAP_HOURS}h since last run — skipping.")
        return 0
    if not _acquire_lock():
        print("[skill-evolve] another run holds the lock — skipping.")
        return 0

    global _WORK_DIR
    wt_path       = None
    evolve_branch = ""
    base_ref      = ""
    base_sha      = ""

    def _return_home():
        global _WORK_DIR
        _WORK_DIR = VARYS_DIR
        if wt_path:
            _git(["worktree", "remove", "--force", str(wt_path)])
            _git(["worktree", "prune"])
        if evolve_branch:
            _git(["branch", "-D", evolve_branch])

    try:
        print(f"[skill-evolve] Starting at {started.isoformat()}")

        _refresh_trajectory()
        prompt = build_prompt()
        _git(["checkout", "--", "memory/trajectory.md"])

        base_ref, base_sha = _resolve_base()
        ts = started.strftime("%Y%m%d-%H%M%S")
        evolve_branch = f"skill-evolve/{ts}"
        WORKTREES_DIR.mkdir(parents=True, exist_ok=True)
        wt_candidate = WORKTREES_DIR / ts
        add = _git(["worktree", "add", str(wt_candidate), "-b", evolve_branch, base_ref])
        if add.returncode != 0:
            print(f"[skill-evolve] could not create worktree off {base_ref}: "
                  f"{add.stderr[:200]} — aborting.")
            evolve_branch = ""
            _return_home()
            _mark_run()
            return 0
        wt_path = wt_candidate
        _WORK_DIR = wt_path
        print(f"[skill-evolve] worktree {wt_path} on {evolve_branch} off {base_ref} ({base_sha[:8]})")

        semantic_judge = _load_semantic_judge()

        try:
            result = subprocess.run(
                ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt,
                 "--model", MODEL],
                cwd=str(_WORK_DIR), capture_output=True, text=True, timeout=900,
            )
        except subprocess.TimeoutExpired:
            print("[skill-evolve] agent timed out (900s) — discarding branch.")
            _return_home()
            _mark_run()
            return 0

        meta = _parse_agent_json(result.stdout)
        title = meta.get("title", "")
        if not title:
            print(f"[skill-evolve] no improvement this run: {meta.get('summary', '(no json)')}")
            _return_home()
            _mark_run()
            return 0

        changed = _changed_files(base_sha)
        if not changed:
            print(f"[skill-evolve] agent claimed '{title}' but changed no files — discarding.")
            _return_home()
            _mark_run()
            return 0

        print(f"[skill-evolve] proposal: {title}")
        print(f"[skill-evolve] changed: {', '.join(changed)}")

        # ── Gates (any failure → discard branch, log, DM) ──
        def _fail(gate_name: str, reason: str):
            print(f"[skill-evolve] GATE FAIL ({gate_name}): {reason}")
            _return_home()
            _log_failure(title, reason, gate_name)
            _dm_shoaib(f"🕷️ Skill evolution discarded — *{title}*\n"
                       f"{gate_name} gate: {reason}\nNo PR opened.")
            klog("skill-evolve", component="skill-evolve",
                 result="discarded", gate=gate_name, title=title)
            _mark_run()

        for gate_name, gate_fn in [("fence", gate_fence), ("content", gate_content)]:
            ok, reason = gate_fn(changed)
            if not ok:
                _fail(gate_name, reason)
                return 0

        diff = _git(["diff", base_sha]).stdout
        verdict = semantic_judge(diff)
        if verdict["verdict"] == "revert":
            _fail("semantic", verdict["reason"])
            return 0

        # ── All gates passed → commit on branch, push, open PR ──
        gates_line = "fence ✅ · content ✅ · semantic ✅"
        _git(["add", "--", SKILL_DIR_PREFIX])
        commit_msg = (
            f"skill-evolve: {title}\n\n{meta.get('summary', '')}\n\n"
            f"Driven by learning: {meta.get('learning', 'n/a')}\n"
            f"Test: {meta.get('test', 'n/a')}\n\n"
            f"🕷️ Autonomous skill evolution (gated: fence+content+semantic)\n"
            f"Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>")
        commit = _git(["commit", "--no-verify", "-m", commit_msg])
        if commit.returncode != 0:
            print(f"[skill-evolve] commit failed: {commit.stderr[:200]} — discarding.")
            _return_home()
            _mark_run()
            return 0

        slug_branch = f"skill-evolve/{started.strftime('%Y%m%d')}-{_slugify(title)}"
        if _git(["branch", "-m", slug_branch]).returncode == 0:
            evolve_branch = slug_branch
        new_sha = _head_sha()

        push = _git(["push", "-u", "origin", evolve_branch], timeout=120)
        if push.returncode != 0:
            print(f"[skill-evolve] push failed: {push.stderr[:200]}")
            _dm_shoaib(f"🕷️ Skill evolution committed but PUSH FAILED — *{title}*\n"
                       f"Branch `{evolve_branch}` exists locally only.\n{push.stderr[:200]}")
            evolve_branch = ""
            _return_home()
            _mark_run()
            return 0

        pr_body = (
            f"## 🕷️ Autonomous skill evolution\n\n"
            f"**What changed:** {meta.get('summary', '')}\n\n"
            f"**Driven by learning:** {meta.get('learning', 'n/a')}\n\n"
            f"**Test:** {meta.get('test', 'n/a')}\n\n"
            f"**Files:** {', '.join(meta.get('files', changed))}\n\n"
            f"**Gates passed:** {gates_line}\n\n"
            f"Branched off `{base_ref}`. Reviewed by you before merge — this is the "
            f"human gate.\n\n"
            f"🤖 Generated with [Claude Code](https://claude.com/claude-code)")
        pr_url = _open_pr(evolve_branch, base_ref, f"skill-evolve: {title}", pr_body)

        _log_success({**meta, "pr": pr_url, "branch": evolve_branch}, new_sha)
        evolve_branch = ""
        _return_home()

        _dm_shoaib(
            f"🕷️ *Evolved a skill* — {title}\n"
            f"{meta.get('summary', '')}\n"
            f"_Driven by:_ {meta.get('learning', 'n/a')}\n"
            f"_Files:_ {', '.join(meta.get('files', changed))}\n"
            f"_Gates:_ {gates_line}\n"
            + (f"_PR:_ {pr_url}" if pr_url else "_PR:_ (gh pr create failed — branch pushed)"))
        klog("skill-evolve", component="skill-evolve",
             result="pr-opened", title=title, sha=new_sha, pr=pr_url)
        print(f"[skill-evolve] PR OPENED — {title}\n  "
              f"{pr_url or '(branch pushed; PR creation failed)'}")
        _mark_run()
        return 0

    except Exception as e:
        klog_error("skill-evolve-main", e, component="skill-evolve", severity="ERROR")
        print(f"[skill-evolve] ERROR: {e}")
        try:
            _return_home()
        except Exception:
            pass
        return 1
    finally:
        dur = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        klog_cron("varys-skill-evolve", status="ok", duration_ms=dur)
        _release_lock()


if __name__ == "__main__":
    sys.exit(main())
