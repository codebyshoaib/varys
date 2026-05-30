# Fix Laptop Freeze — Kamil Cron Resource Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop Kamil's cron scripts from piling up unlimited Claude subprocesses and freezing the laptop every 30 minutes.

**Architecture:** Four targeted surgical edits — one per script — plus a crontab offset. No Ubuntu services touched. No scripts removed. Each fix is independently testable.

**Tech Stack:** Python 3, threading.ThreadPoolExecutor, subprocess semaphore, os.getloadavg(), crontab

---

## Root Cause Summary

At `:00` and `:30` every hour:
- `job-finder.py` spawns **one detached `claude` process per new job found** — no cap, no wait. 10 new jobs = 10 simultaneous Claude processes = ~500 MB RAM spike.
- `slack-poller.py` spawns 1 Claude for self-question with **no load check**.
- `kamil-slack-listener.py` spawns **one raw `threading.Thread` per Slack message** — no pool, no limit.
- All three run at the same minute. Zoom/snap auto-updates can pile on top.

**Result:** 8+ Claude processes simultaneously → OOM kill → laptop freeze.

---

## Files Modified

| File | Change |
|------|--------|
| `.claude/hooks/job-finder.py` | Add `threading.Semaphore(2)` guard around `save_job_to_notion` |
| `.claude/hooks/slack-poller.py` | Add `os.getloadavg()` check before spawning Claude |
| `.claude/hooks/kamil-slack-listener.py` | Replace raw `threading.Thread` message dispatch with `ThreadPoolExecutor(max_workers=2)` |
| `crontab` | Offset `job-finder` to `5,35` so it doesn't collide with `slack-poller` at `:00/:30` |

---

## Task 1 — job-finder.py: Cap parallel Claude spawns to 2

**File:** `.claude/hooks/job-finder.py`

Right now `save_job_to_notion()` calls `subprocess.Popen(["bash", "-c", "claude ..."])` immediately for every qualifying job, with no limit. Fix: a module-level semaphore that allows at most 2 concurrent Popen calls.

- [ ] **Step 1: Read the current save_job_to_notion function**

  Open `.claude/hooks/job-finder.py` and locate `save_job_to_notion` (around line 440). Confirm it calls `subprocess.Popen` directly with no semaphore.

- [ ] **Step 2: Add the semaphore at the top of the file**

  Find the block of module-level constants (after the imports, around line 32 where `SLACK_CONFIG` is defined). Add this line in that block:

  ```python
  # Max 2 Claude subprocesses at a time — prevents OOM freeze on busy job runs
  _NOTION_SEMA = threading.Semaphore(2)
  ```

  Also add `import threading` to the imports if not already present (check line ~19 — it imports `subprocess` but not `threading`).

- [ ] **Step 3: Wrap the Popen call with the semaphore**

  Replace the current `save_job_to_notion` function body. Find this block (around line 463):

  ```python
  subprocess.Popen(
      ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$KAMIL_JOB_PROMPT"'],
      cwd=str(KAMIL_DIR), env=env,
      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
      start_new_session=True,
  )
  ```

  Replace it with:

  ```python
  def _run():
      with _NOTION_SEMA:
          subprocess.Popen(
              ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$KAMIL_JOB_PROMPT"'],
              cwd=str(KAMIL_DIR), env=env,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              start_new_session=True,
          ).wait()

  threading.Thread(target=_run, daemon=True).start()
  ```

  The `.wait()` inside the semaphore means the semaphore slot is held until Claude finishes — so at most 2 Claude processes run at once. Extra jobs queue in daemon threads (cheap — they just sleep on the semaphore).

- [ ] **Step 4: Verify the edit looks correct**

  ```bash
  grep -n "Semaphore\|_NOTION_SEMA\|_run\|Popen" /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/job-finder.py
  ```

  Expected output: semaphore defined, `_run` function wrapping the Popen, `threading.Thread(target=_run` visible.

- [ ] **Step 5: Commit**

  ```bash
  cd /home/oye/Documents/free_work/personal-agent-v2
  git add .claude/hooks/job-finder.py
  git commit -m "fix: cap job-finder Claude spawns to 2 concurrent via semaphore"
  ```

