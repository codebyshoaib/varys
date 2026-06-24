#!/usr/bin/env python3
"""
varys-synthesize-learnings.py — Daily synthesis of Varys's learning archives.

Reads memory/learnings.jsonl and memory/slack_learnings.jsonl (append-only archives,
never compressed), applies time-weighted compression via claude -p, and writes:
  memory/active_learnings.md
  memory/active_slack_learnings.md

These files are loaded into every session via session-start.py so Varys enters
every conversation with accumulated self-knowledge.

Compression tiers (matching yoyo-evolve exactly):
  Recent (last 2 weeks) → full markdown entry
  Medium (2–8 weeks)   → 1–2 sentences per entry
  Old (8+ weeks)       → grouped by theme into Wisdom summaries

Cron: 0 12 * * * cd ~/varys && python3 .claude/hooks/varys-synthesize-learnings.py >> /tmp/varys-synthesize.log 2>&1
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from varys_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

VARYS_DIR   = Path(__file__).parent.parent.parent
MEMORY_DIR  = VARYS_DIR / "memory"
LEARNINGS   = MEMORY_DIR / "learnings.jsonl"
SLACK_L     = MEMORY_DIR / "slack_learnings.jsonl"
ACTIVE_L    = MEMORY_DIR / "active_learnings.md"
ACTIVE_SL   = MEMORY_DIR / "active_slack_learnings.md"
MODEL       = "claude-haiku-4-5-20251001"


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text().splitlines() if line.strip())


def _backup(path: Path) -> Path | None:
    bak = path.with_suffix(".md.bak")
    if path.exists():
        bak.write_text(path.read_text())
        return bak
    return None


def _restore(path: Path, bak: Path | None) -> None:
    if bak and bak.exists():
        path.write_text(bak.read_text())
        print(f"  restored {path.name} from backup")
    else:
        path.unlink(missing_ok=True)
        print(f"  no backup — removed potentially corrupt {path.name}")


def _cleanup_backup(bak: Path | None) -> None:
    if bak:
        bak.unlink(missing_ok=True)


def _synthesize(archive_path: Path, out_path: Path, kind: str) -> bool:
    """Run claude -p to synthesize one archive into its active file. Returns success."""
    archive_content = archive_path.read_text().strip() if archive_path.exists() else ""
    if not archive_content:
        # Write a placeholder instead of running the LLM
        if kind == "learnings":
            out_path.write_text("# Active Learnings\n\nSelf-reflection — what Varys has learned about how it works, what it values, and how it's growing.\n\n*(No entries yet)*\n")
        else:
            out_path.write_text("# Active Slack Learnings\n\nWhat Varys has learned about Shoaib and their working relationship from Slack interactions.\n\n*(No entries yet)*\n")
        return True

    if kind == "learnings":
        header = "# Active Learnings\n\nSelf-reflection — what Varys has learned about how it works, what it values, and how it's growing."
        instruction = """You are synthesizing Varys's learning archive into an active context file.

Apply time-weighted compression tiers:
- **Recent (last 2 weeks):** Render each entry as full markdown:
  ## Lesson: {title}
  **Session:** {session} | **Date:** {date} | **Source:** {source}
  **Context:** {context}
  {takeaway}
- **Medium (2-8 weeks old):** Condense each entry to 1-2 sentences under a bold title
- **Old (8+ weeks):** Group entries by theme into ## Wisdom: [theme] summaries (2-3 sentences per group)

Keep total under ~200 lines. Only keep insights that are genuinely novel and actionable — skip anything that would not change future behavior. Quality beats quantity.

Start your output with exactly:
# Active Learnings

Self-reflection — what Varys has learned about how it works, what it values, and how it's growing.

Then the content. Write nothing else — output only the markdown file content."""
    else:
        header = "# Active Slack Learnings\n\nWhat Varys has learned about Shoaib and their working relationship from Slack interactions."
        instruction = """You are synthesizing Varys's Slack interaction learning archive into an active context file.

Apply time-weighted compression tiers:
- **Recent (last 2 weeks):** Render each entry as a full bullet with metadata (who, date, insight)
- **Medium (2-8 weeks old):** Keep insight only, drop metadata
- **Old (8+ weeks):** Group by theme into ## Wisdom: [theme] summaries (2-3 sentences per group)

Keep total under ~100 lines.

Start your output with exactly:
# Active Slack Learnings

What Varys has learned about Shoaib and their working relationship from Slack interactions.

Then the content. Write nothing else — output only the markdown file content."""

    prompt = f"""{instruction}

Archive ({kind}):
{archive_content}
"""

    bak = _backup(out_path)
    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt,
             "--model", MODEL],
            capture_output=True, text=True, timeout=180,
            cwd=str(VARYS_DIR),
        )
        if result.returncode != 0:
            print(f"  claude -p returned {result.returncode}: {result.stderr[:200]}")
            _restore(out_path, bak)
            return False

        output = result.stdout.strip()
        if not output or "# Active" not in output:
            print(f"  synthesis output malformed (no header found)")
            _restore(out_path, bak)
            return False

        out_path.write_text(output + "\n")
        _cleanup_backup(bak)
        print(f"  wrote {out_path.name} ({len(output.splitlines())} lines)")
        return True

    except subprocess.TimeoutExpired:
        print(f"  synthesis timed out after 180s")
        _restore(out_path, bak)
        return False
    except Exception as e:
        print(f"  synthesis failed: {e}")
        _restore(out_path, bak)
        return False


def _git_commit_if_changed() -> None:
    changed = subprocess.run(
        ["git", "diff", "--quiet",
         "memory/active_learnings.md", "memory/active_slack_learnings.md"],
        cwd=str(VARYS_DIR),
    ).returncode != 0
    if not changed:
        print("No changes to active context files.")
        return
    subprocess.run(
        ["git", "add", "memory/active_learnings.md", "memory/active_slack_learnings.md"],
        cwd=str(VARYS_DIR), check=False,
    )
    subprocess.run(
        ["git", "commit", "--no-verify", "-m", "synthesize: regenerate active memory context"],
        cwd=str(VARYS_DIR), check=False,
    )
    print("Committed active context files.")


def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    print(f"[varys-synthesize] Starting at {now}")

    learnings_count = _count_lines(LEARNINGS)
    slack_count     = _count_lines(SLACK_L)
    print(f"  learnings.jsonl: {learnings_count} entries")
    print(f"  slack_learnings.jsonl: {slack_count} entries")

    ok_l  = _synthesize(LEARNINGS, ACTIVE_L,  "learnings")
    ok_sl = _synthesize(SLACK_L,   ACTIVE_SL, "slack")

    _git_commit_if_changed()

    status = "ok" if (ok_l and ok_sl) else "partial"
    try:
        from varys_log import klog_cron as _klog_cron
        _klog_cron("varys-synthesize-learnings", status=status, duration_ms=0,
                   learnings=learnings_count, slack=slack_count)
    except Exception:
        pass

    print(f"[varys-synthesize] Done. learnings={ok_l} slack={ok_sl}")
    return 0 if (ok_l and ok_sl) else 1


if __name__ == "__main__":
    sys.exit(main())
