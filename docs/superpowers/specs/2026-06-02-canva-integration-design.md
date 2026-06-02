# Canva Integration — Kamil Super-Agent Design

**Date:** 2026-06-02  
**Owner:** Kamal  
**Status:** Approved for implementation  
**Scope:** Canva Pro (m.kamal@taleemabad.com) integrated into Kamil's content pipeline + on-demand design via skill

---

## Goal

Give Kamil a full design capability: automated Canva designs as part of the content pipeline, plus on-demand design from Slack/Claude sessions. Self-evaluating agent retries poor designs and escalates to Kamil only when needed.

---

## Architecture

```
Notion Topic DB
      ↓
NLM Research (existing)
      ↓
Claude writes copy (existing)
      ↓
canva-designer.py              ← pipeline executor
      ↓ brief {topic, copy, format, channel, brand_kit_id}
Canva MCP → designs created (LinkedIn + Instagram + YouTube, parallel)
      ↓ {design_url, export_url, canva_id} per format
kamil-canva-agent              ← intelligent wrapper + self-eval
      ↓ Claude vision eval → scores ≥7 → pass | <7 → retry (max 2x) | fail → Needs-Kamal
Notion Design DB               ← stores URLs, eval scores, status
      ↓
poster scripts (linkedin_poster / ig_poster / yt_thumb)
```

---

## Components

### 1. `canva-designer.py`
- **Location:** `scripts/canva-designer.py`
- **Role:** Dumb executor — receives brief, calls Canva MCP, returns asset URLs
- **Input:** `{topic, copy, channel, format, brand_kit_id}`
- **Output:** `{design_url, export_url, canva_id}` per format
- **Behavior:** Creates all 3 channel formats in parallel per topic run
- **Template selection:** Matches `channel+format` key to a branded Canva template; falls back to brand-kit-guided creation if no template found

### 2. `kamil-canva-agent`
- **Location:** `agents/kamil-canva-agent.py`
- **Role:** Intelligent design agent — briefs the designer, evals output, retries, escalates
- **Invocation:** Called by content pipeline cron OR by `claude -p` from Slack DM
- **Self-eval:** Claude vision scores each design on 3 criteria (1–10 each):
  - **Brand consistency** — correct colors, fonts, logo placement match brand kit
  - **Text legibility** — readable at thumbnail size, adequate contrast
  - **Visual hierarchy** — clear focal point, natural eye flow
- **Retry logic:** Any score <7 → regenerate that format with adjusted brief (max 2 retries)
- **Escalation:** Still <7 after 2 retries → Slack DM to Kamil with scores + design URL
- **Logging:** All eval results written to Notion Observability DB

### 3. `canva` skill
- **Location:** `.claude/skills/canva/`
- **Role:** Kamil's on-demand interface from Claude sessions or Slack
- **Trigger phrases:** "make a post / carousel / thumbnail / banner / design / graphic"
- **Behavior:** Collects missing brief fields interactively, hands off to `kamil-canva-agent`
- **Skills-router entry:** Added to `.claude/rules/skills-router.md`

### 4. Notion Design DB (new)
- **Fields:** topic, channel, format, canva_id, export_url, eval_scores `{brand, legibility, hierarchy}`, retries, status `{draft | approved | posted | Needs-Kamal}`
- **Links:** Foreign key to existing Content DB entry

---

## Data Flow

### Happy Path
```
cron / Slack DM trigger
  → kamil-canva-agent receives brief
  → canva-designer.py creates all formats (parallel)
  → Claude vision eval → all scores ≥7
  → Notion Design DB: status=draft, URLs saved
  → poster scripts triggered → status=posted
```

### Retry Flow
```
any eval score <7
  → agent adjusts brief (contrast, text length, layout hint)
  → canva-designer.py regenerates that format only
  → re-eval → pass → continue | still <7 after 2x → escalate
```

### Escalation Flow
```
2 retries, still <7
  → Notion Design DB: status=Needs-Kamal
  → Slack DM: "Canva design needs review — [topic] [channel] [scores] [url]"
  → pipeline continues with other topics
```

### Auth Failure
```
Canva MCP token expired
  → agent catches auth error
  → Slack DM: "Canva needs re-auth — reply 'canva auth'"
  → affected job paused, other topics continue
```

---

## Eval Harness

### Criteria & Thresholds
| Criterion | Method | Pass threshold |
|---|---|---|
| Brand consistency | Claude vision vs brand kit | ≥7 |
| Text legibility | Claude vision @ thumbnail size | ≥7 |
| Visual hierarchy | Claude vision focal point check | ≥7 |

### Feedback Loop
- After 30 evals: weekly summary to Notion Observability DB
- Patterns (e.g. "YT thumbnails fail legibility 60%") → Kamil reviews → update brief templates
- Agent improves its own brief generation based on historical pass rates per format

---

## Skills Router Addition

```markdown
| design / post / carousel / thumbnail / banner / "make a graphic" | `canva` |
```

---

## Authentication

- Canva MCP (`mcp__claude_ai_Canva__authenticate`) handles OAuth
- Authenticate once with `m.kamal@taleemabad.com` (Canva Pro account)
- Token managed by MCP server; agent catches expiry and prompts re-auth via Slack

---

## Canva Templates Strategy

- Maintain one branded template per format in Canva account:
  - `kamil-linkedin-card` (1200×627)
  - `kamil-ig-post` (1080×1080)
  - `kamil-ig-story` (1080×1920)
  - `kamil-yt-thumbnail` (1280×720)
- Agent selects by `channel+format` key
- Dynamic fields: headline, subtext, background image
- No matching template → create from scratch using brand kit

---

## Files to Create / Modify

| File | Action |
|---|---|
| `scripts/canva-designer.py` | Create |
| `agents/kamil-canva-agent.py` | Create |
| `.claude/skills/canva/skill.md` | Create |
| `.claude/rules/skills-router.md` | Update (add canva row) |
| `.claude/settings.json` | Update (enable Canva MCP) |
| Notion Design DB | Create via MCP |

---

## Out of Scope

- Video / Reels generation (Canva video API — future phase)
- Auto-posting without Kamil approval gate for first 2 weeks (builds trust in eval scores)
- Multi-brand support (single brand kit only)
