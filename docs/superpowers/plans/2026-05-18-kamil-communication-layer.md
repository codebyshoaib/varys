# Kamil Communication Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow Kamal to message Kamil from any terminal or Slack and receive a grounded response via Slack DM within 30 minutes.

**Architecture:** A file-based inbox (`~/kamil-inbox/`) acts as the message queue. A CLI script (`~/bin/kamil`) writes messages to the inbox. The Slack poller is extended to detect `@kamil` mentions and write them to the same inbox. `kamil-daily.sh` calls a new `inbox-processor.py` at the start of every run, which spins a `claude --print` session per message, instructs Claude to read Notion for context, and sends the answer as a Slack DM to Kamal.

**Tech Stack:** Python 3, Bash, Claude CLI (`claude --dangerously-skip-permissions --print`), Notion API (existing helpers in slack-poller.py), Slack API (existing helpers in slack-poller.py)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `~/bin/kamil` | Create | CLI entry point — writes message to inbox |
| `~/kamil-inbox/` | Create (dir) | Message queue directory |
| `.claude/hooks/inbox-processor.py` | Create | Reads inbox, spins Claude session per message, marks done |
| `.claude/hooks/slack-poller.py` | Modify | Detect `@kamil` mentions → write to inbox |
| `kamil-daily.sh` | Modify | Call inbox-processor.py at start of every run |

---

## Task 1: Create the inbox directory and message schema

**Files:**
- Create: `~/kamil-inbox/` (directory)
- Create: `.claude/hooks/inbox-processor.py` (stub)

- [ ] **Step 1: Create inbox directory**

```bash
mkdir -p ~/kamil-inbox
```

- [ ] **Step 2: Verify it exists**

```bash
ls -la ~/kamil-inbox
```
Expected: empty directory listing

- [ ] **Step 3: Create inbox-processor.py stub**

Create `.claude/hooks/inbox-processor.py`:

