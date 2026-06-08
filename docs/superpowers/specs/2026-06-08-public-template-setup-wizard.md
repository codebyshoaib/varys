# Public Template + /setup Wizard — Design Spec
**Date:** 2026-06-08
**Owner:** Kamal
**Status:** Approved for implementation planning

---

## 1. Problem

Every user-specific value (Notion DB IDs, Slack user ID, agent name, absolute paths) is
hardcoded across 40+ Python hook files. A user who clones the repo immediately hits your
databases, your Slack workspace, and your identity. The repo is not reusable without
manually editing dozens of files.

**Root cause:** No central config. Each hook reads its own hardcoded constants.

---

## 2. Solution in One Sentence

One config file as the single source of truth, one `/setup` slash command that creates
it conversationally, and a thin `agent_config.py` loader every hook imports.

---

## 3. Target User

**Anyone at all** — non-technical users included. Setup must be almost entirely
conversational. The AI handles every technical step (DB creation, file writing,
config generation). The user answers 6 questions and types things.

---

## 4. Architecture

```
User clones repo → opens Claude Code in folder → types /setup
    ↓
.claude/commands/setup.md (the wizard — a Claude slash command)
    ↓
Wizard collects: name, agent name, Notion token, Slack details (optional)
    ↓
Wizard creates Notion DBs via API automatically
    ↓
Writes: ~/.agent-config.json  (non-secret IDs + names)
Writes: ~/.claude/hooks/.notion  (NOTION_API_KEY secret)
Writes: ~/.claude/hooks/.slack   (BOT_TOKEN secret, if Slack chosen)
    ↓
Personalizes CLAUDE.md (replaces {{AGENT_NAME}}/{{USER_NAME}})
    ↓
Verifies: test Notion write + read
    ↓
"✅ [AGENT_NAME] is ready. Start a new Claude session to begin."
```

All hooks import `agent_config.py` → reads `~/.agent-config.json` →
returns the right value for this user. No hook reads hardcoded IDs anymore.

---

## 5. The /setup Wizard — Full Conversation Flow

File: `.claude/commands/setup.md`

The wizard is idempotent — running `/setup` again reconfigures from scratch.

### Step 1 — Welcome
```
Hi! I'm going to set up your personal AI agent. I'll ask you 6 questions,
then handle everything else automatically. Takes about 5 minutes.

Let's start — what's your name?
```

### Step 2 — Collect answers (one at a time, in order)

| # | Question | Config key | Notes |
|---|---|---|---|
| 1 | "What's your name?" | `USER_NAME` | First name fine |
| 2 | "What do you want to call your agent?" | `AGENT_NAME` | e.g. Aria, Max, Nova |
| 3 | "Paste your Notion API token. [How to get one →](https://www.notion.so/my-integrations)" | `NOTION_API_KEY` → `.notion` file | Secret — never stored in config |
| 4 | "Do you want Slack integration? (yes/no)" | `SLACK_ENABLED` | If no → skip Q5-Q6 |
| 5 | "What's your Slack workspace URL? (e.g. my-company.slack.com)" | `SLACK_WORKSPACE` | Only if Q4=yes |
| 6 | "Paste your Slack bot token (starts with xoxb-). [How to create a Slack app →]" | `SLACK_BOT_TOKEN` → `.slack` file | Secret — never stored in config |

After collecting answers, wizard says:
```
Got it. Creating your agent now — this takes about 30 seconds.
```

### Step 3 — Automated actions (wizard does all of this, user watches)

```
[1/5] Creating Notion database: "[AGENT_NAME] Harness" ✓
[2/5] Creating Notion database: "[AGENT_NAME] Work Log" ✓
[3/5] Creating Notion database: "[AGENT_NAME] Inbox" ✓  (skipped if no Slack)
[4/5] Writing config files ✓
[5/5] Personalizing your agent identity ✓
```

### Step 4 — Verification

Wizard writes a test entry to the Work Log DB, reads it back, deletes it.

```
Testing connection... ✅ Notion connected
✅ [AGENT_NAME] is ready.

Start a new Claude session in this folder to begin talking to [AGENT_NAME].
Your Notion workspace now has 2 new databases under a page called "[AGENT_NAME] Brain".
```

If verification fails:
```
❌ Notion connection failed. Let's check your token.
[troubleshooting steps]
Type /setup to try again.
```

---

## 6. Config Files

### ~/.agent-config.json (non-secrets, created by wizard)

```json
{
  "AGENT_NAME": "Aria",
  "USER_NAME": "Sarah",
  "USER_SLACK_ID": "",
  "SLACK_WORKSPACE": "",
  "SLACK_ENABLED": false,
  "NOTION_HARNESS_DB_ID": "<created-by-wizard>",
  "NOTION_WORK_LOG_DB_ID": "<created-by-wizard>",
  "NOTION_INBOX_DB_ID": "<created-by-wizard-or-empty>",
  "REPO_ROOT": "/home/sarah/personal-agent",
  "SETUP_COMPLETED_AT": "2026-06-08T10:30:00"
}
```

