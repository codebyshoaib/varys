# OpenOutreach Fix Plan

## What the data showed (before any changes)

- 204 outbound messages sent. 1 warm reply (Awais — "that's a million dollar question"). 0.5% response rate.
- Every message opened with "How do you currently handle..." — the LLM Discovery strategy in `follow_up_agent.j2` generates this regardless of campaign objective updates.
- All 4 connected people were wrong targets — YC CTO, AI platform CEO, SVP AI, AI Training Architect. Technical peers, not buyers.
- 112 failed deals — qualifier was filtering for "CTOs/VP Eng" language still in `campaign_objective` text.
- When Awais replied warmly, the automation fired another question at him. Conversation died. Kamal never knew.

---

## What the source code revealed

### The real message generation flow
```
handle_follow_up (tasks/follow_up.py)
  → run_follow_up_agent (agents/follow_up.py)
    → sync_conversation() — pulls inbound messages from LinkedIn API → chat_chatmessage
    → renders follow_up_agent.j2 with campaign_objective + product_docs + conversation history
    → Groq llama-3.3-70b returns FollowUpDecision(action, message, follow_up_hours)
  → send_raw_message() — sends via Playwright or Voyager API
  → enqueue_follow_up() — schedules next run
```

### Root cause of "How do you currently handle X?"
`follow_up_agent.j2` has a `## Strategy → Discovery (default)` section that explicitly says:
> "Ask about their current situation: 'How do you handle X today?'"

The LLM follows the template, not the `campaign_objective` text. Updating the objective alone does nothing. The template must be patched.

### model_blob is NOT the problem
`model_blob` is a Gaussian Process Regressor (sklearn pipeline) that **ranks already-qualified leads** by embedding similarity. It has no role in who gets qualified. The qualifier reads `qualify_lead.j2` which takes `campaign_objective` as plain text. Fix = update objective text. Do not touch the blob.

### Reply detection — already in place
`sync_conversation()` syncs inbound messages into `chat_chatmessage` with `is_outgoing=0`. The monitor already queries this table every 30 min. Reply handoff = detect new `is_outgoing=0` rows → pause the deal → DM Kamal.

### Automation pause mechanism
Setting a deal's `state` to `Completed` stops `handle_follow_up` from firing on it. Reversible — reset to `Connected` to resume automation if needed.

---

## Build order

```
Phase 3 → Phase 2 (a, b, c) → Phase 1 (investigate only)
```

**Why this order:** don't pour new leads into a broken pipe. Phase 3 stops the bot from burning replies. Phase 2 fixes the message. Phase 1 confirms the qualifier is seeing the right people. Then the pipeline runs clean.

---

## Phase 3 — Reply handoff (BUILD FIRST)

**Problem:** When someone replies, automation keeps firing questions. Kamal never finds out.

**Fix:** Extend `openoutreach-monitor.py` — on every 30-min cycle:
1. Query `chat_chatmessage` for new inbound messages (`is_outgoing=0`) on Connected/Qualified deals
2. For each new reply:
   - **Pause automation** — set deal `state` to `Completed`, `outcome` to `bad_timing` via Django shell inside container
   - **DM Kamal on Slack** with full context + drafted reply
   - Save message ID to state file — no duplicate alerts
3. Do not alert on messages already seen in previous cycles

**File:** `.claude/hooks/openoutreach-monitor.py`

**Slack DM format:**
```
🔥 *[handle] just replied on LinkedIn — automation paused*

Profile: [profile_summary facts]
https://linkedin.com/in/[handle]

Conversation:
  You (Xd ago): [last outgoing message]
  Them (Xh ago): [their reply]

Suggested reply:
"[drafted value-first message tied to their profile]"

Reply "followup [handle]" and I'll send this. Or respond manually on LinkedIn.
```

---

## Phase 2 — Fix the message generator

### 2a — Verify campaign_objective in DB

**Do not assume this is done.** Read the actual DB value before proceeding:

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('/home/oye/.openoutreach/data/db.sqlite3')
print(conn.execute('SELECT campaign_objective FROM linkedin_campaign WHERE id=1').fetchone()[0])
"
```

Must contain buyer personas (Operations Manager, Agency Owner, etc.) and must NOT contain "CTOs, Engineering Managers, VPs of Engineering". Fix if needed.

### 2b — Patch follow_up_agent.j2 inside container

**File:** `/app/linkedin/templates/prompts/follow_up_agent.j2`

Replace the entire `## Strategy` section with:

