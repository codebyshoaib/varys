#!/usr/bin/env python3
"""
stop hook: Runs at session end

Actions:
1. Git commit: git add -A && git commit -m "log: session YYYY-MM-DD"
2. Update STANDUP.md: read today's log, update carry-overs, clear completed
3. MemPalace sync: upsert all changed vault files from this session
"""

import subprocess
import sys
import re
from pathlib import Path
from datetime import datetime
import sys as _sys, time as _time
_sys.path.insert(0, "/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks")
try:
    import kamil_log as _k
except Exception:
    _k = None
try:
    from kamil_context import resolve_person, record_interaction, PersonNotFound, PersonAmbiguous
    _context_available = True
except Exception:
    _context_available = False

def run_cmd(cmd: list[str], cwd: str = None) -> tuple[bool, str]:
    """Execute shell command; return (success, output)."""
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)

def git_commit(workspace_root: Path) -> bool:
    """
    Stage and commit all changes with timestamp.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    message = f"log: session {today}"

    # Add all changes
    success, output = run_cmd(["git", "add", "-A"], cwd=str(workspace_root))
    if not success:
        print(f"[stop] Git add failed: {output}", file=sys.stderr)
        return False

    # Commit (allow empty commit if nothing changed)
    success, output = run_cmd(["git", "commit", "-m", message, "--allow-empty"], cwd=str(workspace_root))
    if not success:
        print(f"[stop] Git commit failed: {output}", file=sys.stderr)
        return False

    # Extract commit hash from output if successful
    match = re.search(r'\[master [a-f0-9]+\]', output)
    if match:
        print(f"[stop] Committed: {message} ({match.group()})", file=sys.stderr)
    else:
        print(f"[stop] Committed: {message}", file=sys.stderr)

    return True

def update_standup(workspace_root: Path) -> bool:
    """
    Read today's log, update STANDUP.md with carry-overs.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = workspace_root / "vault" / "logs" / f"{today}.md"
    standup_file = workspace_root / "STANDUP.md"

    if not log_file.exists():
        print(f"[stop] No log file for today ({today}); skipping STANDUP update", file=sys.stderr)
        return True

    try:
        # Read log entries
        log_content = log_file.read_text(encoding="utf-8")
        log_lines = log_content.split("\n")

        # Extract log entries (lines starting with "- HH:MM")
        log_entries = [line.strip() for line in log_lines if re.match(r'^-\s+\d{2}:\d{2}', line)]

        if log_entries:
            print(f"[stop] Read {len(log_entries)} log entries from today", file=sys.stderr)

        # Read current STANDUP
        standup_content = standup_file.read_text(encoding="utf-8")

        # Update timestamp in STANDUP
        updated_content = re.sub(
            r'\*\*Updated\*\*:\s+\d{4}-\d{2}-\d{2}',
            f"**Updated**: {today}",
            standup_content
        )

        # Write back
        standup_file.write_text(updated_content, encoding="utf-8")
        print(f"[stop] Updated STANDUP.md timestamp to {today}", file=sys.stderr)

        return True
    except Exception as e:
        print(f"[stop] Error updating STANDUP: {e}", file=sys.stderr)
        return False

def mempalace_sync(workspace_root: Path) -> bool:
    """
    Sync all vault files to MemPalace via CLI.
    Uses 'sweep' to catch any files missed by post-tool-use hooks.
    """
    try:
        vault_dir = workspace_root / "vault"
        palace_dir = workspace_root / "mempalace"

        if not vault_dir.exists():
            return True

        # Run mempalace sweep to catch any missed files
        success, output = run_cmd(
            ["mempalace", "--palace", str(palace_dir), "sweep", str(vault_dir)],
            cwd=str(workspace_root)
        )

        if success:
            print(f"[stop] MemPalace sweep completed", file=sys.stderr)
            return True
        else:
            print(f"[stop] MemPalace sweep warning: {output}", file=sys.stderr)
            return False

    except Exception as e:
        print(f"[stop] MemPalace sync error: {e}", file=sys.stderr)
        return False

_DECISION_KEYWORDS = ["decided", "agreed", "approved", "blocked", "will do", "confirmed", "done"]

def _is_meaningful(turn_text: str, person_ids: list) -> bool:
    t = turn_text.lower()
    return bool(person_ids) or any(kw in t for kw in _DECISION_KEYWORDS)

def _extract_persons(text: str) -> list:
    """Try to resolve every Title Case word sequence as a person name."""
    if not _context_available:
        return []
    import re
    candidates = re.findall(r'\b([A-Z][a-z]+(?: [A-Z][a-z]+)+)\b', text)
    persons, seen_ids = [], set()
    for name in candidates:
        try:
            p = resolve_person(name)
            if p.entity_id not in seen_ids:
                persons.append(p)
                seen_ids.add(p.entity_id)
        except (PersonNotFound, PersonAmbiguous):
            pass
    return persons

def log_session_interactions(workspace_root: Path, session_id: str) -> None:
    """
    Read today's log, extract meaningful turns involving named people,
    and record each via record_interaction().
    """
    if not _context_available:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = workspace_root / "vault" / "logs" / f"{today}.md"
    if not log_file.exists():
        return
    try:
        lines = log_file.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        print(f"[stop] log_session_interactions read error: {e}", file=sys.stderr)
        return
    for turn_index, line in enumerate(lines):
        if not line.strip():
            continue
        persons = _extract_persons(line)
        if not _is_meaningful(line, persons):
            continue
        for person in persons:
            try:
                record_interaction(
                    person_id=person.entity_id,
                    source='claude_session',
                    external_id=f"{session_id}_{turn_index:04d}",
                    raw=line,
                    summary=line,
                    open_items="[]",
                )
            except Exception as e:
                print(f"[stop] record_interaction failed for {person.name}: {e}", file=sys.stderr)


