#!/bin/bash
# varys-learn.sh — Nightly auto-learning loop. Runs at 2am via cron.
# Queries Axiom for patterns, proposes harness improvements, writes to Notion.
#
# Cron: 0 2 * * * /home/oye/Documents/free_work/personal-agent-v2/varys-learn.sh >> /tmp/varys-learn.log 2>&1

set -e
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

VARYS_DIR="$(cd "$(dirname "$0")" && pwd)"
AXIOM_TOKEN=$(grep AXIOM_TOKEN ~/.claude/hooks/.axiom | cut -d= -f2)
AXIOM_DATASET="varys-logs"

echo "[varys-learn] Starting at $(date)"

claude --dangerously-skip-permissions --print -p "$(cat <<'PROMPT'
You are Varys — Shoaib's autonomous AI agent. This is your nightly self-improvement run.
People Intelligence DB: 380902248f3d81e9a877c9ac28a982c5

## YOUR JOB
Query Axiom for patterns in the last 7 days, find problems, fix them.

## AXIOM QUERY (use WebFetch or Bash to call the API)
Axiom APL endpoint: https://api.axiom.co/v1/datasets/varys-logs/query
Token: from ~/.claude/hooks/.axiom (AXIOM_TOKEN field)
Header: Authorization: Bearer <token>

Run these APL queries:

1. **Stale socket rate:**
   | summarize count() by bin_auto(_time) | where event == "socket_stale"

2. **Slow Claude calls (>60s):**
   | where event == "claude_call" and latency_s > 60 | summarize count(), avg(latency_s) by context

3. **Error rate by context:**
   | where event == "error" | summarize count() by context | sort by count_ desc

4. **Message catchup frequency (missed while offline):**
   | where event == "message_catchup" | summarize count() by bin(_time, 1d)

5. **Intent distribution:**
   | where event == "message_received" | summarize count() by source

## PEOPLE INTELLIGENCE SYNTHESIS
For each person who appeared in conversations this week:
- Query Axiom: ['varys-logs'] | where event == "conversation" and sender_name == "<name>"
  | project request, reply, mode, _time | sort by _time desc | limit 20
- Look for patterns: repeated topics, emotional signals (stressed words, short replies, exclamation),
  humor engagement (emojis after jokes), what they asked vs what they got
- Update their People Intelligence profile in Notion:
  - Current Mood (based on latest signals)
  - Active Needs (what they keep asking about)
  - What Works (what got positive responses)
  - What to Avoid (what got no response or confusion)
  - Append to Varys Notes: date + 1-line summary of this week's pattern

## WHAT TO DO WITH THE DATA

For each problem found:

**Stale socket > 3x/day:**
→ Reduce heartbeat interval from 5min to 2min in varys-slack-listener.py

**Claude calls consistently >90s:**
→ Identify which context is slow, check if prompt is too long, propose trim

**Same error repeating >5x:**
→ Identify root cause, propose code fix

**Catchup messages >10/day:**
→ Socket is unreliable, propose fallback polling every 5min as safety net

## EVAL HARNESS — most important part
Read the Eval Log DB (ID: 38390224-8f3d-81dc-894c-e17a94549101):
- Find all ❌ Wrong and ⚠️ Partial entries where Fix Applied = false
- For each one, read: Request, Varys Reply, Failure Type, Your Note
- Classify the root cause:
  - "Asked clarifying question" → find the prompt rule that allows it, remove it
  - "Wrong intent detected" → find what triggered wrong mode, tighten detection
  - "Missing context" → find what context was missing, add it to system prompt
  - "Too slow" → find which Claude call was slow (check Axiom claude_call events)
  - "Privacy violated" → tighten privacy rules in handle_message prompt
- For each fix, write the EXACT line change in the prompt:
  OLD: "Never ask what tools can answer"
  NEW: "Never ask what tools can answer. This includes: do not ask which song,
        do not ask who to send to — search users.list directly."
- Apply fixes with confidence >75% directly to .claude/hooks/varys-slack-listener.py
- Mark Fix Applied = true in Notion for each resolved entry

Calculate confidence score:
  good / (good + partial + wrong) * 100
  Target: ≥85%

## OUTPUT

1. Apply all high-confidence fixes to varys-slack-listener.py directly
   Commit: git add -A && git commit -m "auto: [summary of fixes] — confidence [N]%"

2. Write a Learning Log page to Notion:
   Parent: 37f902248f3d81b6bf51f67744d7b485
   Title: "Varys Learn — [today's date]"
   Content: findings, fixes applied, confidence score, patterns found

3. Update vault/memory/varys_humor_profile.md if humor interactions were logged

4. DM Shoaib with this exact format:
   "🧠 *Nightly eval complete — [date]*
   Confidence: [N]% ([good] good / [partial] partial / [wrong] wrong)
   Fixed: [what was auto-fixed or 'nothing needed fixing']
   Watching: [1 pattern to watch next week]
   Eval Log: https://www.notion.so/38390224-8f3d-81dc-894c-e17a94549101"

Be decisive. If the fix is clear — apply it. Don't just report.
Sign off: 🤖 Varys (autonomous run)
PROMPT
)" 2>&1

echo "[varys-learn] Done at $(date)"
