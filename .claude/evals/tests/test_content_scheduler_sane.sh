#!/bin/bash
# Lock-in test: content-scheduler.py must compile, and nlm-delete must only appear on
# guarded empty/failed-notebook paths (not fire indiscriminately). Catches churn-damage. $0.
cd "$(dirname "$0")/../../.." || exit 1
F=.claude/hooks/content-scheduler.py
FAIL=0

python3 -m py_compile "$F" 2>/dev/null && echo "OK compiles" || { echo "FAIL: $F does not compile"; FAIL=1; }

# Every `nlm delete notebook --confirm` must be within ~5 lines of a 0-sources / failed /
# empty guard. Heuristic: each delete line should have a nearby 'count == 0' / 'failed' /
# 'no insights' / 'has 0 sources' marker.
DEL_LINES=$(grep -n 'delete.*notebook.*--confirm' "$F" | cut -d: -f1)
for ln in $DEL_LINES; do
  start=$((ln-10)); [ "$start" -lt 1 ] && start=1
  ctx=$(sed -n "${start},${ln}p" "$F")
  # A guarded delete sits under a failure/empty condition: 0 sources, failed research,
  # no insights, OR an `else:` branch of an `if nlm_insights/had_sources` success check.
  if echo "$ctx" | grep -qiE '0 sources|count == 0|final_count == 0|no insights|research failed|empty|deleting|^\s*else:|not .*insights'; then
    echo "OK guarded delete at line $ln"
  else
    echo "FAIL: unguarded nlm-delete at line $ln (possible churn-damage)"; FAIL=1
  fi
done

[ "$FAIL" -eq 0 ] && echo "SCHEDULER-SANE: PASS" || echo "SCHEDULER-SANE: FAIL"
exit $FAIL
