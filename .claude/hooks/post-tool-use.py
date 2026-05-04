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
    Sync vault file to MemPalace.

    Current: Logs the sync intent with wing/room mapping.
    TODO: Call MemPalace MCP upsert tool for actual semantic indexing.
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

        # TODO: Call MemPalace MCP tools:
        # mempalace_upsert(wing=wing, room=room, content=content, filepath=str(abs_path))

        return True
    except Exception as e:
        print(f"[post-tool-use] Error syncing {file_path}: {e}", file=sys.stderr)
        return False

def main():
    """Hook entry point."""
    # Read tool result from stdin (passed by Claude Code hook system)
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        hook_input = {}
    except Exception:
        hook_input = {}

    # Extract file path from tool result
    # Expected format varies by tool; handle Write/Edit tools
    file_path = None

    if "file_path" in hook_input:
        file_path = hook_input["file_path"]
    elif "path" in hook_input:
        file_path = hook_input["path"]
    else:
        # Silent exit if no file path found
        return

    if file_path:
        sync_to_mempalace(file_path)

if __name__ == "__main__":
    main()