---

## Task 2 — slack-poller.py: Skip Claude spawn when system load is high

**File:** `.claude/hooks/slack-poller.py`

`slack-poller` calls `explore_self_question()` when Slack is quiet. That function blocks for up to 180s running Claude. If the system is already busy (job-finder running, browser open), this pushes it over the edge. Fix: check `os.getloadavg()` and skip if load is high.

- [ ] **Step 1: Find where explore_self_question is called**

  ```bash
  grep -n "explore_self_question\|getloadavg" /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/slack-poller.py
  ```

  You're looking for the call site — something like `explore_self_question(...)` in the main run logic. Note the line number.

- [ ] **Step 2: Add the load guard at the call site**

  Find the line that calls `explore_self_question(...)`. Wrap it with a load check:

  ```python
  load1, _, _ = os.getloadavg()
  if load1 < 2.0:
      explore_self_question(web_client, dm_channel, bot_token)
  else:
      log(f"Skipping self-question — system load too high ({load1:.1f})")
  ```

  `os.getloadavg()` returns (1-min, 5-min, 15-min) load averages. A load of 2.0 on a multi-core machine means the system is genuinely busy. This doesn't require any new import — `os` is already imported.

- [ ] **Step 3: Verify**

  ```bash
  grep -n "getloadavg\|load1\|Skipping self" /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/slack-poller.py
  ```

  Expected: the guard lines visible.

- [ ] **Step 4: Commit**

  ```bash
  cd /home/oye/Documents/free_work/personal-agent-v2
  git add .claude/hooks/slack-poller.py
  git commit -m "fix: skip slack-poller self-question when system load > 2.0"
  ```

---

## Task 3 — kamil-slack-listener.py: Cap message handler threads to 2

**File:** `.claude/hooks/kamil-slack-listener.py`

Right now every incoming Slack message spawns a raw `threading.Thread(target=handle_message, ...)`. No limit. 5 messages in quick succession = 5 Claude processes (240–300s each) = 1.25 GB RAM. Fix: use a `ThreadPoolExecutor(max_workers=2)` so at most 2 messages are processed concurrently; others queue.

- [ ] **Step 1: Find the current imports**

  ```bash
  head -35 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-slack-listener.py
  ```

  Check if `from concurrent.futures import ThreadPoolExecutor` is already imported.

- [ ] **Step 2: Add the import if missing**

  In the imports section (top of file), add:

  ```python
  from concurrent.futures import ThreadPoolExecutor
  ```

- [ ] **Step 3: Create the module-level executor**

  Find the block of module-level constants/globals (where things like `KAMAL_USER_ID`, `KAMAL_DM` are defined). Add:

  ```python
  # Limits concurrent Claude invocations from message handling to 2
  _MSG_EXECUTOR = ThreadPoolExecutor(max_workers=2)
  ```

- [ ] **Step 4: Replace the raw Thread dispatch with executor.submit**

  Find this block (around line 589, the main message dispatch at the bottom of the event handler):

  ```python
  threading.Thread(
      target=handle_message,
      args=(clean, thread_history, web, channel, thread_ts, source,
            sender_id, sender_name, is_third_party, is_dm),
      daemon=True,
  ).start()
  ```

  Replace it with:

  ```python
  _MSG_EXECUTOR.submit(
      handle_message,
      clean, thread_history, web, channel, thread_ts, source,
      sender_id, sender_name, is_third_party, is_dm,
  )
  ```

  The executor queues excess messages instead of spawning unbounded threads. The 2-worker limit means at most 2 Claude processes run simultaneously from message handling.

- [ ] **Step 5: Verify**

  ```bash
  grep -n "ThreadPoolExecutor\|_MSG_EXECUTOR\|executor.submit\|MSG_EXECUTOR.submit" /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-slack-listener.py
  ```

  Expected: executor defined at module level, `.submit(` call replacing `.start()`.