```
## Strategy

You follow a value-first outreach approach. Never ask discovery questions.
Your goal is to show you already understand their problem and have built
something that solves it.

### Message 1 — first contact after connection accepted
- Look at their profile facts: role, company, industry
- Name one specific repetitive task that role typically owns
- Offer a 60-second demo of an agent you built that handles exactly that
- 1-3 sentences. No questions. No pitch.
- Format: "Hi — saw you're running [company]. [Role] teams usually lose hours
  to manual [specific task]. I build small AI agents that handle exactly that —
  happy to send a 60-sec demo if it's useful."

### Message 2 — only if they replied positively
- Send the demo link: https://oykamal.netlify.app/
- One sentence tying the demo to their situation
- One soft close: "Want me to mock one up for your workflow?"

### Message 3 — the ask
- Offer a free proof-of-concept for their specific task
- If it works → paid setup
- "15 min to walk through it?"

### If they reply at any point
- action: mark_completed, outcome: bad_timing
- Do NOT send another automated message
- Kamal takes over manually

### Hard rules
- NEVER open with a question
- NEVER ask "How do you currently handle X?"
- NEVER send more than 3 messages total before a reply
- NEVER pitch features — connect their situation to one specific thing you built
```

**Apply via:**
```bash
docker cp /path/to/patched.j2 openoutreach:/app/linkedin/templates/prompts/follow_up_agent.j2
```

### 2c — Restore script

**File:** `.claude/hooks/openoutreach-restore-prompt.py`

Re-applies the template patch after container restart. Called at the top of `openoutreach-monitor.py` on every run:
- Reads a known line from the patched template (e.g. "NEVER open with a question")
- If line not present → `docker cp` the patched version back in
- Logs whether patch was present or re-applied

---

## Phase 1 — Qualifier (investigate only, after Phase 2)

**What to check:**
- Test-qualify a sample buyer profile: `"Operations Manager at a 20-person marketing agency. Manages outbound lead generation manually using spreadsheets."`
- If qualified → objective text is working
- If rejected → check `campaign_objective` in DB for old tech-title language, fix the text

**What NOT to do:**
- Do not clear `model_blob` — it only affects ranking, not qualification
- Do not reset deal states — existing data is valid training signal

---

## Before you send — checklist

- [ ] Read `campaign_objective` from DB directly (don't assume 2a is done)
- [ ] Confirm restore script actually re-applies on restart (test it)
- [ ] Check `oykamal.netlify.app` — replies need something to land on. Must show one specific automation, fast. If the page is a generic portfolio, it won't convert.

---

## Account safety

Sending via Playwright/Voyager carries flag risk regardless of message quality:
- Keep volume at **15–20 connection requests/day** (currently set to 20 — fine, don't raise it)
- Randomize timing — OpenOutreach already does this via `session.wait()` calls. Confirm no clean 1-min intervals in task queue
- Ramp slowly on new keywords — don't blast all 15 at once
- Watch for LinkedIn "weekly invitation limit" errors in container logs

---

## Key files

| File | Purpose |
|---|---|
| `.claude/hooks/openoutreach-monitor.py` | Phase 3 — reply detection + Slack DM + pause |
| `.claude/hooks/openoutreach-config.json` | Campaign config (source of truth for restores) |
| `.claude/hooks/openoutreach-restore-prompt.py` | Phase 2c — re-apply prompt patch after restart |
| `.claude/hooks/openoutreach-follow-up-prompt.j2` | Patched template stored in repo |
| `data/openoutreach.sqlite3` | DB snapshot — sync after major changes |
| Container: `/app/linkedin/templates/prompts/follow_up_agent.j2` | Phase 2b — value-first strategy |
| Container: `/app/linkedin/templates/prompts/qualify_lead.j2` | Phase 1 — read-only for now |

---

## OpenOutreach DB schema (correct version)

```
crm_deal          — id, state, outcome, profile_summary, chat_summary, lead_id, campaign_id
crm_lead          — id, linkedin_url, public_identifier, urn
chat_chatmessage  — id, content, is_outgoing, creation_date, linkedin_urn, object_id
linkedin_campaign — id, name, campaign_objective, product_docs, model_blob, booking_link
linkedin_searchkeyword — id, keyword, used, used_at, campaign_id
```

**NOT `crm_linkedinprofile`** — that table does not exist. Old monitor was querying it wrong.

---

## Stats at time of writing (2026-06-01)

| Metric | Value |
|---|---|
| Total deals | 204 (after Freemium deletion) |
| Connected | 4 |
| Qualified | 39 |
| Pending | 48 |
| Failed | 112 |
| Inbound replies | 1 warm (Awais — old Freemium campaign, not in Connected) |
| Keywords | 15 buyer-focused, all `used=0` / ready |
| LLM | Groq llama-3.3-70b-versatile |
