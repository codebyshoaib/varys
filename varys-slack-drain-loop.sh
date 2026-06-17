#!/bin/bash
# varys-slack-drain-loop.sh — drain slack_queue every 60s.
# Runs independently of the 270s orchestrator tick so Slack mentions
# get picked up within 1 minute regardless of Notion/GitHub polling.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRAIN="$REPO/.claude/hooks/slack-queue-drain.py"
LOG=/tmp/varys-slack-drain.log

exec 9>/tmp/varys-slack-drain-loop.lock
if ! flock -n 9; then
    echo "[drain-loop] $(date -Is) already running; exit" >>"$LOG"
    exit 0
fi

echo "[drain-loop] $(date -Is) started (60s interval)" >>"$LOG"
while true; do
    python3 "$DRAIN" >>"$LOG" 2>&1
    sleep 60
done
