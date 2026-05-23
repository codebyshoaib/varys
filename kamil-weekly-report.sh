#!/usr/bin/env bash
# kamil-weekly-report.sh — Kamil's weekly Slack message to Kamal
# Runs every Monday at 9am via cron
# After 1 week of learning, proposes things it can handle
#
# Cron entry:
#   0 9 * * 1 /home/oye/Documents/free_work/personal-agent-v2/kamil-weekly-report.sh >> /tmp/kamil-weekly.log 2>&1

set -euo pipefail

KAMIL_DIR="/home/oye/Documents/free_work/personal-agent-v2"
LOG_FILE="/tmp/kamil-weekly.log"
DATE=$(date +%Y-%m-%d)
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")

echo "[$TIMESTAMP] Kamil weekly report starting..." >> "$LOG_FILE"

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

if ! command -v claude &>/dev/null; then
    echo "[$TIMESTAMP] ERROR: claude not found" >> "$LOG_FILE"
    exit 1
fi

PROMPT="You are Kamil, Kamal's autonomous personal agent. Today is $DATE — your weekly report day.

Review everything you've learned this week from Notion (Work Log, Slack Inbox, Team People, My PRs, Harness) and compose a weekly message to send to Kamal on Slack.

The message must:
1. Start with: 'Hey Kamal — Kamil weekly report for the week of $DATE'
2. Summarize: what you learned about the codebase this week
3. Summarize: what each key teammate worked on (Shoaib, Hammad, Laraib, Fatima, Usman, Mah Noor)
4. List: things you noticed that may need attention (PRs stuck, issues opened, teammates blocked)
5. Propose: 2-3 specific things you are confident you can handle autonomously this coming week
   - For EACH proposal: describe exactly what you'd do, why you're confident, and what approval you need
   - Example: 'I can create a GitHub issue for the CMS memory spike. I have the full context from Slack. I will NOT push any code — just open the issue with full description. Do you approve?'
6. Ask: 'Reply YES to each item you approve. I will not act until you confirm.'

IMPORTANT rules for the message:
- Be specific, not vague. Show you actually read things.
- Keep it under 400 words total.
- Be direct like Kamal. No fluff.
- Sign off as 'Kamil 🤖'

After composing the message, send it to Kamal via Slack DM (Kamal's Slack user ID: U0AV1DX3WSE).
Use the Slack MCP to send the message.

Notion Brain page ID: 364d8747b3b1813d8ac8c248800f0a4d"

echo "[$TIMESTAMP] Composing and sending weekly report..." >> "$LOG_FILE"

claude \
    --dangerously-skip-permissions \
    --print \
    -p "$PROMPT" \
    >> "$LOG_FILE" 2>&1 || {
        echo "[$TIMESTAMP] Claude session ended with exit code $?" >> "$LOG_FILE"
    }

echo "[$TIMESTAMP] Kamil weekly report complete." >> "$LOG_FILE"

# ── Humor profile self-review ──────────────────────────────────────────────
echo "[$TIMESTAMP] Running humor profile review..." >> "$LOG_FILE"

HUMOR_PROMPT="You are Kamil. Review your humor performance from this week.

Read /tmp/kamil-humor-log.jsonl — it contains JSON lines: {ts, prompt, response, reaction}

Analyze the patterns:
- Which types of humor got positive reactions (Kamal laughed, said 'haha', sent 😂, or just acted on it)?
- Which missed (Kamal re-explained, ignored, or seemed confused)?
- What style of humor works best for Kamal?

Then:
1. Update vault/memory/kamil_humor_profile.md with:
   - What works (with examples)
   - What to avoid
   - 2-3 rules for future humor attempts
   Format: keep it short and opinionated, like notes to yourself

2. Write a one-line entry to Notion Learning Log DB (0b71db855f914d18ac6d97c0f77fc21e):
   Title: 'Humor Review — $DATE'
   Content: the updated humor rules

If the humor log is empty or doesn't exist, just note 'No humor interactions this week' and skip.

Do it now. No explanation needed."

claude \
    --dangerously-skip-permissions \
    --print \
    -p "$HUMOR_PROMPT" \
    >> "$LOG_FILE" 2>&1 || true

echo "[$TIMESTAMP] Humor review complete." >> "$LOG_FILE"

# ── Portfolio CV intelligence update ──────────────────────────────────────────
echo "[$TIMESTAMP] Running portfolio CV intelligence..." >> "$LOG_FILE"
python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/portfolio-updater.py >> "$LOG_FILE" 2>&1 || true
echo "[$TIMESTAMP] Portfolio update complete." >> "$LOG_FILE"
