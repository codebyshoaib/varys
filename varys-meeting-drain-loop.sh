#!/bin/bash
# varys-meeting-drain-loop.sh — drain meeting_queue one job at a time, every 30s.
# Meeting workers are CPU-heavy (WhisperX) so we run one job at a time (no concurrency).
# Skips this tick if an active recording is in progress (avoids disk/CPU contention).
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS="$REPO/.claude/hooks"
WORKER="$HOOKS/meeting-worker.py"
LOG=/tmp/varys-meeting-drain.log
ACTIVE_RECORDING="$HOME/.varys-harness/active_recording.json"

exec 9>/tmp/varys-meeting-drain-loop.lock
if ! flock -n 9; then
    echo "[meeting-drain-loop] $(date -Is) already running; exit" >>"$LOG"
    exit 0
fi

echo "[meeting-drain-loop] $(date -Is) started (30s interval)" >>"$LOG"
while true; do
    # Skip this tick if a recording is in progress — avoid competing for CPU/disk
    if [ -f "$ACTIVE_RECORDING" ]; then
        echo "[meeting-drain-loop] $(date -Is) active recording in progress, skipping tick" >>"$LOG"
        sleep 30
        continue
    fi

    # Dequeue one pending job ID from meeting_queue
    JOB_ID=$(python3 -c "
import sys
sys.path.insert(0, '$HOOKS')
from varys_harness_db import get_db, dequeue_pending_meeting
db = get_db()
row = dequeue_pending_meeting(db)
if row:
    print(row[0])
" 2>>"$LOG")

    if [ -n "$JOB_ID" ]; then
        echo "[meeting-drain-loop] $(date -Is) processing job $JOB_ID" >>"$LOG"
        python3 "$WORKER" --job-id "$JOB_ID" >>"$LOG" 2>&1
        echo "[meeting-drain-loop] $(date -Is) job $JOB_ID done (rc=$?)" >>"$LOG"
    fi

    sleep 30
done
