# OpenOutreach Fix Plan

## What the data showed (before any changes)

- 204 outbound messages sent. 1 warm reply (Awais — "that's a million dollar question"). 0.5% response rate.
- Every message opened with "How do you currently handle..." — the LLM Discovery strategy in `follow_up_agent.j2` was generating this regardless of campaign objective updates.
- All 4 connected people were wrong targets — YC CTO, AI platform CEO, SVP AI, AI Training Architect. Technical peers, not buyers.
- 112 failed deals — qualifier was filtering for "CTOs/VP Eng" language still in campaign_objective text.
- When Awais replied warmly, the automation fired another question at him instead of alerting Kamal. Conversation died.

---

## What I learned from the source code

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

### Why "How do you currently handle X?" kept appearing
The `follow_up_agent.j2` template has a `## Strategy → Discovery (default)` section that explicitly instructs:
> "Ask about their current situation: 'How do you handle X today?'"

This overrides anything written in campaign_objective. The LLM follows the template, not the objective text.

### The model_blob is NOT the problem
`model_blob` is a Gaussian Process Regressor that ranks already-qualified leads by embedding similarity. It does NOT affect who gets qualified. The qualifier reads `qualify_lead.j2` which takes `campaign_objective` as plain text. Fix = update the objective text.

### Reply detection already works
`sync_conversation()` already syncs inbound messages into `chat_chatmessage` with `is_outgoing=0`. The monitor already queries this table. Reply detection = compare new `is_outgoing=0` rows against seen state.

### Automation pause mechanism
Setting a deal state to `Completed` stops `handle_follow_up` from firing. When Kamal takes over manually, deal can be reset to `Connected` to resume automation if needed.

---

## Build order

```
Phase 3 first → Phase 2 → Phase 1 (investigate only)
```

Reason: don't pour new leads into a broken pipe. Fix the leaks before filling the pipeline.

---

## Phase 3 — Human handoff on reply (BUILD FIRST)

**Problem:** When someone replies, automation keeps firing questions. Kamal never finds out until he checks LinkedIn manually.

**Fix:** Extend `openoutreach-monitor.py`:
- Check `chat_chatmessage` for new inbound messages (`is_outgoing=0`) on every 30-min cycle
- When new inbound reply found on a Connected/Qualified deal:
  1. Pause automation — set deal state to `Completed` with outcome `bad_timing` via Django shell inside container
  2. DM Kamal on Slack with: who replied, their profile summary, full conversation thread, drafted value-first response
  3. Save message ID to state file so no duplicate alerts

**File to change:** `.claude/hooks/openoutreach-monitor.py`

**Slack DM format:**
```
🔥 *[Name] just replied on LinkedIn*

Profile: [title] at [company]
[profile URL]

Conversation:
  You (3d ago): [your last message]
  Them (2h ago): [their reply]

Suggested reply:
"[drafted value-first message based on their profile]"

⏸ Automation paused. Reply "send [their handle]" to send this, or edit and send manually.
```

---

## Phase 2 — Fix the message generator

### Phase 2a — Update campaign_objective in DB
Remove: "CTOs, Engineering Managers, VPs of Engineering, Technical Co-founders"  
Add: buyer-focused personas (Operations Manager, Agency Owner, E-commerce Founder, etc.)  
**Already done** in a prior session — verify it's correct.

### Phase 2b — Patch follow_up_agent.j2 inside container
**File:** `/app/linkedin/templates/prompts/follow_up_agent.j2`  
**Change:** Replace `## Strategy → Discovery (default)` section with value-first approach:

```
## Strategy

You follow a value-first outreach approach. Your goal is to show you understand
their problem and have already solved something like it — never to ask discovery
questions.

### Message 1 (first contact after connection accepted)
- Observe something specific about their role/company from the profile facts
- Name one specific repetitive task their role typically owns
- Offer a concrete 60-second demo of an agent you built that handles exactly that
- No questions. No pitch. 1-3 sentences max.
- Example: "Hi — saw you're running [company]. [Role] teams usually lose hours to
  manual [task]. I build small AI agents that handle exactly that — happy to send
  a 60-sec demo if it's useful."

### Message 2 (only if they replied positively)
- Send the demo link (https://oykamal.netlify.app/)
- Tie it to their specific situation
- Ask one soft question: "Want me to mock one up for your workflow?"

### Message 3 (the ask)
- Propose a free proof-of-concept for their specific task
- If it works → paid setup
- "15 min to walk through it?"

### Rules
- NEVER ask "How do you currently handle X?"
- NEVER open with a question
- NEVER send more than 3 messages total without a reply
- If they reply with anything → mark_completed with outcome bad_timing
  (Kamal takes over manually — do NOT continue the automated sequence)
```

### Phase 2c — Restore script
Write `.claude/hooks/openoutreach-restore-prompt.py` — re-applies the template patch after container restart. Called by `openoutreach-monitor.py` at the start of each run (checks if patch is applied, re-applies if not).

---

## Phase 1 — Qualifier investigation (after Phase 2)

**What to check:**
- Run a test qualification against a sample buyer profile (e.g. "Operations Manager at a 20-person marketing agency")
- Confirm the qualifier accepts it with the updated `campaign_objective`
- Check if new buyer keywords (Operations Manager, Agency Owner, etc.) are producing qualified leads after a few cycles

**What NOT to do:**
- Do not clear `model_blob` — it only affects ranking of already-qualified leads
- Do not reset deal states — 195 existing leads are valid data

**If buyer keywords are still being rejected:**
- The `qualify_lead.j2` template itself is fine (no hardcoded titles)
- Check if `campaign_objective` in DB still has old tech-title language
- Fix by updating the objective text directly

---

## Key files

| File | Purpose |
|---|---|
| `.claude/hooks/openoutreach-monitor.py` | Phase 3 — reply detection + Slack DM + pause |
| `.claude/hooks/openoutreach-config.json` | Campaign config reference (source of truth for restores) |
| `.claude/hooks/openoutreach-restore-prompt.py` | Phase 2c — re-apply prompt patch after restart |
| `data/openoutreach.sqlite3` | DB snapshot — sync after major changes |
| Container: `/app/linkedin/templates/prompts/follow_up_agent.j2` | Phase 2b — value-first strategy |
| Container: `/app/linkedin/templates/prompts/qualify_lead.j2` | Phase 1 — qualification template (read-only for now) |

---

## OpenOutreach DB schema (correct)

```
crm_deal      — state: Connected/Qualified/Pending/Failed/Completed
crm_lead      — linkedin_url, public_identifier, urn
chat_chatmessage — content, is_outgoing, creation_date, linkedin_urn
linkedin_campaign — campaign_objective, product_docs, model_blob, booking_link
linkedin_searchkeyword — keyword, used, campaign_id
```

**NOT:** `crm_linkedinprofile` (doesn't exist — old monitor was wrong)

---

## Stats at time of writing (2026-06-01)

- Total deals: 204 (after Freemium deletion)
- Connected: 4 (mklikushin, kaijiabofeng, alanwalshireland, muhammadajmalsiddiqi)
- Qualified: 39
- Pending: 48
- Failed: 112
- Acceptance rate: 24% (15 connected / 59+15 total with qualified)
- Inbound replies: 1 warm (Awais — not in DB as Connected, was in old Freemium campaign)
- Keywords: 15 buyer-focused, all unused/ready
