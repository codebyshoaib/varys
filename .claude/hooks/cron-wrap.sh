#!/bin/bash
# Usage: cron-wrap.sh <component> <command...>
# Runs the command, times it, captures rc + stderr tail, emits a structured cron_run event.
COMPONENT="$1"; shift
START=$(date +%s%3N)
ERRFILE=$(mktemp)
"$@" >"$ERRFILE" 2>&1
RC=$?
END=$(date +%s%3N)
DUR=$((END - START))
TAIL=$(tail -c 800 "$ERRFILE" | tr '\n' ' ' | tr -d '"')
rm -f "$ERRFILE"
STATUS="ok"; [ "$RC" -ne 0 ] && STATUS="error"
cd "$(dirname "$0")/.."  2>/dev/null
python3 -c "
import sys; sys.path.insert(0,'.claude/hooks')
import kamil_log as k
k.klog_cron('$COMPONENT', status='$STATUS', duration_ms=$DUR, rc=$RC, error='''$TAIL'''[:500])
" 2>/dev/null
exit $RC
