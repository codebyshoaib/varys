# Canva Design Skill

Kamil's on-demand Canva design interface. Triggered when Kamil asks to create
any visual content: post, carousel, thumbnail, banner, graphic, design.

## Trigger phrases
"make a post", "create a carousel", "design a thumbnail", "make a banner",
"create a graphic", "make an image for", "design something for", "canva"

---

## Visual Style System

Pick the style that fits the content. When unsure, default to **TED-Ed** for
fitness/lifestyle, **Bold Graphic** for tech, **Isometric** for professional/data.

### 1. TED-Ed (default for fitness, lifestyle, motivation)
Warm illustrated educational aesthetic. Flat vector with soft textures and
organic shapes. Emotional, approachable, shareable.

**Prompt suffix to append:**
```
TED-Ed animation style: warm illustrated educational aesthetic.
Flat vector illustration with soft textures and organic shapes.
Warm color palette: cream/off-white background, teal (#2DD4BF), coral (#F97316),
golden yellow (#FBBF24), soft sage green (#22C55E) accents.
Hand-drawn feel with clean bold lines and rounded edges.
Playful but professional, engaging visual metaphors.
Simple bold typography, highly readable at thumbnail size.
Full bleed edge-to-edge. No border, no frame.
CRITICAL: All text must be large, sharp, perfectly readable. No blurry text.
DO NOT include meta-labels, zone names, or layout instructions in the image.
```

**Fitness/lifestyle prompt rules:**
- Use emotional visual metaphors ("a man doing push-ups on a mountain at sunrise")
- One strong focal image, one bold headline, one supporting line — nothing else
- Warm coral/teal palette = energy + approachability
- Show the human doing the thing, not icons of the thing

### 2. Bold Graphic (tech, tips, educational content)
Saul Bass-inspired. 2-3 colors max. Film poster energy. Hand-cut paper feel.
Extremely high contrast. Works at tiny thumbnail sizes.

**Prompt suffix:**
```
Bold graphic design style inspired by Saul Bass film posters.
2-3 colors maximum: deep navy (#1B365D), bright coral (#F97316), and cream (#FAFAF8).
Geometric shapes, bold silhouettes, high contrast.
Typography is the hero: oversized, bold, modern sans-serif.
Minimal — one strong image, one headline, nothing else.
Full bleed. No border. No frame.
CRITICAL: Maximum contrast. Text must be instantly readable even at 100px wide.
DO NOT include meta-labels, zone names, or layout instructions in the image.
```

### 3. Isometric (professional, data, career, finance)
3D miniature world-building. Clean vector, soft shadows. Game-like precision.
Best for LinkedIn professional content.

**Prompt suffix:**
```
Isometric illustration style. 3D isometric perspective (30-degree angle).
Detailed miniature world-building with clean vector graphics and soft shadows.
Color palette: navy (#1B365D) primary, teal (#2DD4BF) accents,
coral (#F97316) highlights, warm cream (#FAFAF8) background,
golden yellow (#FBBF24) callouts, sage green (#22C55E) success indicators.
Professional, clean, modern. Game-like clarity and precision.
Bold clean modern sans-serif typography — all text embedded legibly.
Full bleed edge-to-edge. No border, no frame.
CRITICAL: All text MUST be large, sharp, perfectly readable. No blurry text.
DO NOT include meta-labels, zone names, scene numbers, or layout instructions.
Only render real content text the audience should read.
```

---

## Prompt Writing Rules (from Orenda playbooks)

### DO
- Describe content spatially in natural language: "on the left, a man doing squats", "above the text, a sunrise"
- Embed key text directly: `A bold headline reads 'DAILY MOVES EVERY MAN NEEDS'`
- Name specific colors with hex: "sage green (#22C55E)" not "green"
- One strong focal point per design — don't crowd it
- Show humans doing the thing (fitness) not icons of the thing
- State exact pixel dimensions and aspect ratio for each format

### DON'T (these break the output)
- ❌ `"LEFT ZONE: hero image"` → use `"On the left side, a man doing push-ups"`
- ❌ `"SECTION A / SECTION B"` → use spatial language: "above", "below", "beside"
- ❌ `"TOP AREA: headline"` → use `"A bold headline at the top reads '...'"` 
- ❌ Vague colors: `"green"`, `"blue"` → use hex codes
- ❌ Long bullet lists of content → pick ONE message per design
- ❌ Generic stock-photo descriptions → specific, vivid scenes

---

## Format Specs

| Channel | Format | Size | Design type |
|---|---|---|---|
| Instagram post | `instagram_post` | 1080×1350 (4:5) | Feed post |
| Instagram story | `your_story` | 1080×1920 (9:16) | Story |
| LinkedIn | `facebook_post` | 1200×628 (1.91:1) | Feed post |
| YouTube | `youtube_thumbnail` | 1280×720 (16:9) | Thumbnail |

---

## Quality Gate (run before generating)

Before building the prompt, check it against these 5 criteria.
If any fail, rewrite the prompt — don't generate with a bad brief.

| Gate | Check |
|---|---|
| **SPECIFIC** | Grounded in this exact topic — not a generic fitness/tech template |
| **SINGLE MESSAGE** | One idea per design — not 3 tips crammed into one image |
| **VISUAL** | Describes a scene, not a layout — "man doing squats at sunrise" not "image of exercise" |
| **READABLE** | Text embedded in prompt will be legible at 100px thumbnail size |
| **WORTH MAKING** | Would Kamil actually post this? If not, rewrite |

---

## Process

1. Collect brief: **topic**, **copy** (max 8 words), **channel(s)**, **style** (default: TED-Ed for fitness)
2. If any field missing, ask one question at a time
3. Run quality gate on the brief — rewrite if any criteria fail
4. Pick the right style suffix for the content type
5. Build the Canva MCP prompt using natural spatial language, no zone labels
6. Call `mcp__claude_ai_Canva__generate-design` with `brand_kit_id=kAHLIxSiVa8`
7. Pick best candidate → `mcp__claude_ai_Canva__create-design-from-candidate`
8. Export as PNG → `mcp__claude_ai_Canva__export-design` (format: png, quality: pro)
9. Download and post to Slack DM (`D0B415M06SK`) using `files.getUploadURLExternal` flow
10. Share Canva edit URL so Kamil can tweak

**Brand kit ID:** `kAHLIxSiVa8` (m.kamal@taleemabad.com Canva Pro account)
**Slack DM:** `D0B415M06SK`

---

## Example prompt (fitness, TED-Ed style)

**Topic:** Daily push-up routine for men  
**Copy:** "30 Pushups. Every Day. That's It."  
**Channel:** Instagram post

```
A warm illustrated scene of a determined man in athletic wear doing a perfect
push-up on a wooden floor, sunlight streaming through a window behind him.
Above him, bold text reads "30 PUSHUPS. EVERY DAY. THAT'S IT."
Below, smaller text: "Start here. Stay consistent."
The mood is motivating but calm — sunrise energy, not gym hype.
[TED-Ed style suffix appended here]
```

---

## Auth failure handling
If Canva MCP returns an auth error:
"Canva needs re-authentication — run `/mcp` and select claude.ai Canva."
Then retry the generation.
