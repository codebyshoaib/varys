# Kamil — Character Design Spec

> Game asset level consistency. Every image generated from this spec must be
> immediately recognisable as the same character. Read before ANY visual task.
> Reference file: `vault/memory/kamil_avatar.png`

## Core Rules
- This is a CHARACTER, not a person. No ethnicity labels.
- Style: stylised game character — think Valorant agent meets Notion avatar.
- Every asset uses the SAME face, SAME colors, SAME energy. No variation.
- Never generate without reading this file first.
- To change anything: update spec first, bump version, then regenerate ALL assets.

---

## Character Identity

| Attribute | Value |
|---|---|
| Name | Kamil |
| Archetype | The quiet operator. Knows everything, says just enough. |
| Energy | Calm. Sharp. Slightly amused. Never surprised. |
| Vibe | Senior engineer who already found the bug before you finished explaining it. |

---

## Face (locked — never changes)

| Attribute | Value |
|---|---|
| Face shape | Strong angular jaw, slightly square |
| Skin tone | Warm medium-brown (#8B5E3C range) |
| Eyes | Dark, half-lidded, calm — not tired, just unbothered |
| Eyebrows | Dark, slightly thick, one slightly raised — the "I see what you did there" brow |
| Nose | Sharp, defined bridge |
| Lips | Neutral closed mouth, very slight smirk on the right side only |
| Expression | 70% neutral, 30% amused. Never angry, never excited, never fully smiling. |
| Beard | Full, short, well-defined edges. Dark. |
| Hair | Short on sides, slightly textured on top — pushed back loosely |
| Hair color | Black |

---

## Color Palette (locked)

| Name | Hex | Used for |
|---|---|---|
| Skin | #8B5E3C | Face, hands, neck |
| Skin shadow | #6B4226 | Under jaw, eye sockets, nose sides |
| Skin highlight | #A0724F | Forehead, cheekbones |
| Hair / Beard | #1A1A1A | Hair, eyebrows, beard |
| Eye white | #F0EDE8 | Eyeballs |
| Iris | #3D2B1F | Eye color |
| Hoodie | #1C1C1E | Clothing |
| Background | #0D1B2A | All backgrounds |
| Accent | #4A90E2 | Glow, highlights, UI elements |
| Star | #C8D6E5 | The 4-pointed star watermark |

---

## Clothing (locked)

| Attribute | Value |
|---|---|
| Item | Black technical hoodie |
| Details | Drawstrings visible, hood down, subtle chest seam |
| Color | #1C1C1E — near black, not pure black |
| Fit | Relaxed but not baggy |
| No logos | Clean, no branding |

---

## Signature Details (appear on every asset)

- **4-pointed star** — bottom-right corner, small, color #C8D6E5, subtle
- **Expression** — always the same half-smirk, never varies
- **Background** — always #0D1B2A dark navy unless specified otherwise

---

## Asset Library (generate all of these)

### Asset 1 — Profile / Avatar
Square crop. Face + upper chest. Centered.
Prompt suffix: `square format, face and upper chest centered, dark navy background #0D1B2A`

### Asset 2 — Full Body
Standing, arms relaxed at sides or one hand in hoodie pocket.
Prompt suffix: `full body, standing, hands relaxed, dark navy background, game character sheet style`

### Asset 3 — Face Only (close crop)
Just the face, no neck. For emoji, reactions, small icons.
Prompt suffix: `tight face crop, no neck, circular mask, dark navy background`

### Asset 4 — Side Profile
90 degree side view, same face spec.
Prompt suffix: `side profile view, 90 degrees, dark navy background`

### Asset 5 — Working Pose
Sitting at a desk, hands on keyboard, multiple terminal windows glowing behind. Same face.
Prompt suffix: `seated at desk, hands on keyboard, terminal windows glowing blue in background, dark navy background`

### Asset 6 — Thinking Pose
Standing, one arm crossed, other hand on chin, eyes slightly upward.
Prompt suffix: `thinking pose, one hand on chin, looking slightly up, dark navy background`

---

## Locked Base (v4 — FINAL, do not change without Kamal approval)

Reference file: `vault/memory/kamil_avatar.png`
Approved: 2026-06-05

Exact face attributes from approved image:
- Strong angular jaw, slightly wide
- Black hair swept back with volume, fade on sides
- Full medium-length beard, dark, defined edges
- Eyes: dark, half-lidded, left brow slightly raised
- Expression: closed mouth, subtle smirk right side — calm and knowing
- Rounded square border with dark navy frame
- 4-pointed silver star bottom-right

## Master Prompt Template

Use this base for every asset — append the asset-specific suffix:

> **Same character as reference: stylised game character, male, warm medium-brown skin, strong angular jaw, black hair swept back with volume, full dark beard with defined edges, dark half-lidded eyes, left eyebrow slightly raised, subtle smirk right side only. Black technical hoodie with drawstrings. Dark navy background #0D1B2A. Rounded square border. Semi-realistic cartoon style, clean bold outlines, soft shading. Game asset quality. 4-pointed silver star bottom-right corner. [ASSET SUFFIX HERE]**

---

## Style Reference

| Do | Don't |
|---|---|
| Valorant agent meets Notion avatar | Anime |
| Soft shading, clean outlines | Flat design (too simple) |
| Game character sheet consistency | Photorealistic |
| Same face every single time | Varying the expression |
| Dark moody palette | Bright colorful backgrounds |

---

## Version History

| Version | Date | Change |
|---|---|---|
| v1 | 2026-06-04 | First cartoon — circular, minimal |
| v2 | 2026-06-04 | Full beard, swept hair, semi-realistic |
| v3 | 2026-06-05 | Full redesign — game character spec, asset library, locked palette |
| v4 | 2026-06-05 | Base face approved — locked. Asset 1 saved. |
