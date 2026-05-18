# Personal Agent v2

Kamal's personal AI agent. **Notion is the primary brain** — all context lives in Notion databases, queryable by filter. Slack is monitored automatically. Every session starts with a full briefing.

## Architecture (v2.1 — Notion-first)

```
Notion (brain)      → 6 databases: My PRs, Team People, Slack Inbox, Work Log, Projects, Harness
Slack (feed)        → slack-poller.py reads channels every 30min → writes to Notion Inbox
SessionStart hook   → queries Notion → briefs Claude with open PRs + inbox + last session
Stop hook           → writes Work Log entry to Notion
vault/              → legacy Obsidian (kept for history, no longer primary)
mempalace/          → legacy semantic index (kept as fallback)
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
