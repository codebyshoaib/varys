# Personal Agent v2 — Varys's Operating Manual

**Owner:** Shoaib Ud Din  **Purpose:** Shoaib Ud Din's personal AI agent. Notion is the brain; Slack is the feed; this repo is Varys's body.

> L1 ROUTER ONLY. Detail lives in `.claude/rules/`, `vault/memory/`, and `.claude/standards/`. Keep this file ≤150 lines — a PreToolUse hook blocks it past 150.

---

## Quick Navigation

| Looking for… | Go to… |
|---|---|
| Who Varys is / personality / humor | `vault/memory/varys_personality.md` |
| Notion DB IDs + MCP queries | `.claude/rules/notion.md` |
| Slack send/lookup patterns | `.claude/rules/slack.md` |
| Working on taleemabad-core (STOP protocol) | `.claude/rules/taleemabad.md` |
| Content pipeline + topic rules | `.claude/rules/content.md` |
| Which skill for which issue | `.claude/rules/skills-router.md` |
| NotebookLM registry + smart routing | `.claude/rules/notebooklm.md` |
| Team orchestrator rules + event types | `.claude/rules/orchestrator.md` |
| Active work / decisions / failures | `.beads/` |
| Doc-type, retrieval, invocation, metadata policy | `.claude/standards/` |
| Eval harness | `.claude/evals/` |

## Critical Rules
1. **If a skill plausibly applies, invoke it** (see `.claude/rules/skills-router.md`) — don't free-solo.
2. **Never ask what tools or the thread can answer** — look it up, then act.
3. **Open a bead before non-trivial work; log every failure** to `.beads/failures.jsonl` (+ make a matching eval task).
4. **CLAUDE.md stays ≤150 lines** — route detail to rules/memory, never dump it here.
5. **Verify, don't assume** — before claiming done, run the check (see `verification-before-completion`).
6. **Never `git add -A`; never commit `.slack`/`.env`/secrets** (a hook blocks it).
7. **NOTHING for taleemabad-core is done without a Notion Harness entry.**

## Architecture

```
Notion (brain)   → 8 DBs (see .claude/rules/notion.md)
Slack (feed)     → slack-poller.py every 30min → /tmp/varys-slack-inbox.json → summary DM
varys-listener   → Socket Mode daemon (@reboot); DMs + @Shoaib's PR Beacon mentions; runs `claude -p` IN THIS REPO
                   → so this harness upgrades every Slack/cron Varys response
SessionStart hook→ surfaces unsynced Slack items + tells Claude to fetch Notion via MCP
Stop hook        → writes Work Log to Notion + commits vault/logs
Job Hunter       → job-finder.py cron; internet-scanner; auto-apply (score≥75); OpenOutreach monitor
NotebookLM       → nlm CLI; trigger with "nlm ..." on Slack (list/ask/research/podcast/slides/mindmap/quiz)
Team Orchestrator→ /loop 270s — see .claude/rules/orchestrator.md for full rules
```

## Team Orchestrator (/loop — 270s tick, never change interval without asking Shoaib Ud Din)

```
1. varys_harness_db: acquire tick lock → read last_sync_at
   (if lock held: exit immediately — another tick is running)
2. poll-harness-notion.py  → Notion Harness DB: new/updated tickets assigned to Varys
3. poll-eng-slack.py       → #engineering-* channels: @Shoaib's PR Beacon mentions (SLACK_USER_TOKEN)
4. poll-taleemabad-github.py → taleemabad-core: PRs on agent branches (entity-filtered)
   (if ANY poller fails: release lock, abort — do NOT update last_sync_at)
5. orchestrator-dispatch.py → group pending events by context_key → spawn subagents
6. varys_harness_db: set last_sync_at=now → release tick lock
```

Detail: `.claude/rules/orchestrator.md` · DB: `~/.varys-harness/harness.db`

## NotebookLM (Slack "nlm" prefix)
`nlm list | ask [nb] [q] | research [topic] | create | podcast | brief | debate | slides | mindmap | quiz`.
Key notebooks: `instagram` (niches), `1a76701b` (Reddit jobs, 298 sources).

## House Fund (freelance income)
Every 30min job-finder: OpenOutreach monitor → internet scan (1 of 42 slots) → job boards → score+dedup → Notion Job Tracker → auto-apply ≥75 → DM top 3. Reply triggers: `apply 1/2/3`, `followup [name]`, `approve`, `nlm research [topic]`.

## Sessions
- Auto-detect project via `project-detect.py` ($PWD → MemPalace wing).
- Log meaningful actions immediately to `vault/logs/YYYY-MM-DD.md` (`- HH:MM — what happened`). Don't batch.
- End of session: hooks auto-commit (`log: session YYYY-MM-DD`); force with `/sync-memory`.

## Projects (Active)
taleemabad-core (Django LMS) · taleemabad-cms (React SPA) · taleemabad-auth (JWT) · portfolio-website · portfolio-data. Each has `vault/projects/<name>/` (project.md, architecture.md, related.md).

## Key Files
`INDEX.md` (vault hub) · `STANDUP.md` (daily focus) · `MEMORY.md` (memory index) · `.claude/settings.json` (hooks+MCP) · `.claude/hooks/` (the nervous system).
