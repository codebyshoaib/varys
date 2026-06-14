# Canva Design Skill

Varys's on-demand Canva design interface. Triggered when Varys asks to create
any visual content: post, carousel, thumbnail, banner, graphic, design.

## Trigger phrases
"make a post", "create a design", "design a thumbnail", "make a banner",
"create a graphic", "make an image for", "design something for", "canva",
"carousel", "social post"

---

## Core Methodology: Anthropic Canvas-Design Approach

This skill follows the Anthropic canvas-design philosophy. Every design is created
in two steps — never skip step 1.

### Step 1: Design Philosophy Creation

Before touching Canva, create an aesthetic movement for this specific topic.
This is NOT a template or style guide. It is a genuine philosophical stance.

**What to generate:**
- **Movement name** (1-2 evocative words): e.g. "Kinetic Silence", "Brutal Joy", "Chromatic Tension"
- **Manifesto** (4 paragraphs covering): core visual philosophy + what it rejects; how space/form/color operate; emotional register and cultural references; what expert craftsmanship means here
- **Canvas directive** (3-4 sentences): precise visual instruction for the specific format — what dominates, what is absent, how text behaves as a visual element

**Critical principles:**
- The topic is the SOUL embedded invisibly in the work — felt, not announced
- Text is a sculptural element, not a caption — integrated into composition
- 90% visual, 10% essential text
- Must look like it took countless hours — museum-quality, master-level execution
- Reject all generic AI aesthetics, illustration templates, clip-art

**Example philosophy for "daily workout for men" / Instagram:**

> *Movement: "Kinetic Silence"*
>
> *This movement rejects the noise of motivational design — the stock-photo gym, the bright neon, the shouted headline. It speaks in the language of force held still. Every element earns its presence through visual necessity.*
>
> *Space is taut, charged. A single dominant form — the silhouette of a body at peak effort — commands the frame. Color is a single field of deep charcoal broken by one precise accent. Nothing decorates. Everything means.*
>
> *The cultural references are architectural: Brutalist weight, Japanese negative space, the graphic economy of a protest poster. The emotional register is not "motivation" — it is something quieter and more permanent: the knowledge that shows in a body built over years.*
>
> *Canvas directive: One silhouetted human form, maximum contrast. A single bold word floats in the negative space — not labeled, not boxed, just present. The design breathes. Typography is structural weight, not caption.*

### Step 2: Canvas Expression

With the philosophy established, generate the Canva design.

**Prompt construction rules:**
- Lead with the movement name and philosophy
- Embed the topic as the "soul" — the invisible conceptual DNA
- Treat the copy as sculptural typography, not a caption
- Demand museum-quality craftsmanship explicitly
- No zone labels, no layout instructions, no meta-text in the image

---

## Process

1. **Collect brief**: topic, copy (max 8 words), channel(s)
2. **If any field missing**: ask one question at a time
3. **Generate design philosophy**: use `design_philosopher.py` or generate inline — movement name + manifesto + canvas directive for this specific topic
4. **Build Canva prompt** using the philosophy (see methodology above)
5. **Call** `mcp__claude_ai_Canva__generate-design` with `brand_kit_id=kAHLIxSiVa8`
6. **All 4 candidates** are generated — pick the most artistically resolved one (not the safest)
7. **Save** via `mcp__claude_ai_Canva__create-design-from-candidate`
8. **Export** PNG via `mcp__claude_ai_Canva__export-design` (format: png, quality: pro)
9. **Download + post to Slack** DM (use `USER_SLACK_DM` from `~/.agent-config.json`) using `files.getUploadURLExternal` flow
10. **Share edit URL** so {{USER_NAME}} can refine

**Brand kit ID:** set `CANVA_BRAND_KIT_ID` in `~/.agent-config.json`
**Slack DM:** set `USER_SLACK_DM` in `~/.agent-config.json`

---

## Format Specs

| Channel | Canva design_type | Size |
|---|---|---|
| Instagram post | `instagram_post` | 1080×1350 |
| Instagram story | `your_story` | 1080×1920 |
| LinkedIn | `facebook_post` | 1200×628 |
| YouTube thumbnail | `youtube_thumbnail` | 1280×720 |

---

## Quality Gate

Before calling Canva MCP, check the prompt against these gates. Rewrite if any fail.

| Gate | Check |
|---|---|
| **Has philosophy** | A named aesthetic movement drives the prompt — not a style template |
| **Soul not announced** | Topic is embedded invisibly — not "this design is about X" |
| **Text is sculpture** | Copy is treated as a visual element, not a caption |
| **Craftsmanship demanded** | Prompt explicitly calls for museum-quality, master-level execution |
| **No AI aesthetics** | Prompt explicitly rejects generic AI output, clip-art, templates |
| **Visual dominant** | 90% composition, 10% text — stated in the prompt |

---

## Auth failure handling
If Canva MCP returns an auth error: run `/mcp` and select claude.ai Canva.
