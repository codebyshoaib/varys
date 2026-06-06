# Kamil Capability Honesty System — Design Spec

**Date:** 2026-06-06  
**Author:** Kamal (approved)  
**Status:** Ready for implementation

---

## Problem Statement

Kamil confabulates capabilities it does not have. When Kamal asks for an inline
infographic, Kamil claims pipelines exist (Canva batch design, NLM visual export)
that either don't work or produce non-inline output. It never admits the gap,
never offers a concrete honest fallback, and pivots to unrelated tasks when
corrected repeatedly. The root causes are:

1. No capability manifest — Claude's prompt lists what Kamil CAN do but never
   what it CANNOT do, so the model fills the gap with confabulation.
2. No visual intent router — image/infographic requests fall into the generic
   Claude call with no handler, so Claude free-solos a fake pipeline.
3. No honesty gate — there is a clarification-question detector but nothing that
   catches false delivery claims ("I posted X", "here it is").
4. No learning loop — each new capability gap is forgotten after the session ends.

---

## Goals

- Kamil attempts generation using real available tools first.
- If it cannot produce the exact output, it says what it produced instead and
  why the original wasn't possible — one honest message, zero runaround.
- Every gap is recorded and promoted into permanent knowledge after 2+ occurrences.
- Kamal is offered a build ticket for any high-priority gap.

---

## Architecture

```
Incoming Slack message
        │
        ├── is_notebooklm_command?  → NLM handler (existing, unchanged)
        ├── is_pr_review?           → PR handler (existing, unchanged)
        ├── is_visual_request()?    → handle_visual_request() [NEW]
        │                                   │
        │                          infographic_handler.py [NEW]
        │                          NLM research → key points
        │                          → image_generator.py → PNG
        │                          → upload_file_to_slack()
        │                          on failure → honest fallback + log gap
        │
        └── handle_message()        → generic Claude call (existing)
                │  + CAPABILITIES.md injected into prompt [MODIFIED]
                │
                ▼
        honesty_gate.py [NEW]
        scans draft for false delivery claims
        verifies actual file/upload happened
        if mismatch → rewrites to honest fallback + logs gap
                │
                ▼
        web.chat_postMessage()

Gap log → capability_gaps table in harness.db
        │
kamil-gap-watcher.py [MODIFIED — repurposed]
  weekly: gaps ≥2 occurrences → append to CAPABILITIES.md
        → DM Kamal → open Notion Harness ticket
        │
kamil_eval_tracker.py [EXISTING — unchanged]
  reaction signals (👍/❌) feed gap priority score
```

---

## Components

### 1. `CAPABILITIES.md`

**Location:** `.claude/rules/CAPABILITIES.md`  
**Format:** Two sections — `CAN DO` (summary, already implicit) and `CANNOT DO`
(explicit list with honest fallback for each item).

Initial `CANNOT DO` entries:
- `inline_image_generation` — cannot generate arbitrary images on demand.
  Fallback: `image_generator.py --type info` for structured infographics (NLM-sourced).
- `nlm_visual_export_sync` — NLM slide/visual exports are async (2–5 min); cannot
  post inline immediately. Fallback: poll + upload when ready.
- `canva_inline_post` — Canva design links require login; cannot post as viewable
  inline image. Fallback: export PNG via Canva MCP then upload.
- `video_generation` — no video generation capability exists. Fallback: say so.
- `arbitrary_file_download` — cannot download external URLs as files unless
  using specific tools. Fallback: WebFetch for text, say so for binaries.

This file is injected verbatim into `handle_message()` under `## WHAT KAMIL CANNOT DO`.
The model reads its own limits before answering.

Auto-updated by `kamil-gap-watcher.py` when new gaps are confirmed.

---

### 2. `infographic_handler.py`

**Location:** `.claude/hooks/infographic_handler.py`  
**Trigger:** `is_visual_request()` in the listener  
**Dependencies:** `notebooklm_handler.py`, `image_generator.py`, `kamil_log.py`

