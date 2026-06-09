# kamil-agent: Make It Public-Ready for Non-Technical Users
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A non-technical user clones the repo, types `/setup`, answers 6 questions, and has a working personal AI agent — with zero confusion, zero personal data from Kamal, and zero unexplained complexity.

**Architecture:** Three layers of cleanup: (1) delete/replace all personal vault files with generic templates, (2) remove hardcoded personal data from hooks, (3) add a short "what happens next" guide so the first session isn't confusing.

**Tech Stack:** Python, Markdown, Bash, git

---

## File Map

### Delete (personal data — no generic equivalent needed)
- `vault/memory/collaborator_anam_masood.md`
- `vault/memory/omer_rana_direct_report.md`
- `vault/memory/taleemabad_workplace.md`
- `vault/memory/taleemabad_training_project.md`
- `vault/memory/taleemabad_cms_project.md`
- `vault/memory/taleemabad_oxbridge_feature.md`
- `vault/memory/posthog_credentials.md`
- `vault/memory/jira_hook.md`
- `vault/memory/graphify_integration.md`
- `vault/memory/portfolio_ownership.md`
- `vault/memory/repo_personal_agent_workspace.md`
- `vault/memory/project_workspace.md`
- `vault/domains/taleemabad/` (entire folder)
- `vault/domains/contacts/` (entire folder — real people's names)
- `BUGS.md` (Kamal's personal bug log)

### Replace with generic templates
| File | Replaces |
|------|----------|
| `vault/memory/user_profile.md` | "Muhammad Kamal at Taleemabad" → generic template |
| `vault/memory/kamil_personality.md` | Kamal-specific personality → generic agent personality template |
| `vault/memory/kamil_humor_profile.md` | Kamal-specific humor → generic template |
| `vault/memory/kamil_face.md` | Kamal's avatar → generic template |
| `vault/memory/MEMORY.md` | Kamal's memory index → generic template |
| `MEMORY.md` (root) | Same — generic |

### Fix hooks with personal data
- `.claude/hooks/auto-apply.py` — remove `oyekamal` GitHub URL
- `.claude/hooks/portfolio-updater.py` — remove hardcoded GitHub portfolio URL
- `.claude/hooks/notebooklm_handler.py` — remove email comment

### Add new files
- `AFTER-SETUP.md` — "What happens at your first session" guide
- `vault/memory/user_profile.md` — generic template (replaces Kamal's)
- `vault/memory/agent_personality.md` — generic template (replaces kamil_personality.md)

---

## Task 1: Delete all personal vault files and folders

**Files:**
- Delete: 13 vault/memory files + 2 vault/domain folders listed above
- Delete: `BUGS.md`

- [ ] **Step 1: Delete personal memory files**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git rm -f \
  vault/memory/collaborator_anam_masood.md \
  vault/memory/omer_rana_direct_report.md \
  vault/memory/taleemabad_workplace.md \
  vault/memory/taleemabad_training_project.md \
  vault/memory/taleemabad_cms_project.md \
  vault/memory/posthog_credentials.md \
  vault/memory/jira_hook.md \
  vault/memory/graphify_integration.md \
  vault/memory/portfolio_ownership.md \
  vault/memory/repo_personal_agent_workspace.md \
  vault/memory/project_workspace.md 2>/dev/null
echo "memory files deleted"
```

- [ ] **Step 2: Delete taleemabad_oxbridge_feature.md if it exists**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git rm -f vault/memory/taleemabad_oxbridge_feature.md 2>/dev/null || echo "not found, skip"
```

- [ ] **Step 3: Delete personal domain folders**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git rm -rf vault/domains/taleemabad/ vault/domains/contacts/ 2>/dev/null
echo "domain folders deleted"
```

- [ ] **Step 4: Delete BUGS.md**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git rm -f BUGS.md 2>/dev/null || echo "not found"
```

- [ ] **Step 5: Verify deleted**

```bash
ls /home/oye/Documents/free_work/personal-agent-v2/vault/memory/
```
Expected: only generic files remain (kamil_personality.md, user_profile.md, etc.)

- [ ] **Step 6: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git commit -m "chore: delete personal vault files and domain data for public template"
```

---

## Task 2: Replace personal memory files with generic templates

**Files:**
- Modify: `vault/memory/user_profile.md`
- Modify: `vault/memory/kamil_personality.md` → rename to `vault/memory/agent_personality.md`
- Modify: `vault/memory/kamil_humor_profile.md`
- Modify: `vault/memory/kamil_face.md`
- Modify: `vault/memory/MEMORY.md`
- Modify: `MEMORY.md` (root)

- [ ] **Step 1: Rewrite user_profile.md as a generic template**

Write to `vault/memory/user_profile.md`:
```markdown
---
type: user
description: Profile of the person who owns this agent — fill in after /setup
---

# Your Profile

> This file is populated after you run `/setup`. Edit it to help your agent understand who you are.

## Basic Info
- **Name**: {{USER_NAME}}
- **Role**: (e.g. Software Engineer, Designer, Founder)
- **Location**: (your city/timezone)
- **Current focus**: (what you're mainly working on right now)

## How You Work
- **Preferred communication style**: (e.g. direct, detailed, brief)
- **Work hours**: (e.g. 9am-6pm, flexible)
- **Tools you use daily**: (e.g. GitHub, Notion, Slack, VS Code)

## What Your Agent Should Know
- (Add anything your agent should keep in mind about you)
- (Projects you're working on)
- (Things you care about)
```

- [ ] **Step 2: Rewrite agent_personality.md as a generic template**

Delete old kamil_personality.md and create agent_personality.md:
```bash
git rm -f vault/memory/kamil_personality.md 2>/dev/null
```

Write to `vault/memory/agent_personality.md`:
```markdown
---
type: user
description: Your agent's personality — edit to match how you want it to behave
---

# {{AGENT_NAME}} — Personality

> Edit this file to shape how your agent talks and acts. The more specific you are, the better.

## Tone
- Professional but warm
- Direct — says what it means without padding
- Occasionally dry humour when the moment is right
- Never robotic or over-formal

## How {{AGENT_NAME}} Responds
- Short answers for simple questions, detailed for complex ones
- Always acts then confirms — never says "I would need to..." just does it
- Signs off as "🤖 {{AGENT_NAME}}" in Slack messages
- Never asks clarifying questions that the code or thread already answers

## What {{AGENT_NAME}} Cares About
- Getting things right over getting them fast
- Transparency — tells {{USER_NAME}} when something can't be done
- Learning — logs failures and improves from them

## Customize This
Replace the above with your own preferences. Examples:
- "Be more casual — use contractions, informal language"
- "Always give me 3 options before recommending one"
- "Never use bullet points in casual replies"
```

- [ ] **Step 3: Rewrite kamil_humor_profile.md**

```bash
cat > /home/oye/Documents/free_work/personal-agent-v2/vault/memory/kamil_humor_profile.md << 'EOF'
---
type: user
description: Agent humor style — edit to match your preferences
---

# Humor Profile

> Edit this to tell your agent when and how to be funny.

- Dry wit preferred over slapstick
- Humor when the situation is light, not when stakes are high
- Self-aware is good, self-deprecating is fine
- Never forced — if it doesn't land naturally, skip it
- Log humor attempts to /tmp/agent-humor-log.jsonl for review
EOF
```

- [ ] **Step 4: Rewrite kamil_face.md**

```bash
cat > /home/oye/Documents/free_work/personal-agent-v2/vault/memory/kamil_face.md << 'EOF'
---
type: user
description: Agent visual identity — optional, for avatar/image generation
---

# {{AGENT_NAME}} Visual Identity

> Optional: fill this in if you want your agent to have a visual identity for avatars or social posts.

## If You Want an Agent Avatar
Describe your agent's visual style here. Examples:
- "Minimalist robot icon, dark blue and white, geometric shapes"
- "Friendly illustrated character, warm colors, approachable"
- "Abstract logo, initials {{AGENT_NAME}}, modern sans-serif"

## Current Assets
(none — add paths to generated assets here after creation)
EOF
```

- [ ] **Step 5: Rewrite vault/memory/MEMORY.md**

```bash
cat > /home/oye/Documents/free_work/personal-agent-v2/vault/memory/MEMORY.md << 'EOF'
# Memory Index

This folder contains your agent's persistent memory files.
They are loaded at session start and help your agent understand who you are and how you work.

## Files in This Folder

| File | What it stores |
|------|---------------|
| `user_profile.md` | Your name, role, preferences — edit after /setup |
| `agent_personality.md` | How {{AGENT_NAME}} talks and acts — customise freely |
| `kamil_humor_profile.md` | Humor style — edit to your preference |
| `kamil_face.md` | Visual identity — optional |

## How to Add Your Own Memory

Create a new `.md` file here with this header:
```
---
type: user
description: one-line description of what this file stores
---
```

Your agent will pick it up automatically at the next session start.
EOF
```

- [ ] **Step 6: Rewrite root MEMORY.md**

Write to `/home/oye/Documents/free_work/personal-agent-v2/MEMORY.md`:
```markdown
# {{AGENT_NAME}} Memory Index

> This file is your agent's memory index. It is loaded at every session start.
> After running `/setup`, your agent's name will replace `{{AGENT_NAME}}` here.

## Quick Reference

| Memory | File | What it stores |
|--------|------|---------------|
| Your profile | `vault/memory/user_profile.md` | Who you are, your role, how you work |
| Agent personality | `vault/memory/agent_personality.md` | How your agent communicates |
| Notion Brain | `~/.agent-config.json` | Your Notion DB IDs (created by /setup) |

## How Memory Works

1. You run `/setup` once — this creates your Notion databases and writes `~/.agent-config.json`
2. Every Claude session reads these memory files at start
3. Session logs are written to `vault/logs/YYYY-MM-DD.md` automatically
4. Your agent learns from its mistakes via the evolution agent

## Customising Your Agent

Edit any file in `vault/memory/` to change how your agent understands you.
Add new files with `type: user` frontmatter and they'll be picked up automatically.
```

- [ ] **Step 7: Verify no personal names remain in vault/memory**

```bash
grep -rn "Kamal\|Kamil\|Anam\|Omer\|Taleemabad\|taleemabad\|m\.kamal" \
  /home/oye/Documents/free_work/personal-agent-v2/vault/memory/ 2>/dev/null | head -10
```
Expected: no output or only `{{AGENT_NAME}}`/`{{USER_NAME}}` references

- [ ] **Step 8: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add vault/memory/
git commit -m "refactor: replace personal vault/memory files with generic templates"
```

---

## Task 3: Fix remaining hooks with personal data

**Files:**
- Modify: `.claude/hooks/auto-apply.py`
- Modify: `.claude/hooks/portfolio-updater.py`
- Modify: `.claude/hooks/notebooklm_handler.py`

- [ ] **Step 1: Fix auto-apply.py — remove oyekamal GitHub URL**

```bash
grep -n "oyekamal" /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/auto-apply.py
```

Replace any `https://github.com/oyekamal` with `{{config:GITHUB_PROFILE_URL}}` or remove:
```bash
python3 -c "
from pathlib import Path
f = Path('/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/auto-apply.py')
c = f.read_text()
c = c.replace('https://github.com/oyekamal', 'https://github.com/{{YOUR_GITHUB}}')
f.write_text(c)
print('fixed auto-apply.py')
"
```

- [ ] **Step 2: Fix portfolio-updater.py — remove hardcoded portfolio repo URL**

```bash
grep -n "oyekamal\|portfolio-data" /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/portfolio-updater.py | head -5
```

Replace hardcoded GitHub URLs:
```bash
python3 -c "
from pathlib import Path
f = Path('/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/portfolio-updater.py')
c = f.read_text()
c = c.replace('https://github.com/oyekamal/portfolio-data', 'https://github.com/{{YOUR_GITHUB}}/portfolio-data')
c = c.replace('oyekamal', '{{YOUR_GITHUB}}')
f.write_text(c)
print('fixed portfolio-updater.py')
"
```

- [ ] **Step 3: Fix notebooklm_handler.py — remove email comment**

```bash
python3 -c "
from pathlib import Path
f = Path('/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/notebooklm_handler.py')
c = f.read_text()
c = c.replace('# work email m.kamal@taleemabad.com', '# set NLM_PROFILE env var to your NotebookLM profile name')
c = c.replace('m.kamal@taleemabad.com', '{{USER_EMAIL}}')
f.write_text(c)
print('fixed notebooklm_handler.py')
"
```

- [ ] **Step 4: Verify syntax on all 3 files**

```bash
for f in auto-apply portfolio-updater notebooklm_handler; do
  python3 -c "import ast; ast.parse(open('/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/${f}.py').read()); print('${f}: OK')"
done
```
Expected: all 3 OK

- [ ] **Step 5: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/hooks/auto-apply.py .claude/hooks/portfolio-updater.py .claude/hooks/notebooklm_handler.py
git commit -m "fix: remove personal GitHub URLs and emails from hooks"
```

---

## Task 4: Add AFTER-SETUP.md — the missing guide

**Files:**
- Create: `AFTER-SETUP.md`

- [ ] **Step 1: Write the file**

Write to `/home/oye/Documents/free_work/personal-agent-v2/AFTER-SETUP.md`:

```markdown
# After /setup — What Happens Next

You've run `/setup` and your agent is configured. Here's what to expect.

---

## Starting Your First Session

Open Claude Code in this folder and start a new session. Your agent will:

1. **Greet you by name** — CLAUDE.md has been personalised with your name and agent name
2. **Load your Notion context** — You'll see "Loading Notion brain..." for a few seconds
3. **Tell you what's in your Notion** — Any tasks or notes you have in your Harness database

This is normal. It happens every session.

---

## Talking to Your Agent

Just type naturally. Examples:

> "What do I have on my plate today?"

> "Help me write a LinkedIn post about [topic]"

> "Research the best tools for [topic]"

> "Remember that I prefer [X] when doing [Y]"

Your agent routes each request to the right specialist automatically.

---

## Your Notion Workspace

After `/setup`, your Notion workspace has a page called **"[AGENT_NAME] Brain"** with:

| Database | What it's for |
|----------|--------------|
| **[AGENT_NAME] Harness** | Task backlog — your agent tracks work here |
| **[AGENT_NAME] Work Log** | Automatic session logs — written at session end |
| **[AGENT_NAME] Inbox** | Slack messages (only if you enabled Slack) |

You can open these in Notion and see your agent's work in real time.

---

## Auto-Commits (What They Are)

At the end of every session, your agent automatically:
- Writes a summary to your Notion Work Log
- Commits any changes to `vault/logs/` with the message `log: session YYYY-MM-DD`

**This is intentional.** It keeps a history of your agent's activity in git.
If you don't want this, comment out the `Stop` hook in `.claude/settings.json`.

---

## Customising Your Agent

| You want to change... | Edit this file |
|----------------------|---------------|
| Agent's name or your name | Run `/setup` again |
| How the agent talks | `vault/memory/agent_personality.md` |
| Who you are / your context | `vault/memory/user_profile.md` |
| Which tasks to delegate to agents | `.claude/rules/skills-router.md` |
| What the agent does on session start | `.claude/hooks/session-start.py` |

---

## Adding Slack

If you skipped Slack during setup and want to add it later, run `/setup` again and say yes to Slack when asked.

You'll need to:
1. Create a Slack app at https://api.slack.com/apps
2. Add scopes: `chat:write`, `channels:history`, `channels:read`
3. Install it to your workspace
4. Copy the Bot User OAuth Token

---

## Something Isn't Working?

**Agent doesn't know my name:** Run `/setup` again.

**Notion not loading:** Check `~/.claude/hooks/.notion` exists with your API key inside.

**Session-start errors:** Your Notion integration needs "Read content" and "Insert content" capabilities. Check at https://www.notion.so/my-integrations

**Hooks failing:** Check `/tmp/agent-*.log` files for error messages.
```

- [ ] **Step 2: Verify it was created**

```bash
wc -l /home/oye/Documents/free_work/personal-agent-v2/AFTER-SETUP.md
```
Expected: > 60 lines

- [ ] **Step 3: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add AFTER-SETUP.md
git commit -m "docs: add AFTER-SETUP.md — what happens after /setup for new users"
```

---

## Task 5: Final scan + push to kamil-agent

- [ ] **Step 1: Full private-data scan**

```bash
grep -rn "m\.kamal\|oyekamal\|Muhammad Kamal\|Anam Masood\|Omer Rana\|Haroon Yasin\|taleemabad\.com\|posthog" \
  /home/oye/Documents/free_work/personal-agent-v2/ \
  --exclude-dir=".git" --exclude-dir="__pycache__" --exclude="*.pyc" \
  2>/dev/null | grep -v "docs/superpowers/" | head -20
```
Expected: empty

- [ ] **Step 2: Check vault/memory is clean**

```bash
ls /home/oye/Documents/free_work/personal-agent-v2/vault/memory/
grep -rn "Kamal\b\|Kamil\b" /home/oye/Documents/free_work/personal-agent-v2/vault/memory/ | grep -v "{{" | head -10
```
Expected: only `{{AGENT_NAME}}`/`{{USER_NAME}}` references, no bare names

- [ ] **Step 3: Push everything to personal-agent-v2 (origin)**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git log --oneline -6
git push origin master
```

- [ ] **Step 4: Push to kamil-agent template branch**

```bash
git push kamil-agent master:template --force 2>&1
```

- [ ] **Step 5: Confirm push**

```bash
gh repo view oyekamal/kamil-agent --json pushedAt
```

---

## Self-Review

### Spec coverage
| Gap from audit | Covered by |
|---|---|
| Personal vault files (collaborators, taleemabad) | Task 1 |
| Personal memory files (user_profile, personality) | Task 2 |
| Personal email in hooks | Task 3 |
| GitHub URLs in hooks | Task 3 |
| No "what happens next" guide | Task 4 |
| Final data scan + push | Task 5 |

### What a non-technical user now gets
1. Clones repo → sees a clean README with 3 steps
2. Runs `/setup` → wizard walks them through it
3. Opens first session → AFTER-SETUP.md explains what they're seeing
4. Vault files are generic templates → nothing confusing
5. No traces of "Kamil", "Kamal", "Taleemabad" anywhere visible
