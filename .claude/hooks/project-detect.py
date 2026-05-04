#!/usr/bin/env python3
"""
project-detect hook: Runs at session start (pre-session)

Detects current working directory, matches against known projects.
If match found: loads that project's wing in MemPalace.
Surfaces last 3 session summaries + related projects from related.md.
"""

import os
import sys
import json
from pathlib import Path

def detect_project(cwd: str) -> str | None:
    """
    Match current working directory to known project.

    Known projects:
    - /home/oye/Documents/taleemabad-core → "taleemabad-core"
    - /home/oye/Documents/free_work/personal-agent-v2/repos/taleemabad-cms → "taleemabad-cms"
    - etc.
    """
    cwd_path = Path(cwd).resolve()

    projects = {
        Path("/home/oye/Documents/taleemabad-core"): "taleemabad-core",
        Path("/home/oye/Documents/free_work/personal-agent/repos/taleemabad-cms"): "taleemabad-cms",
        Path("/home/oye/Documents/taleemabad-auth"): "taleemabad-auth",
        Path("/home/oye/Documents/free_work/portfolio-website"): "portfolio-website",
        Path("/home/oye/Documents/free_work/portfolio-data"): "portfolio-data",
        Path("/home/oye/Documents/free_work/personal-agent-v2"): "personal-agent-v2",
    }

    # Check if cwd is within a known project
    for project_path, project_name in projects.items():
        try:
            cwd_path.relative_to(project_path)
            return project_name  # Found match
        except ValueError:
            continue

    return None

def load_related_projects(workspace_root: Path, project_name: str) -> list[str]:
    """
    Read related.md for the project to find sibling projects.
    """
    related_file = workspace_root / "vault" / "projects" / project_name / "related.md"

    if not related_file.exists():
        return []

    try:
        content = related_file.read_text(encoding="utf-8")

        # Extract wikilinks: [[projects/name]]
        related = []
        for line in content.split("\n"):
            if "[[projects/" in line:
                # Extract project name from wikilink
                start = line.find("[[projects/") + len("[[projects/")
                end = line.find("]]", start)
                if start > 0 and end > start:
                    related_name = line[start:end].split("/")[0]
                    related.append(related_name)

        return related
    except Exception as e:
        print(f"[project-detect] Error reading related.md: {e}", file=sys.stderr)
        return []

def main():
    """Hook entry point."""
    workspace_root = Path(__file__).parent.parent.parent
    cwd = os.getcwd()

    project = detect_project(cwd)

    if project:
        print(f"[project-detect] Detected project: {project}", file=sys.stderr)

        # Load related projects
        related = load_related_projects(workspace_root, project)

        # Output context for Claude (would integrate with MemPalace MCP)
        context = {
            "project": project,
            "related": related,
        }

        # In a real implementation, would call MemPalace MCP to:
        # 1. Activate this project's wing
        # 2. Load last 3 session summaries
        # 3. Surface related projects context

        print(f"[project-detect] Context: {json.dumps(context)}", file=sys.stderr)
    else:
        print(f"[project-detect] No project detected; loading workspace context", file=sys.stderr)

    return 0

if __name__ == "__main__":
    sys.exit(main())