```python
#!/usr/bin/env python3
"""
inbox-processor.py — Process queued messages for Kamil.

Reads ~/kamil-inbox/*.json, spins a claude session per message,
posts response to Kamal via Slack DM, marks message as done.

Run manually:
  python3 .claude/hooks/inbox-processor.py

Called automatically by kamil-daily.sh at the start of each loop.

Config files (same as slack-poller.py):
  ~/.claude/hooks/.notion   →  NOTION_API_KEY=secret_...
  ~/.claude/hooks/.slack    →  SLACK_TOKEN=xoxp-...
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

INBOX_DIR = Path.home() / "kamil-inbox"
KAMIL_DIR = Path(__file__).parent.parent.parent  # personal-agent-v2/
LOG_FILE = Path("/tmp/kamil-inbox-processor.log")

NOTION_BRAIN_PAGE_ID = "364d8747b3b1813d8ac8c248800f0a4d"
KAMAL_SLACK_ID = "U0AV1DX3WSE"

# Known project paths → project name
PROJECT_PATHS = {
    "/home/oye/Documents/taleemabad-core": "taleemabad-core",
    "/home/oye/Documents/free_work/personal-agent-v2/repos/taleemabad-cms": "taleemabad-cms",
    "/home/oye/Documents/free_work/personal-agent-v2/repos/taleemabad-auth": "taleemabad-auth",
    "/home/oye/Documents/free_work/personal-agent-v2/repos/portfolio-website": "portfolio-website",
}


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, file=sys.stderr)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def detect_project(cwd: str) -> str:
    """Return project name from cwd, or empty string."""
    for path_prefix, project in PROJECT_PATHS.items():
        if cwd and cwd.startswith(path_prefix):
            return project
    return ""


def get_unprocessed_messages() -> list[Path]:
    """Return list of unprocessed inbox files, sorted oldest first."""
    if not INBOX_DIR.exists():
        return []
    files = sorted(INBOX_DIR.glob("*.json"))
    return files


def mark_done(inbox_file: Path):
    inbox_file.rename(inbox_file.with_suffix(".json.done"))


def mark_error(inbox_file: Path):
    inbox_file.rename(inbox_file.with_suffix(".json.error"))


def build_prompt(message: dict) -> str:
    text = message.get("text", "")
    cwd = message.get("cwd", "")
    project = message.get("project", "") or detect_project(cwd)
    source = message.get("source", "cli")

    project_context = ""
    if project:
        project_context = f"\nContext: Kamal was working in project '{project}' (path: {cwd}) when he sent this."

    return f"""You are Kamil, Kamal's autonomous personal agent.

Kamal has a question or message for you (sent via {source}):

\"{text}\"
{project_context}

Your job:
1. Answer using your Notion brain (page ID: {NOTION_BRAIN_PAGE_ID}).
   Read the relevant Notion databases: Work Log, Slack Inbox, Team People, My PRs.
   If the question is about a specific project ({project or 'check the context'}), read that project's harness too.
2. Send your response as a Slack DM to Kamal (Slack user ID: {KAMAL_SLACK_ID}).
   Keep the response direct and specific — show you actually checked Notion data, not just guessing.
   Sign off as: Kamil 🤖
3. Log this conversation to Notion Work Log with title: "Kamal asked: {text[:60]}"

Rules:
- Never send Slack messages to anyone other than Kamal without his explicit approval
- Never push code without Kamal's approval
- If you can't find the answer in Notion/Slack, say so clearly rather than guessing
- Be direct, no fluff
"""


def process_message(inbox_file: Path) -> bool:
    """Process one inbox message. Returns True on success."""
    try:
        data = json.loads(inbox_file.read_text())
    except json.JSONDecodeError as e:
        log(f"ERROR: malformed JSON in {inbox_file.name}: {e}")
        mark_error(inbox_file)
        return False

    text = data.get("text", "").strip()
    if not text:
        log(f"SKIP: empty message in {inbox_file.name}")
        mark_done(inbox_file)
        return True

    log(f"Processing: {inbox_file.name} — '{text[:60]}'")

    prompt = build_prompt(data)

    # Load NVM so claude is available
    nvm_source = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'

    cmd = f'{nvm_source} && claude --dangerously-skip-permissions --print -p {json.dumps(prompt)}'

    result = subprocess.run(
        ["bash", "-c", cmd],
        capture_output=True,
        text=True,
        cwd=str(KAMIL_DIR),
        timeout=300,  # 5 min max per message
    )

    if result.returncode != 0:
        log(f"ERROR: claude exited {result.returncode} for {inbox_file.name}")
        log(f"stderr: {result.stderr[:200]}")
        # Leave as unprocessed for retry (don't mark done/error)
        return False

    log(f"OK: processed {inbox_file.name}")
    mark_done(inbox_file)
    return True


def main():
    messages = get_unprocessed_messages()
    if not messages:
        log("No unprocessed messages in inbox.")
        return

    log(f"Found {len(messages)} unprocessed message(s).")
    for inbox_file in messages:
        process_message(inbox_file)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Make it executable**

```bash
chmod +x /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/inbox-processor.py
```

- [ ] **Step 5: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/hooks/inbox-processor.py
git commit -m "feat: add inbox-processor.py stub"
```

---

## Task 2: Create the `kamil` CLI script

**Files:**
- Create: `~/bin/kamil`

- [ ] **Step 1: Ensure ~/bin exists and is in PATH**

```bash
mkdir -p ~/bin
echo $PATH | grep -q "$HOME/bin" && echo "Already in PATH" || echo "Need to add to PATH"
```

If not in PATH, add to `~/.zshrc`:
```bash
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

- [ ] **Step 2: Create ~/bin/kamil**

```bash
cat > ~/bin/kamil << 'SCRIPT'
#!/usr/bin/env bash
# kamil — Send a message to Kamil agent
# Usage: kamil "your message"
#        kamil   (opens $EDITOR for longer messages)

INBOX_DIR="$HOME/kamil-inbox"
mkdir -p "$INBOX_DIR"

