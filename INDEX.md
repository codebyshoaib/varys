# Personal Agent v2 — Navigation Hub

## Quick Start
- **Daily**: Open Obsidian, check [[STANDUP]] for today's focus and carry-overs
- **Each action**: Log to [[vault/logs/YYYY-MM-DD]]
- **Each session**: Hook auto-commits at end; verify `/morning-standup` for next session context
- **Working in a project**: Hook auto-loads context; use `/switch-project` if moving between repos

## Memory & Context
- [[MEMORY]] — Index of all 19 memory files
- [[vault/memory/user_profile]] — You: role, preferences, knowledge
- [[vault/memory/feedback_coding]] — Validated coding patterns
- [[vault/memory/taleemabad_workplace]] — Your employer & work context

## Projects (Active)
All have `architecture.md`, `decisions.md`, `related.md`:
- [[vault/projects/taleemabad-core]] — Django LMS backend
- [[vault/projects/taleemabad-cms]] — React SPA content manager
- [[vault/projects/taleemabad-auth]] — JWT auth middleware
- [[vault/projects/portfolio-website]] — Static portfolio site
- [[vault/projects/portfolio-data]] — Blog JSON + project data

## Domains (Life/Work Tracking)
- [[vault/domains/taleemabad]] — Work-log, incidents, contacts
- [[vault/domains/fitness]] — Goals, activity log
- [[vault/domains/business]] — Ideas, experiments, log
- [[vault/domains/content]] — Blog pipeline, content log
- [[vault/domains/contacts]] — Email tracker, people files

## Daily Workflows
- **Morning**: `/morning-standup` — shows today's focus + carry-overs
- **Throughout**: `/sync-memory` — force re-index vault to MemPalace (if needed)
- **When switching projects**: `/switch-project <name>` — override auto-detect
- **End of session**: Hook auto-commits + updates STANDUP.md

## Tools & Integrations
- **MemPalace** — Semantic memory server (MCP); 29 tools for memory ops
- **auto-browser** — Browser automation (MCP); E2E testing, web scraping
- **karpathy-skills** — Behavioral discipline plugin; installed globally
- **Obsidian** — Vault editor; wikilinks for graph navigation

## Hooks (Automatic)
- `post-tool-use.py` — Syncs `vault/` writes to MemPalace
- `stop.py` — Commits vault, updates STANDUP.md, full MemPalace sync
- `project-detect.py` — `$PWD` → loads project wing on session start

## Harness (Backlog)
- [[vault/harness/taleemabad-core]] — Automation harness for core (future)
- Templates in `harness/_template/` for other projects

---

**Everything in `vault/` is wikilinked and Obsidian-navigable. Use the graph view to explore relationships.**
