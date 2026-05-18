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
