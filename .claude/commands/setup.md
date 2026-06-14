# /setup — Personal Agent Setup Wizard

You are running the setup wizard for this personal AI agent template.
Your job is to guide the user through setup by asking questions one at a time,
then using the Python helpers in `.claude/hooks/notion_setup.py` to automate
all technical steps. The user should never have to edit a file manually.

## Before you start

Check if setup has already been run:

```bash
python3 -c "
import sys
sys.path.insert(0, '.claude/hooks')
from agent_config import is_configured, cfg
if is_configured():
    print(f'Already configured: agent={cfg(\"AGENT_NAME\")}, user={cfg(\"USER_NAME\")}')
else:
    print('Not configured')
"
```

If already configured, say:
"Your agent **[AGENT_NAME]** is already set up. Running /setup will replace your current configuration.
Type `yes` to continue, or anything else to cancel."

If user cancels, stop here.

---

## Step 1 — Welcome

Say exactly:
```
Hi! I'm going to set up your personal AI agent. I'll ask you a few questions,
then handle everything else automatically — creating your Notion databases,
writing config files, and personalising your agent identity.

This takes about 5 minutes. Let's start.

What's your name?
```

Wait for the user's reply. Store as USER_NAME.

---

## Step 2 — Agent name

Say:
```
Nice to meet you, [USER_NAME]! What do you want to call your agent?
(e.g. Varys, Max, Nova, Atlas — pick anything you like)
```

Wait for reply. Store as AGENT_NAME.

---

## Step 3 — Notion token

Say:
```
To connect [AGENT_NAME] to Notion, I need your Notion API token.

Here's how to get one (takes 2 minutes):
1. Go to: https://www.notion.so/my-integrations
2. Click "New integration"
3. Give it a name (e.g. "[AGENT_NAME] Agent")
4. Select your workspace
5. Click "Save" — you'll see a token starting with "secret_"
6. Copy that token and paste it here

Paste your Notion API token:
```

Wait for reply. This is the NOTION_API_KEY. It starts with `secret_`.

Test the token immediately:
```bash
python3 -c "
import sys
sys.path.insert(0, '.claude/hooks')
from notion_setup import test_connection
ok, msg = test_connection('PASTE_TOKEN_HERE')
print('OK' if ok else 'FAIL', msg)
"
```
(Replace PASTE_TOKEN_HERE with the actual token the user gave you.)

If the test returns FAIL, say:
```
That token didn't work: [error message]

Double-check you copied the full token (it starts with "secret_").
Paste it again:
```

Retry up to 3 times. If still failing after 3 attempts, say:
```
I'm having trouble connecting to Notion. This usually means:
- The token was copied incorrectly (check for spaces at start/end)
- The integration wasn't saved properly

Please try creating a new integration at https://www.notion.so/my-integrations
and paste the new token. Or type /setup to start over.
```
Then stop.

---

## Step 4 — Slack (optional)

Say:
```
Do you want Slack integration? This lets [AGENT_NAME] respond when you
@mention them in Slack channels.

(If you don't use Slack or want to set this up later, just say "no" or "skip")
```

If user says no/skip/later → set SLACK_ENABLED=false, skip to Step 5 (Config).

If yes, ask:
```
What's your Slack workspace URL?
(e.g. my-company.slack.com — just the domain, not the full URL)
```
Wait for reply. Store as SLACK_WORKSPACE.

Then ask:
```
What's your Slack user ID? This is how [AGENT_NAME] knows who to DM.

To find it: In Slack, click your profile picture → "Profile" → click the
"..." menu → "Copy member ID". It looks like U1234ABCDE.

Paste your Slack user ID:
```
Wait for reply. Store as USER_SLACK_ID.

Then ask:
```
Last thing for Slack — paste your bot token (starts with xoxb-).

To get one: Create a Slack app at https://api.slack.com/apps, add the
bot scopes (chat:write, channels:history, channels:read), install it to
your workspace, and copy the "Bot User OAuth Token".

Paste your Slack bot token:
```
Wait for reply. Store as SLACK_BOT_TOKEN. Set SLACK_ENABLED=true.

---

## Step 5 — Confirm

Say:
```
Got it! Here's what I'm setting up:

- Your name: [USER_NAME]
- Agent name: [AGENT_NAME]
- Notion: ✅ connected
- Slack: [✅ enabled / ⏭️ skipped]

Creating your agent now — this takes about 30 seconds.
```

---

## Step 6 — Automated setup

Run these steps in order. Show each line as you complete it.
If ANY step fails, say "Setup stopped at step [N]: [error]" and stop — do not write partial config files.

### 6a — Create Notion parent page
```bash
python3 -c "
import sys
sys.path.insert(0, '.claude/hooks')
from notion_setup import create_parent_page
page_id = create_parent_page('NOTION_API_KEY', 'AGENT_NAME')
print(page_id)
"
```
(Replace NOTION_API_KEY and AGENT_NAME with actual values.)
Store output as NOTION_PARENT_PAGE_ID.
Show: `[1/5] Creating "[AGENT_NAME] Brain" page in Notion ✓`

### 6b — Create Harness database
```bash
python3 -c "
import sys
sys.path.insert(0, '.claude/hooks')
from notion_setup import create_harness_db
db_id = create_harness_db('NOTION_API_KEY', 'PARENT_PAGE_ID', 'AGENT_NAME')
print(db_id)
"
```
Store output as NOTION_HARNESS_DB_ID.
Show: `[2/5] Creating "[AGENT_NAME] Harness" database ✓`