# Get message text
if [ $# -eq 0 ]; then
    TMPFILE=$(mktemp /tmp/kamil-message.XXXXXX.txt)
    ${EDITOR:-nano} "$TMPFILE"
    TEXT=$(cat "$TMPFILE")
    rm -f "$TMPFILE"
else
    TEXT="$*"
fi

if [ -z "$TEXT" ]; then
    echo "No message provided. Aborted."
    exit 1
fi

# Detect project from cwd
CWD="$(pwd)"
PROJECT=""
declare -A PROJECT_MAP=(
    ["/home/oye/Documents/taleemabad-core"]="taleemabad-core"
    ["/home/oye/Documents/free_work/personal-agent-v2/repos/taleemabad-cms"]="taleemabad-cms"
    ["/home/oye/Documents/free_work/personal-agent-v2/repos/taleemabad-auth"]="taleemabad-auth"
    ["/home/oye/Documents/free_work/personal-agent-v2/repos/portfolio-website"]="portfolio-website"
)
for path in "${!PROJECT_MAP[@]}"; do
    if [[ "$CWD" == "$path"* ]]; then
        PROJECT="${PROJECT_MAP[$path]}"
        break
    fi
done

# Write inbox file
TIMESTAMP=$(date +"%Y-%m-%dT%H-%M-%S")
INBOX_FILE="$INBOX_DIR/${TIMESTAMP}-cli.json"

cat > "$INBOX_FILE" << EOF
{
  "id": "${TIMESTAMP}-cli",
  "source": "cli",
  "text": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$TEXT"),
  "cwd": "$CWD",
  "project": "$PROJECT",
  "timestamp": "$(date -Iseconds)"
}
EOF

echo "✓ Message queued for Kamil."
echo "  He'll respond on Slack within 30 min (next loop run)."
echo "  Inbox: $INBOX_FILE"
SCRIPT
```

- [ ] **Step 3: Make it executable**

```bash
chmod +x ~/bin/kamil
```

- [ ] **Step 4: Test it**

```bash
kamil "test message from CLI"
```

Expected output:
```
✓ Message queued for Kamil.
  He'll respond on Slack within 30 min (next loop run).
  Inbox: /home/oye/kamil-inbox/2026-05-18T...-cli.json
```

- [ ] **Step 5: Verify the inbox file looks correct**

```bash
cat ~/kamil-inbox/*.json | python3 -m json.tool
```

Expected: valid JSON with `text`, `source: "cli"`, `cwd`, `project`, `timestamp`

- [ ] **Step 6: Clean up test message**

```bash
rm ~/kamil-inbox/*.json
```

- [ ] **Step 7: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add -A
git commit -m "feat: add kamil CLI script to ~/bin/kamil"
```

---

## Task 3: Extend slack-poller.py to detect @kamil mentions

**Files:**
- Modify: `.claude/hooks/slack-poller.py`

The poller already scans channels every 30min. We need to:
1. Define a Kamil bot user ID (or use a keyword `@kamil` in text)
2. When a message contains `@kamil` or is a DM to Kamil bot — write it to `~/kamil-inbox/`

- [ ] **Step 1: Add KAMIL constants near the top of slack-poller.py (after line 40)**

Open `.claude/hooks/slack-poller.py` and add after the `KAMAL_USER_ID` line:

```python
KAMIL_INBOX_DIR = Path.home() / "kamil-inbox"
KAMIL_TRIGGER_KEYWORDS = ["@kamil", "kamil,", "hey kamil", "kamil:"]
```

- [ ] **Step 2: Add write_to_kamil_inbox function before the `main()` function**

```python
def write_to_kamil_inbox(text: str, source_channel: str, from_id: str, ts: str):
    """Write a message directed at Kamil into the inbox queue."""
    KAMIL_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    safe_ts = ts.replace(".", "-")
    inbox_file = KAMIL_INBOX_DIR / f"{safe_ts}-slack.json"
    if inbox_file.exists():
        return  # already queued
    payload = {
        "id": f"{safe_ts}-slack",
        "source": "slack",
        "text": text,
        "cwd": "",
        "project": "",
        "channel": source_channel,
        "from_id": from_id,
        "timestamp": datetime.now().isoformat(),
    }
    inbox_file.write_text(json.dumps(payload, indent=2))
    print(f"[slack-poller] Kamil inbox: queued message from {from_id} in {source_channel}", file=sys.stderr)
```

- [ ] **Step 3: Add @kamil detection inside poll_channel(), after the `if not is_relevant: continue` block**

Find this section in `poll_channel()`:

```python
        if not is_relevant:
            continue

        msg_type, status = classify_message(text, from_id)
```

Add kamil detection right before `msg_type, status = ...`:

```python
        # Kamil inbox — if message is directed at Kamil, queue it
        text_lower_check = text.lower()
        if any(kw in text_lower_check for kw in KAMIL_TRIGGER_KEYWORDS):
            write_to_kamil_inbox(text, channel_name, from_id, ts)
            # Still continue to log in Notion Slack Inbox as normal

        msg_type, status = classify_message(text, from_id)
```

- [ ] **Step 4: Verify the change looks correct**

```bash
grep -n "kamil\|KAMIL\|write_to_kamil" /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/slack-poller.py
```

Expected: lines showing KAMIL_INBOX_DIR, KAMIL_TRIGGER_KEYWORDS, write_to_kamil_inbox, and the detection call.

- [ ] **Step 5: Syntax check**

```bash
python3 -m py_compile /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/slack-poller.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/hooks/slack-poller.py
git commit -m "feat: detect @kamil mentions in slack-poller, write to inbox"
```

---

## Task 4: Extend kamil-daily.sh to call inbox-processor

**Files:**
- Modify: `kamil-daily.sh`

- [ ] **Step 1: Open kamil-daily.sh and find the step comments**

```bash
grep -n "Step\|python3\|echo" /home/oye/Documents/free_work/personal-agent-v2/kamil-daily.sh | head -20
```

- [ ] **Step 2: Add inbox-processor call as Step 0, before Step 1 (Slack poller)**

Find this block in `kamil-daily.sh`:

```bash
# ── Step 1: Run Slack poller first ─────────────────────────────────────────
echo "[$TIMESTAMP] Running Slack poller..." >> "$LOG_FILE"
python3 "$KAMIL_DIR/.claude/hooks/slack-poller.py" >> "$LOG_FILE" 2>&1 || true
```

Add before it:

```bash
# ── Step 0: Process any queued inbox messages ──────────────────────────────
echo "[$TIMESTAMP] Processing inbox messages..." >> "$LOG_FILE"
python3 "$KAMIL_DIR/.claude/hooks/inbox-processor.py" >> "$LOG_FILE" 2>&1 || true
```

- [ ] **Step 3: Verify the change**

```bash
grep -n "Step 0\|inbox-processor\|Step 1\|slack-poller" /home/oye/Documents/free_work/personal-agent-v2/kamil-daily.sh
```

Expected: Step 0 (inbox-processor) appears before Step 1 (slack-poller).

- [ ] **Step 4: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add kamil-daily.sh
git commit -m "feat: call inbox-processor at start of kamil daily loop"
```

---

## Task 5: End-to-end test

- [ ] **Step 1: Send a test message via CLI**

```bash
kamil "what are the open PRs in taleemabad-core right now?"
```

Expected: message queued confirmation + file in `~/kamil-inbox/`

- [ ] **Step 2: Manually trigger inbox-processor to verify it runs**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 .claude/hooks/inbox-processor.py
```

Expected: log output showing message being processed, Claude session starting.

- [ ] **Step 3: Check the log**

```bash
tail -30 /tmp/kamil-inbox-processor.log
```

Expected: entries showing message found, claude invoked, marked done.

- [ ] **Step 4: Check inbox is marked done**

```bash
ls ~/kamil-inbox/
```

Expected: file renamed to `.json.done`

- [ ] **Step 5: Check Slack DM from Kamil**

Open Slack and verify a DM arrived from Kamil with the answer.

- [ ] **Step 6: Check Notion Work Log**

Open Notion → Work Log database → verify entry "Kamal asked: what are the open PRs..."

---

## Task 6: Verify cron is set up

- [ ] **Step 1: Check existing cron**

```bash
crontab -l
```

Expected: see the `0 8 * * *` entry for `kamil-daily.sh`.

If NOT present:

- [ ] **Step 2: Add cron entry**

```bash
(crontab -l 2>/dev/null; echo "0 8 * * * /home/oye/Documents/free_work/personal-agent-v2/kamil-daily.sh >> /tmp/kamil-daily.log 2>&1") | crontab -
```

- [ ] **Step 3: Verify**

```bash
crontab -l | grep kamil
```

Expected: the cron entry is listed.
