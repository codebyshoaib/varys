# Kamil Agent Public Repo Plan

**Goal:** Create a public GitHub repo `oyekamal/kamil-agent` that lets anyone build
their own Notion + Claude + Axiom orchestration agent — based on what Kamal built,
but stripped of Slack and personal details, with a clean setup wizard.

**What it includes:**
- SQLite harness DB (same schema as personal-agent-v2)
- Notion poller (ticket-based events)
- GitHub poller (PR events)
- Dispatcher (spawns Claude subagents per context_key)
- Brain DB (knowledge graph — the new layer)
- Setup wizard skill (/setup)
- Loop skill (/loop 270s)
- Clean README, .env.example, CLAUDE.md

**What it excludes:**
- Slack (removed per Kamal's request)
- Personal memory/vault files
- Personal Notion DB IDs
- Personal content pipeline
- Job finder, linkedin poster, etc.

**Inspired by:** orchestration-harness-v2 structure + Kamal's personal-agent-v2

---

## Repo structure

```
kamil-agent/
├── README.md                    ← star-worthy, shows video, explains concept
├── CLAUDE.md                    ← L1 router (≤150 lines)
├── CONTEXT.md                   ← domain glossary
├── .env.example                 ← all vars needed, with comments
├── .gitignore
├── harness/
│   ├── CLAUDE.md                ← tick sequence (L2)
│   ├── db/
│   │   ├── schema.sql           ← events, entities, sessions, links, brain tables
│   │   └── init.sh              ← creates harness.db
│   └── skills/
│       ├── setup.md             ← /setup wizard
│       ├── sync-state.md        ← tick lock + last_sync_at
│       ├── poll-notion.md       ← Notion ticket poller
│       ├── poll-github.md       ← GitHub PR poller
│       ├── dispatch.md          ← event dispatcher + subagent spawner
│       ├── brain-watcher.md     ← session end knowledge extraction
│       └── entity-registry.md  ← entity dedup + linking
├── .claude/
│   ├── settings.json            ← Stop hook wired to brain-watcher
│   └── agents/
│       ├── brain-agent.md
│       └── research-agent.md
└── docs/
    └── setup-guide.md           ← step-by-step for non-technical users
```

---

## Tasks

### Task 1: Create the repo locally + GitHub remote
### Task 2: Write CLAUDE.md + CONTEXT.md
### Task 3: Write harness/db/schema.sql + init.sh
### Task 4: Write .env.example + .gitignore
### Task 5: Write all 7 harness skills
### Task 6: Write .claude/settings.json + agents
### Task 7: Write README.md (the star-worthy one)
### Task 8: Write docs/setup-guide.md
### Task 9: Push to GitHub, verify public