**Never committed to git.** Added to `.gitignore`.

### ~/.claude/hooks/.notion (secret, created by wizard)

```
NOTION_API_KEY=secret_abc123...
```

### ~/.claude/hooks/.slack (secret, created by wizard, only if Slack enabled)

```
BOT_TOKEN=xoxb-abc123...
SLACK_USER_TOKEN=xoxp-abc123...
```

---

## 7. agent_config.py — The Config Loader

New file: `.claude/hooks/agent_config.py`

```python
import json, os
from pathlib import Path

_CONFIG_PATH = Path.home() / ".agent-config.json"
_CACHE = None

def cfg(key: str, default=None):
    """Load a value from ~/.agent-config.json. Falls back to env var, then default."""
    global _CACHE
    if _CACHE is None:
        if _CONFIG_PATH.exists():
            _CACHE = json.loads(_CONFIG_PATH.read_text())
        else:
            _CACHE = {}
    return _CACHE.get(key) or os.environ.get(key) or default

def cfg_all() -> dict:
    """Return the full config dict."""
    cfg("_warmup")  # trigger load
    return dict(_CACHE)
```

### Hook migration pattern

Every hook that currently hardcodes a value changes exactly one way:

**Before:**
```python
HARNESS_DB  = "de10157da3e34ef58a74ea240f31fe98"
USER_ID     = "U0AV1DX3WSE"
WORKSPACE   = "taleemabad-talk.slack.com"
```

**After:**
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from agent_config import cfg

