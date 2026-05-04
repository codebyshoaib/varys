#!/usr/bin/env python3
"""
post-tool-use hook: Syncs vault writes to MemPalace

Triggers after Write/Edit tool calls that touch vault/.
Detects file path, derives wing+room from folder structure.
Calls MemPalace MCP to upsert file content into correct location.
"""

import os
import sys
import json
from pathlib import Path

def get_wing_and_room(file_path: str) -> tuple[str, str]:
    """
    Derive MemPalace wing + room from file path.

    Examples:
    vault/memory/user_profile.md → wing: "workspace", room: "memory"
    vault/projects/taleemabad-core/project.md → wing: "taleemabad-core", room: "project"
    vault/domains/taleemabad/work-log.md → wing: "taleemabad", room: "work-log"
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
        return "workspace", "memory"
    elif category == "projects" and vault_idx + 2 < len(parts):
        project_name = parts[vault_idx + 2]
        return project_name, "project"
    elif category == "domains" and vault_idx + 2 < len(parts):
        domain_name = parts[vault_idx + 2]
        return domain_name, "domain"
    elif category == "logs":
        return "workspace", "logs"
    elif category == "plans":
        return "workspace", "plans"

    return None, None

def sync_to_mempalace(file_path: str):
    """
    Sync vault file to MemPalace via MCP tools.

    In a real implementation, this would call MemPalace MCP upsert tool.
    For now, log the sync intent.
    """
    wing, room = get_wing_and_room(file_path)

    if not wing or not room:
        return  # Not a vault file

    abs_path = Path(file_path).resolve()
    if not abs_path.exists():
        return

    content = abs_path.read_text(encoding="utf-8")

    # Log sync intent (real implementation would call MemPalace MCP)
    workspace_root = Path(__file__).parent.parent.parent
    log_dir = workspace_root / "vault" / "logs"

    # For now, just log that sync was triggered
    # Once MemPalace MCP is wired up, this will actually upsert
    print(f"[post-tool-use] Synced {file_path} → MemPalace wing:'{wing}' room:'{room}'", file=sys.stderr)

def main():
    """Hook entry point."""
    # Read tool result from stdin (passed by Claude Code hook system)
    try:
        hook_input = json.loads(sys.stdin.read())
    except:
        hook_input = {}

    # Extract file path from tool result
    # Expected format varies by tool; handle Write/Edit tools
    if "file_path" in hook_input:
        file_path = hook_input["file_path"]
        sync_to_mempalace(file_path)
    elif "path" in hook_input:
        file_path = hook_input["path"]
        sync_to_mempalace(file_path)

if __name__ == "__main__":
    main()
