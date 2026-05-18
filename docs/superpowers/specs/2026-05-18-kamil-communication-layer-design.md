# Kamil Communication Layer — Design Spec
_Date: 2026-05-18_

## Goal

Allow Kamal to message Kamil from anywhere on his laptop (terminal or Slack) and receive a response grounded in Kamil's Notion brain. Kamil can also use project MCPs when the question involves active development work.

---

## Architecture

```
Kamal (terminal)          Kamal (Slack @kamil)
      |                          |
 ~/bin/kamil CLI           slack-poller.py (extended)
      |                          |
      └──────────┬───────────────┘
                 ↓
         ~/kamil-inbox/<timestamp>.json
         { text, source, cwd, project, timestamp }
                 ↓
         kamil-daily.sh (every 30min cron)
                 ↓
         inbox-processor.py
         - reads all unprocessed inbox files
         - for each: spins claude --print session
         - prompt includes: Notion context + the question
         - Claude answers using Notion (Work Log, Slack Inbox, Team People, My PRs)
         - if project context present: uses project harness MCPs
                 ↓
         response → Slack DM to Kamal (U0AV1DX3WSE)
         conversation → logged to Notion Work Log
         inbox file → marked processed (rename to .done)
```

---

## Components

### 1. `~/bin/kamil` — CLI script

A bash script installed to `~/bin/kamil` (already in PATH or symlinked).

```
Usage: kamil "your message"
       kamil   (opens $EDITOR for longer messages)
```

- Writes a JSON file to `~/kamil-inbox/<timestamp>-cli.json`:
  ```json
  {
    "id": "2026-05-18T09:30:00-cli",
    "source": "cli",
    "text": "did Haroon read the message?",
    "cwd": "/home/oye/Documents/taleemabad-core",
    "project": "taleemabad-core",
    "timestamp": "2026-05-18T09:30:00"
  }
  ```
- Prints: `Message queued for Kamil. He'll respond on Slack within 30min.`
- Project is auto-detected from `$PWD` by matching known project paths

### 2. Slack @mention detection (extend `slack-poller.py`)

- When polling channels, detect any message containing `@kamil` or DMs sent to a Kamil bot user
- Extract the message text (strip the mention)
- Write to `~/kamil-inbox/<timestamp>-slack.json` with `source: "slack"`
- Same schema as CLI inbox files

### 3. `~/kamil-inbox/` — Message queue

- Directory of JSON files, one per message
- Unprocessed: `<timestamp>-<source>.json`
- Processed: `<timestamp>-<source>.json.done`
- Processor renames to `.done` after handling — no deletions

### 4. `inbox-processor.py` — Core processor

Called by `kamil-daily.sh` before the main daily loop.

For each unprocessed inbox file:
1. Load message JSON
2. Build prompt:
   - Kamil identity + Notion brain page ID
   - The user's question
   - Project context (if cwd detected a known project)
   - Instruction: answer from Notion, use Slack/Notion MCPs, respond via Slack DM
3. Spin `claude --dangerously-skip-permissions --print -p "<prompt>"`
4. Rename inbox file to `.done`

**Prompt template:**
```
You are Kamil, Kamal's autonomous personal agent.
Kamal has a question for you: "<text>"

Context: He sent this from <cwd> (project: <project>).

Answer using your Notion brain (page ID: 364d8747b3b1813d8ac8c248800f0a4d).
Read the relevant Notion databases: Work Log, Slack Inbox, Team People, My PRs.
If the question is about a project, check the harness for that project.

After answering, send your response as a Slack DM to Kamal (U0AV1DX3WSE).
Log this conversation to Notion Work Log under "Kamal asked: <text>".

Rules:
- Never send Slack messages to anyone else without Kamal's approval
- Never push code without Kamal's approval
- Be direct, no fluff
- Sign off as Kamil 🤖
```

### 5. `kamil-daily.sh` (extended)

Add at the top of the main loop, before the existing daily exploration:

```bash
# Process any queued messages first
python3 "$KAMIL_DIR/.claude/hooks/inbox-processor.py"
```

---

## Project Detection

Known project paths mapped to project names:

| Path | Project |
|---|---|
| `/home/oye/Documents/taleemabad-core` | `taleemabad-core` |
| `*/repos/taleemabad-cms` | `taleemabad-cms` |
| `*/repos/taleemabad-auth` | `taleemabad-auth` |
| `*/repos/portfolio-website` | `portfolio-website` |

If `$PWD` matches a known path prefix → project is set in the inbox message.

---

## Error Handling

- If `claude` not in PATH: log to `/tmp/kamil-inbox-processor.log`, skip file (leave as unprocessed for next run)
- If Notion/Slack MCP unavailable: Claude answers from whatever context it has, notes the gap in the Slack response
- If inbox file is malformed JSON: log and skip, rename to `.error`
- Max retries: 3 (track in inbox file metadata)

---

## Success Criteria

- `kamil "question"` from any terminal queues a message in under 1 second
- Within 30min (next cron run), Kamil responds via Slack DM
- Response references actual Notion data (not hallucinated)
- Conversation is logged to Notion Work Log
- @kamil mentions in Slack are picked up by the poller and processed the same way

---

## Files Created / Modified

| File | Action |
|---|---|
| `~/bin/kamil` | Create — CLI script |
| `~/kamil-inbox/` | Create — inbox directory |
| `.claude/hooks/inbox-processor.py` | Create — message processor |
| `kamil-daily.sh` | Modify — call inbox-processor at start |
| `.claude/hooks/slack-poller.py` | Modify — detect @kamil mentions |