HARNESS_DB  = cfg("NOTION_HARNESS_DB_ID")
USER_ID     = cfg("USER_SLACK_ID")
WORKSPACE   = cfg("SLACK_WORKSPACE")
```

No logic changes in any hook. Only constant definitions change.

---

## 8. Hooks to Migrate (12 files)

Every file that contains a hardcoded value from this list must be migrated:

| Config key | Current hardcoded value | Files to update |
|---|---|---|
| `NOTION_HARNESS_DB_ID` | `de10157da3e34ef58a74ea240f31fe98` | session-start.py, kamil-task-interceptor.py, poll-harness-notion.py, poll-eng-slack.py, orchestrator-dispatch.py, kamil-manager.py, escalation-broker.py, kamil-evolution-agent.py, stop-notion.py |
| `NOTION_WORK_LOG_DB_ID` | `0b71db855f914d18ac6d97c0f77fc21e` | session-start.py, stop-notion.py |
| `NOTION_INBOX_DB_ID` | `6d14f1b6b8cd4ff68fd40efdfc3f304e` | session-start.py |
| `USER_SLACK_ID` | `U0AV1DX3WSE` | slack-poller.py, kamil-task-interceptor.py, kamil-slack-listener.py, poll-eng-slack.py |
| `SLACK_WORKSPACE` | `taleemabad-talk.slack.com` | slack-poller.py |
| `AGENT_NAME` | `Kamil` | CLAUDE.md, all .claude/rules/*.md |
| `USER_NAME` | `Kamal` | CLAUDE.md, all .claude/rules/*.md |
| `REPO_ROOT` | `/home/oye/Documents/free_work/personal-agent-v2` | session-start.py, stop.py, settings.json (mempalace path) |

---

## 9. Notion Database Schema (created by wizard)

### [AGENT_NAME] Harness
The task backlog. Required properties:

| Property | Type |
|---|---|
| Name | Title |
| Status | Select: Not started / In progress / Done / Blocked / In review / Cancelled |
| Phase | Select: Research / Planning / In Dev / Testing / Done / Blocked |
| Plan Summary | Rich Text |
| Confidence | Number |
| Last Activity | Date |
| Agent Session ID | Rich Text |
| Last Agent Update | Date |
| GitHub PR | URL |
| Slack Thread | URL |

### [AGENT_NAME] Work Log
Session logs. Required properties:

| Property | Type |
|---|---|
| Date | Title (date string) |
| Summary | Rich Text |
| Session ID | Rich Text |
| Duration | Number |
| Tasks Completed | Rich Text |

### [AGENT_NAME] Inbox (Slack only)
Classified messages. Required properties:

| Property | Type |
|---|---|
| Message | Title |
| From | Rich Text |
| Channel | Rich Text |
| Status | Select: New / Read / Actioned |
| Received At | Date |

All 3 databases are created under a single Notion page called "[AGENT_NAME] Brain"
which the wizard creates first as the parent.

---

## 10. Repository Cleanup (private data removal)

### Files to template (replace hardcoded values with {{placeholders}})

| File | What changes |
|---|---|
| `CLAUDE.md` | "Kamil" → `{{AGENT_NAME}}`, "Kamal" → `{{USER_NAME}}`, "taleemabad" project refs → generic |
| `.claude/rules/notion.md` | All DB IDs → `{{config:NOTION_HARNESS_DB_ID}}` etc. |
| `.claude/rules/slack.md` | `U0AV1DX3WSE` → `{{config:USER_SLACK_ID}}`, workspace → `{{config:SLACK_WORKSPACE}}` |
| `.claude/rules/orchestrator.md` | Slack ID references → `{{config:USER_SLACK_ID}}` |
| `.claude/rules/taleemabad.md` | Remove taleemabad-specific paths, replace with `{{config:REPO_ROOT}}` |
| `.claude/agents/*.md` | `U0AV1DX3WSE` → `{{config:USER_SLACK_ID}}` in DM instructions |

### Files to wipe and replace with templates

| File | Replacement |
|---|---|
| `vault/notion-map.md` | Empty template with instructions |
| `STANDUP.md` | Empty template |
| `vault/memory/kamil_personality.md` | Template: "Fill in your agent's personality here" |
| `vault/memory/*.md` (team members) | Remove team-specific files; replace with generic example |
| `vault/logs/` | Clear all session logs |
| `.beads/failures.jsonl` | Clear |

### Files to delete entirely

- `SETUP-SUMMARY.md` (replaced by README.md)
- `TRANSFER-SUMMARY.md`
- `VALIDATION-REPORT.md`
- `IMPLEMENTATION-CHECKLIST.md`

### .gitignore additions

```
# secret token files (never commit)
.claude/hooks/.notion
.claude/hooks/.slack
.claude/hooks/.linkedin
.claude/hooks/.axiom
# user session data
vault/logs/
.beads/failures.jsonl
# python
*.pyc
__pycache__/
```

Note: `~/.agent-config.json` lives outside the repo (in the user's home dir) so it
doesn't need a `.gitignore` entry — it's never inside the repo folder.

---

## 11. README.md (new file)

```markdown
# Personal AI Agent

Your own AI agent that remembers, learns, and works — powered by Claude.

## What it does

- **Remembers** your work across sessions via Notion
- **Learns** from its mistakes and improves itself
- **Orchestrates** specialist agents for different tasks
- **Integrates** with Slack (optional) to respond to @mentions

## Setup (5 minutes)

1. Clone this repo
2. Install [Claude Code](https://claude.ai/code)
3. Open Claude Code in the repo folder
4. Type: `/setup`

The setup wizard will ask you 6 questions and handle everything else.

## What you need

- A [Notion account](https://notion.so) (free)
- A [Notion API token](https://www.notion.so/my-integrations)
- Slack (optional — for @mention triggers)

## After setup

Start a new Claude Code session in this folder and talk to your agent.
Your agent's name, personality, and Notion workspace are yours to customize.

## Customizing your agent

- **Identity**: Edit `CLAUDE.md` and `vault/memory/` files
- **Skills**: Add slash commands to `.claude/commands/`
- **Rules**: Edit `.claude/rules/` to change how your agent behaves
- **Agents**: Add new specialist agents to `.claude/agents/`

## Reconfigure

Run `/setup` at any time to reconfigure your agent.
```

---

## 12. Settings.json — Mempalace Path Fix

The mempalace MCP server has an absolute path:
```json
"args": ["serve", "--palace", "/home/oye/Documents/free_work/personal-agent-v2/mempalace"]
```

This must become relative or use the `REPO_ROOT` config value. The wizard
writes a `settings.local.json` (gitignored) with the user's actual path,
which Claude Code merges with `settings.json`.

---

## 13. Success Criteria

The implementation is complete when:

1. A user can clone the repo, type `/setup`, answer 6 questions, and have a working agent — no manual file editing required.
2. Zero references to `U0AV1DX3WSE`, `de10157da3e34ef58a74ea240f31fe98`, `taleemabad-talk.slack.com`, `/home/oye/`, `Kamal`, or `Kamil` remain in any committed file.
3. All 12 hooks read from `agent_config.py` instead of hardcoded constants.
4. Running `/setup` twice produces a clean reconfiguration (idempotent).
5. A user with no Slack account can complete setup and have a working agent (Slack is optional).
6. The README explains setup in 3 steps.

---

## 14. Out of Scope

- Slack app creation automation (OAuth flow too complex — wizard gives link + checklist)
- GitHub integration setup (optional, user adds later)
- Content pipeline / job finder / NotebookLM (optional modules)
- Web UI for configuration
- Docker / containerization
- Multiple agent profiles (one agent per install)