**Flow:**
```
handle(text, channel, thread_ts, web, bot_token, sender_id)
  │
  ├─ Step 1: extract_topic(text)
  │    regex for "infographic about X", "image of X", "create X infographic"
  │    fallback: Claude one-shot "what is the topic of this request? reply with 1-5 words"
  │
  ├─ Step 2: resolve NLM notebook
  │    registry_search([topic keywords]) → best match
  │    if no match → create_notebook(topic) + deep_research(topic)
  │
  ├─ Step 3: query notebook for structured points
  │    nlm notebook query nb_id "list exactly 7 key facts about [topic], one per line"
  │    parse → list[str] (7 items max, 5 minimum)
  │
  ├─ Step 4: render PNG
  │    image_generator.py --type info --title [topic] --tips [points]
  │    --palette fitness|tech (auto-detect from topic keywords)
  │    --output /tmp/infographic-<ts>.png
  │
  ├─ Step 5: upload to Slack
  │    upload_file_to_slack(bot_token, channel, filepath, title, comment)
  │    post ack: "🖼️ *[topic]* — sourced from NotebookLM 🤖 Kamil"
  │
  └─ ON FAILURE at any step:
       log_capability_gap(gap_type="inline_image", failed_step=step, request=text)
       post honest fallback (see Fallback Messages section)
```

**Fallback messages by step:**
- Step 2 fail (NLM unreachable): "NotebookLM isn't responding right now. I can do a text summary instead — want that?"
- Step 3 fail (query returns empty): "Got the notebook but couldn't extract structured points. Try `nlm ask [topic] 'list 7 key facts'` directly."
- Step 4 fail (PIL/font missing): "Image renderer isn't set up (missing PIL or fonts). I can post the research as a structured text instead."
- Step 5 fail (no files:write scope): "Generated the image but can't upload — Kamil app needs `files:write` scope. File saved at `/tmp/infographic-<ts>.png`. Fix: api.slack.com/apps → Kamil → OAuth Scopes → add `files:write` → Reinstall."

---

### 3. `honesty_gate.py`

**Location:** `.claude/hooks/honesty_gate.py`  
**Called from:** `handle_message()`, between `run_claude()` and `web.chat_postMessage()`  
**Pattern:** Same structure as existing `privacy_eval()` — takes draft, returns safe draft.

**Detection — false delivery claim phrases:**
```python
DELIVERY_CLAIMS = [
    "here it is", "here you go", "i've posted", "i posted", "i've sent",
    "i sent", "i generated", "i created the image", "done — here",
    "posted it", "uploaded it", "i've uploaded", "check it out",
    "here's the infographic", "here's the image", "i've created",
]
```

**Verification logic:**
```
for each claim phrase found in draft:
  → check if any file was actually uploaded this request cycle
    (flag set by infographic_handler or upload_file_to_slack on success)
  → if no upload flag set:
      rewrite = honest_fallback(draft, gap_type)
      log_capability_gap(gap_type, request, draft)
      return rewrite
  → else: pass through unchanged
```

**Honest fallback rewrite prompt (runs fast Claude call):**
```
"Rewrite this message to be honest. The agent claimed to have produced or
sent something but did not. Remove the false claim. State clearly what
wasn't possible and offer 1-2 concrete alternatives that ARE possible.
Keep it under 3 lines. Sign off: 🤖 Kamil"
```

The gate **never blocks** — if the rewrite call itself fails, the original draft
goes through and the gap is still logged.

**Logging:** every gate correction → `klog("honesty_gate_fired", ...)` + Notion
Observability DB entry (Status: Monitoring, Severity: warning).

---

