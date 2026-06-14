#!/usr/bin/env python3
"""
post-tool-use hook: Syncs vault writes to MemPalace

Triggers after Write/Edit tool calls that touch vault/.
Detects file path, derives wing+room from folder structure.
Calls MemPalace MCP to upsert file content into correct location.

Currently logs sync intent. Full MemPalace MCP integration pending.
"""

import os
import sys
import json
import re
import subprocess
from pathlib import Path

def get_wing_and_room(file_path: str) -> tuple[str | None, str | None]:
    """
    Derive MemPalace wing + room from vault file path.

    Wing: High-level context (project, domain, or workspace)
    Room: Subcategory within the wing

    Examples:
    vault/memory/user_profile.md
        → wing: "workspace", room: "memory"

    vault/projects/taleemabad-core/project.md
        → wing: "taleemabad-core", room: "project"

    vault/projects/taleemabad-core/architecture.md
        → wing: "taleemabad-core", room: "architecture"

    vault/domains/taleemabad/work-log.md
        → wing: "taleemabad", room: "work-log"

    vault/logs/2026-05-04.md
        → wing: "workspace", room: "logs"

    vault/plans/strategy.md
        → wing: "workspace", room: "plans"
    """
    path = Path(file_path)
    parts = path.parts

    if "vault" not in parts:
        return None, None  # Not in vault, skip

    vault_idx = parts.index("vault")
    if vault_idx + 1 >= len(parts):
        return None, None

    category = parts[vault_idx + 1]  # memory, projects, domains, logs, plans

    if category == "memory":
        # All memory files go to "workspace" wing
        return "workspace", "memory"

    elif category == "projects" and vault_idx + 2 < len(parts):
        # vault/projects/PROJECT_NAME/... → wing: "PROJECT_NAME"
        project_name = parts[vault_idx + 2]
        # Room is the file type (project, architecture, related, decisions, etc.)
        file_stem = path.stem  # "project", "architecture", "decisions", etc.
        room = file_stem if file_stem else "project"
        return project_name, room

    elif category == "domains" and vault_idx + 2 < len(parts):
        # vault/domains/DOMAIN_NAME/... → wing: "DOMAIN_NAME", room: "domain"
        domain_name = parts[vault_idx + 2]
        file_stem = path.stem  # "work-log", "incidents", "goals", etc.
        room = file_stem if file_stem else "domain"
        return domain_name, room

    elif category == "logs":
        # All logs go to "workspace" wing
        file_stem = path.stem  # Date like "2026-05-04"
        return "workspace", f"logs/{file_stem}"

    elif category == "plans":
        # All plans go to "workspace" wing
        file_stem = path.stem
        room = file_stem if file_stem else "plans"
        return "workspace", f"plans/{room}"

    return None, None

def run_cmd(cmd: list[str], cwd: str = None) -> tuple[bool, str]:
    """Execute shell command; return (success, output)."""
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)

def get_file_summary(file_path: str, max_lines: int = 10) -> str:
    """
    Get a brief summary of file content (first N lines + metadata).
    Used for logging what was synced.
    """
    try:
        abs_path = Path(file_path).resolve()
        if not abs_path.exists():
            return "(file not found)"

        content = abs_path.read_text(encoding="utf-8", errors="ignore")
        lines = content.split("\n")[:max_lines]
        summary = "\n".join(lines)

        if len(content.split("\n")) > max_lines:
            summary += f"\n... ({len(content.split('\n')) - max_lines} more lines)"

        return summary
    except Exception as e:
        return f"(error reading file: {e})"

def sync_to_mempalace(file_path: str) -> bool:
    """
    Sync vault file to MemPalace via CLI.

    Calls: mempalace mine vault to re-index all vault files.
    This is efficient because mempalace is idempotent (only updates changed files).
    """
    wing, room = get_wing_and_room(file_path)

    if not wing or not room:
        return False  # Not a vault file

    abs_path = Path(file_path).resolve()
    if not abs_path.exists():
        print(f"[post-tool-use] File not found: {file_path}", file=sys.stderr)
        return False

    try:
        content = abs_path.read_text(encoding="utf-8")
        size_kb = len(content) / 1024

        # Log sync intent
        print(f"[post-tool-use] Syncing vault file", file=sys.stderr)
        print(f"  File: {file_path}", file=sys.stderr)
        print(f"  Wing: '{wing}' | Room: '{room}'", file=sys.stderr)
        print(f"  Size: {size_kb:.1f} KB", file=sys.stderr)

        # Call MemPalace CLI to mine vault (idempotent, only updates changed files)
        workspace_root = Path(__file__).parent.parent.parent
        palace_path = workspace_root / "mempalace"
        vault_path = workspace_root / "vault"

        success, output = run_cmd(
            ["mempalace", "--palace", str(palace_path), "mine", str(vault_path)],
            cwd=str(workspace_root)
        )

        if success:
            print(f"[post-tool-use] Indexed to MemPalace: {wing}/{room}", file=sys.stderr)
            return True
        else:
            print(f"[post-tool-use] MemPalace indexing warning: {output}", file=sys.stderr)
            return False

    except Exception as e:
        print(f"[post-tool-use] Error syncing {file_path}: {e}", file=sys.stderr)
        return False

ERROR_LOG = Path("/tmp/varys-tool-errors.log")

def log_tool_error(tool_name: str, error: str, input_data: dict):
    """Write tool errors to a file the self-healer monitors."""
    ts = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "ts": ts,
        "tool": tool_name,
        "error": error[:500],
        "input": str(input_data)[:300],
    }
    with open(ERROR_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def main():
    """Hook entry point."""
    # Read tool result from stdin (passed by Claude Code hook system)
    try:
        raw = sys.stdin.read()
        hook_input = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        hook_input = {}
    except Exception:
        hook_input = {}

    # Detect tool errors and log them for self-healer
    tool_name = hook_input.get("tool_name", "")
    tool_result = hook_input.get("tool_result", {})
    if isinstance(tool_result, dict):
        error = tool_result.get("error") or tool_result.get("stderr", "")
        if error and len(str(error).strip()) > 5:
            log_tool_error(tool_name, str(error), hook_input.get("tool_input", {}))

    # Extract file path for MemPalace sync (Write/Edit tools)
    tool_input = hook_input.get("tool_input", hook_input)
    file_path = tool_input.get("file_path") or tool_input.get("path")

    if file_path:
        sync_to_mempalace(file_path)

if __name__ == "__main__":
    main()
