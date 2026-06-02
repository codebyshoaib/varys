---
name: taleemabad-core Issues Log
description: Running log of bugs, incidents, and post-mortems
updated: 2026-06-02
---

# Issues Log — taleemabad-core

Log every non-trivial bug here after resolution. Link to the feature folder for full context.

## Format

```
### YYYY-MM-DD — <short title>
- **Severity**: P0 / P1 / P2
- **App**: <django app affected>
- **Symptom**: What Kamil or the team observed
- **Root Cause**: What actually caused it
- **Fix**: What was changed (file + line if applicable)
- **Feature folder**: .claude/features/YYYY-MM-DD-<name>/ (if applicable)
- **Eval added?**: Yes / No
```

---

## Issues

<!-- Add entries below in reverse-chronological order (newest first) -->

## Example Entry (template only)

### YYYY-MM-DD — (example) Dexie race condition on multi-profile sync
- **Severity**: P1
- **App**: coaching / frontend sync layer
- **Symptom**: Coaching observations duplicated after teacher synced on two devices
- **Root Cause**: `api/teachertraining.ts` wrote to two Dexie tables outside a transaction
- **Fix**: Wrapped writes in `db.transaction('rw', [observations, answers], ...)` — see patterns.md
- **Feature folder**: N/A (hotfix)
- **Eval added?**: No
