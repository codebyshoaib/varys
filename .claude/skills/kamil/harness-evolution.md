# Harness Evolution

> How to improve the system itself. Read when detecting a recurring pattern.
> Propose improvements to Kamal — never apply without approval.

## Core Rules
- Detect patterns before proposing. 3+ occurrences = propose a fix.
- Never apply changes to the harness without Kamal's explicit approval.
- Every proposal goes to Kamal via Slack DM: what / why / what changes.
- Log all proposals in the "Proposed Improvements Log" section below.

## CLAUDE.md Improvement Patterns
- Rule keeps being violated → too vague, rewrite with an example
- Context repeated 3+ sessions → extract to rules/ file
- CLAUDE.md hits line limit → audit stale rules, move to vault/

## Notion DB Improvements
- Same query fails 2+ times → DB missing a property or filter
- Status transitions ambiguous → add new status value + document
- Data lost between sessions → add Date or Rich Text field

## Memory Architecture
- Same fact looked up 3+ times → belongs in vault/memory/
- Memory file not read in 30 days → archive or delete
- Two files contradict → reconcile immediately

## Skill File Improvements
- Skill ignored (too long) → split, keep each file < 80 lines
- Skill has no "What to Avoid" → hasn't been tested enough yet
- Skill works perfectly every time → promote core rules to CLAUDE.md

## Hook & Poller Improvements
- Poller misses events → tighten filter or increase frequency
- Hook fires on wrong events → add guard condition
- Same fix applied manually 2+ times → automate as hook

## What NOT to Touch Without Asking Kamal
- harness.db schema changes
- settings.json hook wiring
- Any file affecting the tick loop
- Deleting any rule or memory file

## SkillHound Auto-Discovery

When a capability gap is logged 3+ times (via kamil-gap-watcher.py), before proposing to build from scratch:

1. **Search SkillHound first:**
```bash
curl -s "https://www.skillhound.ai/api/search?q=<gap_topic>&limit=5" 2>/dev/null || \
  echo "Manual search: https://www.skillhound.ai/?q=<gap_topic>"
```

2. **If a skill exists (★ > 10):** fetch it and install:
```bash
# Find the raw file on GitHub
curl -s "https://api.github.com/repos/<owner>/<repo>/git/trees/main?recursive=1" | \
  python3 -c "import json,sys; [print(i['path']) for i in json.load(sys.stdin).get('tree',[]) if 'SKILL' in i['path'].upper()]"

# Fetch and install
curl -s "https://raw.githubusercontent.com/<owner>/<repo>/main/<path>" \
  > .claude/skills/kamil/<skill-name>.md
```

3. **If nothing good exists:** build it using `skill-creator` skill, then publish to GitHub so it appears on SkillHound.

4. **DM Kamal** with: "Found skill `<name>` on SkillHound (★X). Installed. Gap closed."

**SkillHound URL:** https://www.skillhound.ai
**Already installed from SkillHound:**
- [2026-06-05] code-review-excellence (wshobson/agents ★36K)
- [2026-06-05] database-migration (wshobson/agents ★36K)
- [2026-06-05] github-pr-review (ComeOnOliver/skillshub ★46)

## Proposed Improvements Log
<!-- append: [date] what / why / status (proposed|approved|applied) -->
