---
description: Run one orchestrator tick — poll Notion/Slack/GitHub, dispatch subagents. Use /loop orchestrate for recurring execution.
---

# /orchestrate — Team Orchestrator Tick

Runs a single tick of Varys's team orchestrator. Use with `/loop 270` for continuous operation.

**Never change the 270s interval without asking Shoaib.**

## Tick Sequence

Execute these steps IN ORDER. If any step fails: release tick lock, stop, do NOT update last_sync_at.

### Step 1 — Acquire tick lock + read last_sync_at

```bash
python3 .claude/hooks/varys_harness_db.py
```

Actually run this Python inline:

```python
import sys
sys.path.insert(0, '.claude/hooks')
from varys_harness_db import get_db, acquire_tick_lock, get_last_sync_at

db = get_db()
if not acquire_tick_lock(db, 'orchestrate-tick'):
    print("Tick already running — exiting")
    sys.exit(0)
last_sync_at = get_last_sync_at(db)
print(f"Tick started. last_sync_at={last_sync_at}")
```

If lock not acquired: **stop here**. Another tick is running.

### Step 2 — Poll Notion Harness DB

```bash
python3 .claude/hooks/poll-harness-notion.py
```

If exit code != 0: **release lock, stop, do not update last_sync_at**.

### Step 3 — Poll Engineering Slack channels

```bash
python3 .claude/hooks/poll-eng-slack.py
```

If exit code != 0: **release lock, stop**.

### Step 4 — Poll taleemabad-core GitHub PRs

```bash
python3 .claude/hooks/poll-taleemabad-github.py
```

If exit code != 0: **release lock, stop**.

### Step 4.5 — Poll proactive Slack channels

```bash
python3 .claude/hooks/poll-proactive-slack.py
```

If exit code != 0: **release lock, stop**.

### Step 5 — Dispatch subagents

```bash
python3 .claude/hooks/orchestrator-dispatch.py
```

Dispatcher handles its own failures per context_key — this step always succeeds at the tick level.

### Step 5.5 — Run gap watcher

```bash
python3 .claude/hooks/varys-gap-watcher.py
```

Gap watcher monitors for stalled contexts and escalates timeouts. Always succeeds at the tick level.

### Step 6 — Update last_sync_at + release lock

```python
from varys_harness_db import set_last_sync_at, release_tick_lock
from datetime import datetime, timezone

set_last_sync_at(db, datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
release_tick_lock(db)
db.close()
print("Tick complete.")
```

## Rules

- **270s interval** — never change
- **Tick atomicity** — any poller failure = abort entire tick, do not update last_sync_at
- **context_key** — always a Notion ticket entity ID (never Slack ts or PR number)
- **Status=Done** — always written LAST in any Notion update
- See `.claude/rules/orchestrator.md` for full rules
