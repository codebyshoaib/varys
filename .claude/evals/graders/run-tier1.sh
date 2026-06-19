#!/bin/bash
# Tier-1 deterministic eval grader. Exit 0 = pass, 1 = fail. No LLM, $0.
cd "$(dirname "$0")/../../.." || exit 1
FAIL=0

echo "== Tier-1: eval route files exist =="
for y in .claude/evals/tasks/*.yaml; do
  route=$(python3 -c "import yaml,sys; print(yaml.safe_load(open('$y'))['expected']['route'])" 2>/dev/null)
  if [ -n "$route" ] && [ -e "$route" ]; then echo "  OK $route"; else echo "  FAIL missing route: $route ($y)"; FAIL=1; fi
done

echo "== Tier-1: markdown frontmatter (rules/standards/memory) =="
for f in .claude/rules/*.md .claude/standards/*.md vault/memory/varys_personality.md; do
  [ -f "$f" ] || continue
  if head -1 "$f" | grep -q '^---'; then echo "  OK fm $f"; else echo "  FAIL no frontmatter: $f"; FAIL=1; fi
done

echo "== Tier-1: CLAUDE.md <=150 lines =="
L=$(wc -l < CLAUDE.md)
if [ "$L" -le 150 ]; then echo "  OK CLAUDE.md $L lines"; else echo "  FAIL CLAUDE.md $L > 150"; FAIL=1; fi

echo "== Tier-1: rules line limits (<=300) =="
for f in .claude/rules/*.md; do
  L=$(wc -l < "$f"); if [ "$L" -le 300 ]; then echo "  OK $f ($L)"; else echo "  FAIL $f $L > 300"; FAIL=1; fi
done

echo "== Tier-1: freshness (rules within 31 days of last_verified) =="
python3 - <<'PY' || FAIL=1
import glob, datetime, re, sys
today = datetime.date.today()
bad=0
for f in glob.glob(".claude/rules/*.md"):
    m=re.search(r'last_verified:\s*(\d{4}-\d{2}-\d{2})', open(f).read())
    if not m: print(f"  FAIL no last_verified: {f}"); bad=1; continue
    d=datetime.date.fromisoformat(m.group(1))
    age=(today-d).days
    print(f"  {'OK' if age<=31 else 'STALE'} {f} ({age}d)")
    if age>31: bad=1
sys.exit(bad)
PY

if [ "$FAIL" -eq 0 ]; then echo "TIER-1: PASS"; else echo "TIER-1: FAIL"; fi
exit $FAIL
