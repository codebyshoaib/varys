# Personal Agent v2

This is Kamal's personal assistant workspace v2. Clean rebuild with Obsidian + MemPalace hybrid memory, hook-driven architecture, auto-project context detection, and karpathy-skills discipline.

## Key Differences from v1

- **Obsidian + MemPalace hybrid**: Vault is human-readable source of truth; MemPalace indexes it for Claude's semantic retrieval
- **Auto-project detection**: `$PWD` → loads project wing automatically; no manual context switching
- **Hook-driven sync**: post-tool-use syncs writes to MemPalace; stop hook auto-commits and refreshes STANDUP.md
- **Zero missing memory files**: All 19 memory files exist and are linked from MEMORY.md
- **Inter-project graphs**: Projects declare relationships (taleemabad-core ↔ taleemabad-cms); Claude surfaces related context automatically
- **Karpathy-skills globally**: Surgical changes, simplicity-first, goal-driven execution — enforced everywhere

## Architecture

```
vault/              → Obsidian source of truth (you browse, edit, see graphs)
mempalace/          → Claude's semantic memory (auto-indexed by hooks)
.claude/hooks/      → Post-tool-use, stop, project-detect (the nervous system)
repos/              → Symlinks to actual project paths
```

## Auto-Start Behavior

Every session:
1. `project-detect.py` reads `$PWD` and loads that project's wing in MemPalace
2. If in a known project, surfaces last 3 session summaries + related projects
3. If not in a project, loads general workspace context

## Session Discipline

- Write to `vault/logs/YYYY-MM-DD.md` immediately after meaningful actions
- Hooks auto-commit at session end and update STANDUP.md
- Use `/morning-standup` for daily focus + carry-overs
- Use `/switch-project` to override auto-detect if working across projects

## Memory System

Memory index lives in MEMORY.md — every entry must have a corresponding file in `vault/memory/`:
- `user_profile.md` — Role, preferences, knowledge level
- `feedback_*.md` — Validated approaches, what to avoid
- `*_workplace.md`, `*_project.md`, `*_path.md` — Project context
- `collaborator_*.md`, `*_direct_report.md` — People tracking
- `*_integration.md` — Tool/API integration notes

### MemPalace Wings
- `workspace` — General personal-agent context
- `taleemabad` — Work domain: taleemabad-core, taleemabad-cms, taleemabad-auth
- `fitness`, `business`, `content`, `contacts` — Life domains
- `{project-name}` — Project-specific context when in that repo

## Projects (Active)

All projects must have a `vault/projects/<name>/` folder with:
- `project.md` — Path, GitHub URL, overview
- `architecture.md` — Tech stack, key patterns, decisions
- `related.md` — Wikilinks to sibling projects + shared concerns

### Current Projects
- taleemabad-core (Django backend, LMS)
- taleemabad-cms (React SPA for content management)
- taleemabad-auth (JWT auth middleware)
- portfolio-website (Static portfolio site)
- portfolio-data (Blog posts + project JSON)

## Karpathy-Skills

Installed globally as a Claude Code plugin. Enforces everywhere:
- **Think before coding** — Clarify assumptions; no silent context gaps
- **Simplicity first** — Minimal, focused solutions only
- **Surgical changes** — Only touch what's necessary
- **Goal-driven execution** — Verifiable success criteria; test before done

Per-project CLAUDE.md can override for specific needs:
- `taleemabad-core` → Strict TDD, migrations tested, no changes without tests
- `taleemabad-cms` → Component-first, type-check before commit
- `portfolio-website` → Exploratory OK, less rigid

## Logging Discipline

Every meaningful action → immediate log entry to `vault/logs/YYYY-MM-DD.md`:
```markdown
- HH:MM — [one line: what happened]
```

If file doesn't exist, create with:
```markdown
# Session Log — YYYY-MM-DD

## Updates
```

Then append entries. Do NOT batch writes to end of session.

## Harness (Backlog)

When Kamal has free time: build automation harness for taleemabad-core.
- Unit test runner
- auto-browser E2E suite
- One-prompt issue fixing: describe bug → test → verify
- Template for other projects

## End of Session

Always commit:
```bash
git add -A && git commit -m "log: session YYYY-MM-DD"
```

Hook auto-does this, but you can force with `/sync-memory` if needed.

## Key Files

- `CLAUDE.md` — This file, workspace config
- `INDEX.md` — Vault navigation hub
- `STANDUP.md` — Daily focus, carry-overs (auto-updated by stop hook)
- `MEMORY.md` — Real index of memory files
- `vault/` — Obsidian vault root
- `.claude/settings.json` — MCP server config
- `.claude/hooks/` — The nervous system