- [ ] **Step 6: Restart the listener so changes take effect**

  The listener is a daemon started `@reboot`. Kill the current one and restart:

  ```bash
  pkill -f kamil-slack-listener.py
  sleep 2
  nohup python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-slack-listener.py >> /tmp/kamil-slack-listener.log 2>&1 &
  sleep 3
  tail -5 /tmp/kamil-slack-listener.log
  ```

  Expected: last lines show "Connected" or "Listening".

- [ ] **Step 7: Commit**

  ```bash
  cd /home/oye/Documents/free_work/personal-agent-v2
  git add .claude/hooks/kamil-slack-listener.py
  git commit -m "fix: cap slack-listener message handler to 2 concurrent threads via ThreadPoolExecutor"
  ```

---

## Task 4 — Stagger crontab: offset job-finder by 5 minutes

**Crontab**

Both `slack-poller` and `job-finder` run at `*/30` — they fire at exactly the same minute (`:00` and `:30`). Combined with self-healer at `*/10`, you get a triple pile-up. Fix: shift job-finder to `:05` and `:35`.

- [ ] **Step 1: View current crontab**

  ```bash
  crontab -l
  ```

  Confirm the job-finder line reads `*/30 * * * *`.

- [ ] **Step 2: Edit crontab**

  ```bash
  crontab -e
  ```

  Find this line:
  ```
  */30 * * * * python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/job-finder.py >> /tmp/kamil-jobs.log 2>&1
  ```

  Change `*/30` to `5,35`:
  ```
  5,35 * * * * python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/job-finder.py >> /tmp/kamil-jobs.log 2>&1
  ```

  Save and exit.

- [ ] **Step 3: Verify**

  ```bash
  crontab -l | grep job-finder
  ```

  Expected output:
  ```
  5,35 * * * * python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/job-finder.py >> /tmp/kamil-jobs.log 2>&1
  ```

- [ ] **Step 4: Also add `nice -n 15` to both job-finder and slack-poller**

  `nice -n 15` tells the OS to deprioritize these cron processes. Your browser and IDE will always get CPU first.

  Edit crontab again (`crontab -e`) and update both lines:

  ```
  */30 * * * * nice -n 15 python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/slack-poller.py >> /tmp/kamil-slack.log 2>&1
  5,35 * * * * nice -n 15 python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/job-finder.py >> /tmp/kamil-jobs.log 2>&1
  */10 * * * * nice -n 15 python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-self-healer.py >> /tmp/kamil-self-healer.log 2>&1
  ```

- [ ] **Step 5: Verify final crontab**

  ```bash
  crontab -l
  ```

  Confirm `nice -n 15` is on all three cron jobs and job-finder reads `5,35`.

---

## Task 5 — Smoke test: verify fixes work at next cron cycle

- [ ] **Step 1: Watch cron fire at next :05 or :35**

  ```bash
  watch -n 5 'ps aux | grep -E "[c]laude|[j]ob-finder|[s]lack-poller" | wc -l'
  ```

  Wait for the next `:05` or `:35` minute. You should see at most 3-4 processes — not 8+.

- [ ] **Step 2: Check system load during the run**

  ```bash
  watch -n 2 'uptime && ps aux --sort=-%cpu | head -8'
  ```

  Load average should stay under 3.0 during cron runs. Before the fix it would spike to 6+.

- [ ] **Step 3: Check job-finder log for semaphore behavior**

  ```bash
  tail -f /tmp/kamil-jobs.log
  ```

  Jobs should still be saved to Notion — just queued if > 2 at once. Verify Notion Job Tracker gets new entries.

- [ ] **Step 4: Check slack-listener is running with pool**

  ```bash
  tail -5 /tmp/kamil-slack-listener.log
  ```

  Should show "Connected" and no crash. Send a test DM to Kamil and verify it still responds.

---

## Expected Outcome

| Before | After |
|--------|-------|
| 8+ Claude processes at :00/:30 | Max 4 Claude processes total (2 job-finder + 1 poller + 1 listener handler) |
| job-finder + slack-poller collide every cycle | 5-minute gap between them |
| Cron at normal priority competing with browser | `nice -n 15` — OS yields to your active work |
| slack-listener unbounded threads | 2-worker pool, excess messages queue |
| Laptop freeze ~every 30 min | Clean runs, no freeze |
