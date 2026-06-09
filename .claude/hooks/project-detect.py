#!/usr/bin/env python3
"""
project-detect hook: Runs at session start (pre-session)

Detects current working directory, matches against known projects.
If match found: loads that project's wing in MemPalace.
Surfaces last 3 session summaries + related projects from related.md.
"""

import os
import re
import sys
import json
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from agent_config import cfg as _cfg_pd
except Exception:
    _cfg_pd = lambda k, d=None: d

def run_cmd(cmd: list[str], cwd: str = None) -> tuple[bool, str]:
    """Execute shell command; return (success, output)."""
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)

def detect_project(cwd: str) -> str | None:
    """
    Match current working directory to known project.
    Handles both direct paths and symlinks via resolve().

    Known projects — configure via ~/.agent-config.json or env vars.
    Add your own project paths under PROJECT_1_PATH, PROJECT_2_PATH, etc.
    - {{PROJECT_1_PATH}} → "my-project"
    - etc.
    """
    cwd_path = Path(cwd).resolve()

    _home = Path.home()
    _repo_root = Path(_cfg_pd("REPO_ROOT", str(_home / "Documents" / "free_work" / "personal-agent-v2")))
    projects = {
        # Add your own project paths here — override with env vars or ~/.agent-config.json
        # Example: Path(_cfg_pd("MY_PROJECT_PATH", str(_home / "Documents" / "my-project"))).resolve(): "my-project",
        Path(_cfg_pd("PROJECT_1_PATH", str(_home / "Documents" / "project-1"))).resolve(): "project-1",
        Path(_cfg_pd("PROJECT_2_PATH", str(_home / "Documents" / "project-2"))).resolve(): "project-2",
        Path(_cfg_pd("PORTFOLIO_WEBSITE_PATH", str(_home / "Documents" / "free_work" / "portfolio-website"))).resolve(): "portfolio-website",
        Path(_cfg_pd("PORTFOLIO_DATA_PATH", str(_home / "Documents" / "free_work" / "portfolio-data"))).resolve(): "portfolio-data",
        _repo_root.resolve(): "personal-agent-v2",
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

    Parses wikilinks: [[projects/name]] and [[projects/name | display text]]
    Returns list of project names.
    """
    related_file = workspace_root / "vault" / "projects" / project_name / "related.md"

    if not related_file.exists():
        return []

    try:
        content = related_file.read_text(encoding="utf-8")

        # Extract wikilinks: [[projects/name]] or [[projects/name | display text]]
        # Regex: \[\[projects/([a-z0-9\-]+)(?:\s*\|\s*[^\]]+)?\]\]
        pattern = r"\[\[projects/([a-z0-9\-]+)(?:\s*\|\s*[^\]]+)?\]\]"
        matches = re.findall(pattern, content)

        # Remove duplicates while preserving order
        seen = set()
        related = []
        for name in matches:
            if name not in seen:
                related.append(name)
                seen.add(name)

        return related
    except Exception as e:
        print(f"[project-detect] Error reading related.md: {e}", file=sys.stderr)
        return []

def get_project_info(workspace_root: Path, project_name: str) -> dict:
    """
    Load project metadata from project.md
    """
    project_file = workspace_root / "vault" / "projects" / project_name / "project.md"

    if not project_file.exists():
        return {"name": project_name}

    try:
        content = project_file.read_text(encoding="utf-8")
        # Extract title from YAML frontmatter
        if "---" in content:
            lines = content.split("\n")
            for line in lines[1:]:
                if line.startswith("name:"):
                    name = line.replace("name:", "").strip()
                    return {"name": name, "path": str(project_file.parent)}
        return {"name": project_name}
    except:
        return {"name": project_name}

def main():
    """Hook entry point."""
    workspace_root = Path(__file__).parent.parent.parent
    cwd = os.getcwd()

    project = detect_project(cwd)

    if project:
        # Get project info
        project_info = get_project_info(workspace_root, project)

        # Load related projects
        related = load_related_projects(workspace_root, project)

        # Build context for Claude
        context = {
            "project": project,
            "project_info": project_info,
            "related": related,
            "workspace_root": str(workspace_root),
        }

        print(f"[project-detect] Detected project: {project}", file=sys.stderr)
        print(f"[project-detect] Related projects: {', '.join(related) if related else 'none'}", file=sys.stderr)

        # Search MemPalace for project context
        workspace_root = Path(cwd).parents[1]  # Navigate to personal-agent-v2 root
        palace_path = workspace_root / "mempalace"

        # Search for project-specific files in MemPalace
        success, search_output = run_cmd(
            ["mempalace", "--palace", str(palace_path), "search", project],
            cwd=str(workspace_root)
        )

        if success:
            print(f"[project-detect] MemPalace context loaded: {project}", file=sys.stderr)
            if related:
                print(f"[project-detect] Related projects available: {', '.join(related)}", file=sys.stderr)
        else:
            print(f"[project-detect] MemPalace search note: {search_output[:100]}", file=sys.stderr)
    else:
        print(f"[project-detect] No project detected at: {cwd}", file=sys.stderr)
        print(f"[project-detect] Loading workspace context instead", file=sys.stderr)

    return 0

if __name__ == "__main__":
    sys.exit(main())
