---
name: Graphify Integration
description: Knowledge graph for context management across projects
type: reference
---

# Graphify Integration — Context Graph

## What It Does

Graphify automatically indexes the vault and creates a knowledge graph showing:
- Relationships between projects (taleemabad-core ↔ taleemabad-cms)
- People and their roles (Anam Masood → Taleemabad collaborator)
- Domains and project assignments (work → taleemabad, content → portfolio)
- Memory references and their connections

## Auto-Indexing

When you run `/morning-standup`, Graphify:
1. Scans `vault/projects/*/related.md` for wikilinks
2. Scans `vault/memory/*.md` for cross-references
3. Indexes all people, projects, and domains
4. Shows related memories as suggestions

Example output:
```
You're in taleemabad-core
Related: [[taleemabad-cms]] (shares S3 bucket), [[taleemabad-auth]] (JWT validation)
Recent context: training LMS system, NIETE integration
```

## Benefits

- **Never lose context** — Related projects surface automatically
- **See the graph** — Obsidian wikilinks show connections visually
- **Smart suggestions** — When in a project, Claude suggests related work
- **Memory discovery** — Find forgotten context by exploring the graph

## How It Works

Graphify reads:
- Wikilinks: `[[path/to/file]]` in any markdown
- Frontmatter: `type`, `name`, `description` in YAML headers
- File paths: Treats folder structure as graph nodes (e.g., `projects/taleemabad-core`)

Output:
- Text suggestions (shown in morning standup)
- Graph HTML (can be viewed in browser, but not required)
- Relationships: Stored in MemPalace edges for semantic retrieval

## Configuration

Graphify is built into personal-agent-v2 automatically:
- No additional setup required
- Respects all wikilinks in vault/
- Auto-updates as you add/edit memory files

## Related

See [[vault/memory/project_workspace]] for how this integrates into the overall system.
