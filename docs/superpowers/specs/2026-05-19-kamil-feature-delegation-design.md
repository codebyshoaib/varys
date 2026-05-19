# Design: Kamil Feature Delegation via Subprocess

**Date**: 2026-05-19  
**Status**: Approved  
**File to change**: `.claude/hooks/kamil-task-interceptor.py`

## Problem

When Kamal says "Kamil, work on taleemabad-core — [task]", Kamil skips the `/feature` pipeline entirely and starts reading files and writing code directly. The system message in the interceptor hook tells Kamil to run `/feature` first, but this is advisory — Claude ignores it and dives in.

## Solution

The interceptor hook mechanically runs `/feature <slug>` as a blocking subprocess before returning the system message to Claude. Kamil wakes up to a completed `/feature` run. The delegation is enforced at the hook level, not the instruction level.

## Architecture

### Subprocess call (added to `kamil-task-interceptor.py`)

After git branch setup, before building the system message:

```python
feature_result = run_feature(task_slug)
```

```python
def run_feature(slug):
    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "-p", f"/feature {slug}"],
            cwd=TALEEMABAD_CORE,
            timeout=1800,
            capture_output=True,
            text=True
        )
        return {"ok": result.returncode == 0, "output": result.stdout[-2000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "timed out after 30 minutes"}
    except Exception as e:
        return {"ok": False, "output": str(e)}
```

### System message change

**Before (advisory):**
> "Your first and only action right now: run `/feature {slug}`"

**After (confirmatory):**
> "/feature {slug} has already run. Feature folder: `.claude/features/YYYY-MM-DD-{slug}/`  
> Read research.md and plan.md as engineering lead. Then run /develop {slug}.  
> Do NOT grep or read other files. The research is done."

On failure:
> "/feature {slug} may not have completed cleanly (exit: {code}). Check `.claude/features/` in taleemabad-core. If the folder exists, review it. If not, run `/feature {slug}` manually from inside taleemabad-core."

### Data flow

```
Kamal types: "Kamil, work on taleemabad-core — [task]"
  → hook fires (UserPromptSubmit)
  → extract task, slugify
  → create Notion entry
  → git checkout develop && pull && create branch
  → subprocess: claude -p "/feature {slug}" in taleemabad-core  [BLOCKS ~20min]
  → subprocess completes
  → send Slack DM (includes feature folder path)
  → inject system message (confirmatory, not directive)
  → Kamil wakes up, reads research.md + plan.md, runs /develop
```

## Error handling

| Scenario | Behavior |
|----------|----------|
| `/feature` exits 0 | System message: "done, review it" |
| `/feature` exits non-zero | System message: "may have failed, check the folder" |
| Timeout (>30min) | System message: "timed out, check folder or re-run manually" |
| `claude` binary not found | Falls back to old advisory message, logs warning |

## What doesn't change

- Notion entry creation
- Git branch setup  
- Slack DM
- `/develop` → `/test` → `/fix` → `/deliver` pipeline — Kamil owns these

## Success criteria

- Kamal types "Kamil, work on taleemabad-core — X" and the hook blocks until `/feature` finishes
- Kamil's first message is a review of `research.md` and `plan.md`, not file exploration
- If `/feature` fails, Kamil is told exactly where to look and what to do
