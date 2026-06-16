#!/bin/bash
# varys-orchestrator-loop.sh — agent-free 270s orchestrator heartbeat.
#
# Replaces `/loop 270s` (one LLM agent turn per tick — the token furnace) with a
# pure-Python tick. The LLM is only invoked downstream by orchestrator-dispatch.py
# when events are actually pending. Interval = 270s per orchestrator.md rule 7 —
# do NOT change without asking Shoaib. Started @reboot via crontab.snapshot.txt;
# pgrep guard makes a second start a no-op.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TICK="$REPO/.claude/hooks/varys-tick.py"
LOG=/tmp/varys-orchestrator-tick.log

# Single-instance guard via flock (race-free; auto-released when the process dies).
# pgrep-counting was wrong here: the launching shell's command line contains the
# script name and self-counts as a second instance.
exec 9>/tmp/varys-orchestrator-loop.lock
if ! flock -n 9; then
    echo "[loop] $(date -Is) already running; exit" >>"$LOG"
    exit 0
fi

echo "[loop] $(date -Is) agent-free orchestrator loop started (270s)" >>"$LOG"
while true; do
    python3 "$TICK" >>"$LOG" 2>&1
    sleep 270
done