def _seed_session_to_brain(workspace_root: Path) -> None:
    """
    Extract what was built/decided this session and seed into brain.db.
    Non-fatal — never blocks the stop hook.
    """
    import json as _json
    today    = datetime.now().strftime("%Y-%m-%d")
    log_path = workspace_root / "vault" / "logs" / f"{today}.md"
    if not log_path.exists():
        print("[stop] No session log — skipping brain seed", file=sys.stderr)
        return

    log_text = log_path.read_text(encoding="utf-8")[-3000:]
    if len(log_text) < 100:
        print("[stop] Session log too short — skipping brain seed", file=sys.stderr)
        return

    prompt = (
        "From this engineering session log, extract what was built or decided.\n"
        "Output ONLY valid JSON with these keys:\n"
        "  key_insights: list of up to 3 concrete patterns or decisions (max 20 words each)\n"
        "  lessons_learned: list of up to 2 lessons for future Kamil (what to do / avoid)\n"
        "  tools_mentioned: list of tools/scripts/files that were created or significantly changed\n"
        "  one_line_summary: single sentence, the most important outcome of this session\n\n"
        f"Session log:\n{log_text}\n\nJSON only."
    )
    try:
        r = run_cmd(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt],
            cwd=str(workspace_root),
        )
        # run_cmd returns (success, output)
        raw   = r[1].strip()
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start < 0 or end <= start:
            print("[stop] Brain seed: Claude returned no JSON", file=sys.stderr)
            return
        structured = _json.loads(raw[start:end])
    except Exception as e:
        print(f"[stop] Brain seed prompt failed (non-fatal): {e}", file=sys.stderr)
        return

    try:
        import importlib.util as _ilu
        seed_path = workspace_root / ".claude" / "hooks" / "brain_seed_from_content.py"
        spec = _ilu.spec_from_file_location("brain_seed", str(seed_path))
        mod  = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod._write_to_brain(
            topic      = f"Engineering session {today}",
            track      = "tech",
            nb_id      = "session-stop",
            structured = structured,
            session_id = "",
            source     = "session_stop",
        )
        print("[stop] Session decisions seeded to brain.db", file=sys.stderr)
    except Exception as e:
        print(f"[stop] Brain seed write failed (non-fatal): {e}", file=sys.stderr)


def main():
    """Hook entry point."""
    workspace_root = Path(__file__).parent.parent.parent

    print("[stop] Running stop hook...", file=sys.stderr)

    # 0. Seed session decisions to brain.db (non-fatal)
    _seed_session_to_brain(workspace_root)

    # 1. Commit changes
    if not git_commit(workspace_root):
        print("[stop] Git commit failed; continuing with other steps", file=sys.stderr)
        # Don't exit; try other steps

    # Log meaningful session interactions to per-person memory
    import uuid as _uuid
    session_id = str(_uuid.uuid4())[:8]
    log_session_interactions(workspace_root, session_id)

    # 2. Update STANDUP.md
    if not update_standup(workspace_root):
        print("[stop] STANDUP update failed; continuing", file=sys.stderr)
        # Don't exit

    # 3. MemPalace sync
    if not mempalace_sync(workspace_root):
        print("[stop] MemPalace sync failed; continuing", file=sys.stderr)
        # Don't exit

    # 4. Update notion-map.md with session activity summary
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = workspace_root / "vault" / "logs" / f"{today}.md"
        if log_file.exists():
            lines = [l.strip() for l in log_file.read_text().splitlines()
                     if l.strip().startswith("-")]
            summary = " | ".join(lines[-3:]) if lines else "session ended"
        else:
            summary = "session ended"
        run_cmd(
            ["python3",
             str(workspace_root / ".claude" / "hooks" / "notion-map-updater.py"),
             "--mode", "session", "--summary", summary[:200]],
            cwd=str(workspace_root)
        )
        print("[stop] notion-map.md updated", file=sys.stderr)
    except Exception as e:
        print(f"[stop] notion-map update failed (non-fatal): {e}", file=sys.stderr)

    # 5. Brain watcher — wire session knowledge into brain.db
    try:
        brain_watcher = workspace_root / ".claude" / "hooks" / "kamil-brain-watcher.py"
        if brain_watcher.exists():
            success, output = run_cmd(
                ["python3", str(brain_watcher)],
                cwd=str(workspace_root)
            )
            if not success:
                print(f"[stop] Brain watcher warning: {output[:200]}", file=sys.stderr)
            else:
                print("[stop] Brain watcher completed", file=sys.stderr)
    except Exception as e:
        print(f"[stop] Brain watcher error (non-fatal): {e}", file=sys.stderr)

    print("[stop] Stop hook completed", file=sys.stderr)
    return 0

if __name__ == "__main__":
    _t0 = _time.time()
    try:
        rc = main()
        if _k: _k.klog_cron("stop", status="ok", duration_ms=(_time.time()-_t0)*1000)
        sys.exit(rc)
    except Exception as _e:
        if _k: _k.klog_error("stop-main", _e, component="stop", severity="ERROR")
        raise
