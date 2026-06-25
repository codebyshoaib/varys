# Blindspot

> Asks the question the self-assessment forgot to ask.
> Use after self-assess or analyze-trajectory returns "all good" — that's often
> the moment a real blindspot is hiding.

## The Problem This Skill Solves

Self-assessment has a structural flaw: you look where you know to look.
If you've never tried to use a feature, you can't notice it's broken.
If a cron silently fails, it never appears in your trajectory.
If a tool is unused because it's hard to reach, no learning captures that.

Blindspot forces you to look in the places you systematically skip.

## When to use

- Self-assessment found nothing actionable ("codebase looks healthy")
- Three consecutive evolution runs produced minor/cosmetic improvements
- A pattern in `active_learnings.md` says "I keep missing X" but X never shows up in trajectory
- Shoaib reports a problem you didn't flag

## The Five Blindspot Lenses

Apply each one. Most will come up empty — that's fine. You need the one that doesn't.

### Lens 1: Crons that never emit telemetry

```bash
# What's wired?
crontab -l

# For each cron: when did it last emit a telemetry event?
jq -r 'select(.component != null) | .component' ~/.varys-harness/telemetry.jsonl | sort | uniq -c | sort -rn | head -20
```

A component that appears in crontab but NOT in telemetry hasn't run successfully in a while — or its logging is broken. Either is a blindspot.

### Lens 2: Skills never invoked

```bash
ls .claude/skills/varys/
# Cross-ref against session logs to see which skills Shoaib actually invokes
grep -r "invoke\|/varys\|skill:" vault/logs/ 2>/dev/null | grep -oP '(?<=skills/varys/)[^.]+' | sort | uniq -c | sort -rn
```

A skill nobody invokes is either: (a) unknown — add it to skills-router.md, or (b) not useful — archive it. Either way it's a gap.

### Lens 3: Hooks with no tests

```bash
ls .claude/hooks/*.py | grep -v test_ | while read f; do
  stem=$(basename "$f" .py)
  if [ ! -f ".claude/hooks/test_${stem}.py" ]; then
    echo "UNTESTED: $f"
  fi
done
```

An untested hook can break silently. Note any that look load-bearing.

### Lens 4: Rules nobody reads

```bash
# Rules loaded in session-start.py
grep -r "rules/" .claude/hooks/session-start.py 2>/dev/null

# Rules that exist
ls .claude/rules/
```

A rule file that's NOT loaded by session-start is dead letter. Check if it should be surfaced.

### Lens 5: Failures with no learning

```bash
# Failures in the last 30 days
python3 -c "
import json, datetime
from pathlib import Path
cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
for line in Path('.beads/failures.jsonl').read_text().splitlines():
    if not line.strip(): continue
    e = json.loads(line)
    ts = e.get('ts','')
    if ts and ts > cutoff.strftime('%Y-%m-%d'):
        print(ts[:10], e.get('incident','')[:80])
" 2>/dev/null | head -20

# Learnings added in the same period
python3 -c "
import json
from pathlib import Path
for line in Path('memory/learnings.jsonl').read_text().splitlines():
    if not line.strip(): continue
    e = json.loads(line)
    print(e.get('date','')[:10], e.get('title','')[:60])
" 2>/dev/null | sort | tail -20
```

A failure cluster with no corresponding learning means the reflect loop missed it. Flag for `varys-reflect.py` to pick up.

## Output

After each lens, note: (a) what you found, (b) severity (high/medium/low/skip).
Prioritize by: broken-and-silent > unused-but-load-bearing > stale-documentation.

Pick ONE finding and either:
- Fix it now if it's inside the fence and trivial
- Open a bead if it needs a proper evolution run
- Update `skills-router.md` if it's a discoverability gap
