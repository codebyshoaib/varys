---
name: Personal Agent Workspace
description: This workspace and its purpose
type: project
---

# personal-agent-v2 — Workspace Purpose

## What This Is
Your personal operating system for life and work. A unified context system that:
- Tracks all projects and their interconnections
- Manages memory so Claude never loses context
- Automates workflows (commits, memory sync, email handling)
- Enforces coding discipline (Karpathy-skills)
- Provides daily focus and carry-over tracking

## Core Components

### Memory System (Obsidian + MemPalace)
- `vault/` — Human-readable Obsidian vault (you browse, edit)
- `mempalace/` — Claude's semantic memory (auto-indexed)
- Hooks keep them in sync automatically

### Domain Tracking
- **Work** — taleemabad, projects, incidents, contacts
- **Fitness** — Goals, activity log
- **Business** — Ideas, experiments
- **Content** — Blog pipeline, publications
- **Contacts** — Email tracker, people relationships

### Project Context
- Each active project has a folder in `vault/projects/<name>/`
- Includes: overview, architecture, decisions, relationships to other projects
- Inter-project graph allows Claude to surface related context automatically

### Daily Workflows
- `/morning-standup` — Today's focus + carry-overs
- `vault/logs/YYYY-MM-DD.md` — Session logs (append immediately)
- Hooks auto-commit and update STANDUP.md at session end

## Key Goals for v2

1. **Stop losing context** — MemPalace + hooks remember everything across sessions
2. **Reduce context-switching** — Auto-detect project; surface related work
3. **Enforce discipline** — Karpathy-skills prevent scope creep
4. **Automate boilerplate** — Commits, email tracking, memory sync happen automatically
5. **See the graph** — Obsidian wikilinks + MemPalace relationships show project connections

## Public Blueprint

This workspace is documented as a public blueprint:
- **Repo**: `github.com/Orenda-Project/personal-agent-workspace`
- **Purpose**: Template for others to build similar context systems
- **Updates**: As you improve v2, consider documenting patterns in the blueprint