### 4. `capability_gaps` table in `harness.db`

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS capability_gaps (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    gap_type     TEXT NOT NULL,           -- e.g. "inline_image"
    request_text TEXT,                    -- what Kamal asked
    failed_step  TEXT,                    -- which step failed
    fallback_used TEXT,                   -- what was offered instead
    reaction     TEXT DEFAULT 'pending',  -- 'accepted'/'rejected'/'pending'
    ts           TEXT NOT NULL,
    session_id   TEXT
);
```

**Written by:** `infographic_handler.py` (step failures) and `honesty_gate.py`
(false claim corrections).

**Read by:** `kamil-gap-watcher.py` (weekly promotion loop).

---

### 5. `kamil-gap-watcher.py` (repurposed)

**Existing file:** `.claude/hooks/kamil-gap-watcher.py` already exists — repurpose it.  
**Schedule:** Weekly (add to crontab via `cron-wrap.sh`).

**Logic:**
```
1. Query capability_gaps WHERE ts > 7 days ago
2. GROUP BY gap_type → count occurrences
3. For each gap_type with count >= 2:
   a. Check if already in CAPABILITIES.md (skip if yes)
   b. Append to CAPABILITIES.md under CANNOT DO with honest fallback
   c. Score priority:
        reaction='rejected' occurrences * 3 + total occurrences
   d. If priority >= 4:
        → Create Notion Harness ticket:
          Title: "Build capability: [gap_type]"
          Status: Not started
          Body: N requests in last 7 days, sample requests, suggested approach
        → DM Kamal:
          "I've learned I can't do [gap_type] (hit it N times this week).
           Added to my limits. Created Harness ticket to build it — want me to start?"
4. Update kamil_eval_tracker reaction scores for gap entries
   (👍 on fallback = reaction='accepted', ❌ = reaction='rejected')
```

---

### 6. `is_visual_request()` + routing (listener changes)

**New function in `kamil-slack-listener.py`:**
```python
_VISUAL_TRIGGERS = (
    "infographic", "create image", "make image", "generate image",
    "create a visual", "make a visual", "make me a", "create me a",
    "create an image", "generate a picture", "make an infographic",
    "visual for", "image for", "picture of", "draw me",
)

def is_visual_request(text: str) -> bool:
    t = text.lower()
    return any(trigger in t for trigger in _VISUAL_TRIGGERS)
```

**Routing addition** (before the generic `handle_message` call, after NLM/PR checks):
```python
if sender_id == KAMAL_USER_ID and is_visual_request(clean):
    threading.Thread(
        target=infographic_handler.handle,
        args=(clean, channel, thread_ts, web, bot_token_cfg, sender_id),
        daemon=True,
    ).start()
    return
```

**Prompt injection** in `handle_message()`:
```python
capabilities_path = KAMIL_DIR / ".claude" / "rules" / "CAPABILITIES.md"
capabilities_block = (
    capabilities_path.read_text() if capabilities_path.exists() else ""
)
# injected into prompt as:
# ## WHAT KAMIL CANNOT DO
# {capabilities_block}
```

---

## Files Changed

| File | Change type | What changes |
|---|---|---|
| `.claude/rules/CAPABILITIES.md` | NEW | Capability manifest, auto-updated by gap-watcher |
| `.claude/hooks/infographic_handler.py` | NEW | NLM → image_generator → Slack upload pipeline |
| `.claude/hooks/honesty_gate.py` | NEW | Pre-send false claim detector and rewriter |
| `.claude/hooks/kamil-gap-watcher.py` | MODIFIED | Add gap promotion loop + Notion ticket creation |
| `.claude/hooks/kamil-slack-listener.py` | MODIFIED | `is_visual_request()`, visual routing, gate wiring, manifest injection |
| `~/.kamil-harness/harness.db` | SCHEMA ADD | `capability_gaps` table (migration in kamil_harness_db.py) |
| `.claude/hooks/kamil_harness_db.py` | MODIFIED | Add `capability_gaps` table creation + `log_capability_gap()` helper |

---

## What This Does NOT Change

- NLM command routing (`nlm *`) — untouched
- PR review flow — untouched
- Third-party reply privacy eval — untouched
- Eval/health logging infrastructure — untouched (only adds calls to existing functions)
- Content pipeline — untouched

---

## Success Criteria

1. "Create an infographic about [topic]" → produces a real PNG uploaded inline to Slack,
   sourced from NLM, within 3 minutes.
2. If any step fails → one honest message with the exact failure reason and 1-2 alternatives.
   Zero "here it is" claims without an actual file.
3. After 2 identical gap types in a week → `CAPABILITIES.md` is updated automatically
   and Kamal gets a DM + Harness ticket.
4. `honesty_gate.py` never blocks a message — failures are logged and the original
   passes through.
5. Kamil never again claims to have posted something it did not post.