### 6c — Create Work Log database
```bash
python3 -c "
import sys
sys.path.insert(0, '.claude/hooks')
from notion_setup import create_work_log_db
db_id = create_work_log_db('NOTION_API_KEY', 'PARENT_PAGE_ID', 'AGENT_NAME')
print(db_id)
"
```
Store output as NOTION_WORK_LOG_DB_ID.
Show: `[3/5] Creating "[AGENT_NAME] Work Log" database ✓`

### 6d — Create Inbox database (only if SLACK_ENABLED=true)
```bash
python3 -c "
import sys
sys.path.insert(0, '.claude/hooks')
from notion_setup import create_inbox_db
db_id = create_inbox_db('NOTION_API_KEY', 'PARENT_PAGE_ID', 'AGENT_NAME')
print(db_id)
"
```
Store output as NOTION_INBOX_DB_ID.
Show: `[3/5] Creating "[AGENT_NAME] Inbox" database ✓`
If Slack skipped, set NOTION_INBOX_DB_ID="" and show: `[3/5] Slack inbox skipped ⏭️`

### 6e — Write ~/.agent-config.json
```bash
python3 -c "
import json
from pathlib import Path
from datetime import datetime
config = {
    'AGENT_NAME': 'AGENT_NAME',
    'USER_NAME': 'USER_NAME',
    'USER_SLACK_ID': 'USER_SLACK_ID_OR_EMPTY',
    'SLACK_WORKSPACE': 'SLACK_WORKSPACE_OR_EMPTY',
    'SLACK_ENABLED': False,
    'NOTION_HARNESS_DB_ID': 'NOTION_HARNESS_DB_ID',
    'NOTION_WORK_LOG_DB_ID': 'NOTION_WORK_LOG_DB_ID',
    'NOTION_INBOX_DB_ID': 'NOTION_INBOX_DB_ID_OR_EMPTY',
    'REPO_ROOT': str(Path.cwd()),
    'SETUP_COMPLETED_AT': datetime.utcnow().isoformat(),
}
Path.home().joinpath('.agent-config.json').write_text(json.dumps(config, indent=2))
print('written')
"
```
(Replace all placeholder values with actual collected values.)
Show: `[4/5] Writing config files ✓`

### 6f — Write ~/.claude/hooks/.notion
```bash
python3 -c "
from pathlib import Path
p = Path.home() / '.claude' / 'hooks' / '.notion'
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text('NOTION_API_KEY=ACTUAL_TOKEN\n')
print('written')
"
```
(Replace ACTUAL_TOKEN with the real token.)

### 6g — Write ~/.claude/hooks/.slack (only if SLACK_ENABLED=true)
```bash
python3 -c "
from pathlib import Path
p = Path.home() / '.claude' / 'hooks' / '.slack'
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text('BOT_TOKEN=ACTUAL_BOT_TOKEN\nSLACK_BOT_TOKEN=ACTUAL_BOT_TOKEN\n')
print('written')
"
```
(Replace ACTUAL_BOT_TOKEN with the real bot token.)

### 6h — Personalise CLAUDE.md
```bash
python3 -c "
from pathlib import Path
f = Path('CLAUDE.md')
content = f.read_text()
content = content.replace('{{AGENT_NAME}}', 'AGENT_NAME')
content = content.replace('{{USER_NAME}}', 'USER_NAME')
f.write_text(content)
print('personalised')
"
```
(Replace AGENT_NAME and USER_NAME with actual values.)
Show: `[5/5] Personalising your agent identity ✓`

---

## Step 7 — Verify

```bash
python3 -c "
import sys
sys.path.insert(0, '.claude/hooks')
from notion_setup import write_test_entry, delete_test_entry
from pathlib import Path

api_key = None
notion_file = Path.home() / '.claude' / 'hooks' / '.notion'
for line in notion_file.read_text().splitlines():
    if line.startswith('NOTION_API_KEY='):
        api_key = line.split('=', 1)[1].strip()

from agent_config import cfg
db_id = cfg('NOTION_WORK_LOG_DB_ID')
page_id = write_test_entry(api_key, db_id)
delete_test_entry(api_key, page_id)
print('verification passed')
"
```

If verification passes, say:
```
Testing connection... ✅ Notion connected
✅ [AGENT_NAME] is ready, [USER_NAME]!

What's next:
1. Close this session
2. Open a new Claude Code session in this folder
3. [AGENT_NAME] will greet you and load your Notion context automatically

Your Notion workspace now has a page called "[AGENT_NAME] Brain" with your
Harness and Work Log databases inside.

Run /setup at any time to reconfigure.
```

If verification fails, say:
```
❌ Verification failed: [error]

Your config files were saved, but the Notion connection test failed.
This might be a temporary issue. Try:
1. Close and reopen Claude Code
2. Check your Notion integration at https://www.notion.so/my-integrations
   (make sure it has "Read content" and "Insert content" capabilities)
3. Run /setup again if needed
```

---

## Security rules

- NEVER log or display the full Notion API key or Slack bot token to the user after they paste it
- NEVER commit the token files to git (they're in .gitignore)
- NEVER store tokens in ~/.agent-config.json — only in the dedicated token files
