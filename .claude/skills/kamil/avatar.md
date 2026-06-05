# Kamil Avatar — Visual Identity Spec

> Single source of truth for generating Kamil's face.
> Read this file before any image generation task.
> Approved reference: `vault/memory/kamil_avatar.png`

## Core Rules
- Always use this spec. Never guess or improvise attributes.
- Style is semi-realistic cartoon — not flat design, not photorealistic.
- When regenerating: match every attribute below exactly.
- If an attribute needs changing, update this file first, then generate.

---

## Face

| Attribute | Value |
|---|---|
| Ethnicity | Pakistani |
| Age | Late 20s |
| Skin tone | Medium-brown, warm undertone |
| Face shape | Oval, strong jaw |
| Expression | Calm, subtle half-smile — confident, knowing. Not happy, not serious. |
| Eyebrows | Dark, slightly thick, natural arch |
| Eyes | Dark brown, calm, slightly knowing — like he already read your PR |
| Nose | Natural, medium width |
| Lips | Neutral, relaxed, slight upturn on one side |

---

## Hair

| Attribute | Value |
|---|---|
| Style | Swept to one side, slight volume on top |
| Length | Short-medium on top, faded on sides |
| Color | Black |
| Texture | Smooth, clean lines |

---

## Beard

| Attribute | Value |
|---|---|
| Style | Full beard, well-groomed |
| Length | Short-medium, close to face |
| Color | Dark black |
| Edges | Clean, defined |

---

## Clothing

| Attribute | Value |
|---|---|
| Item | Black hoodie |
| Details | Drawstrings visible, hood down |
| Color | Black / very dark charcoal |
| Fit | Relaxed |

---

## Background & Composition

| Attribute | Value |
|---|---|
| Background color | Dark navy (#0d1b2a or similar) |
| Background style | Solid, no texture |
| Crop | Square — face and upper chest, centered |
| Lighting | Soft, slightly from front-left |
| Extra detail | Small 4-pointed star bottom-right corner (subtle) |

---

## Style

| Attribute | Value |
|---|---|
| Illustration style | Semi-realistic cartoon / vector with soft shading |
| Outline | Clean bold lines, dark outlines |
| Shading | Soft gradient shading — not flat, not photorealistic |
| Detail level | Medium-high — more than emoji/flat, less than portrait |
| Vibe | Confident senior engineer. The kind who DMs you "found it" at 2am. |

---

## Canonical Prompt (assemble from spec above)

> Semi-realistic cartoon avatar of a Pakistani man, late 20s. Medium-brown warm skin, black hair swept to one side with a fade on the sides. Full well-groomed dark beard. Dark brown calm eyes, subtle knowing half-smile — confident, not happy. Black hoodie with drawstrings visible, hood down. Dark navy square background (#0d1b2a). Clean vector illustration with soft shading. Face and upper chest centered. Small 4-pointed star bottom-right corner.

---

## Version History

| Version | Date | Change |
|---|---|---|
| v1 | 2026-06-04 | First cartoon — circular crop, minimal detail |
| v2 | 2026-06-04 | Upgraded — full beard, swept hair, semi-realistic shading. **Current.** |

## What to Avoid
- No photorealistic skin
- No robot elements, circuits, glowing eyes
- No full smile — always calm half-smile
- No bright or busy backgrounds
- No generic South Asian or Middle Eastern features — Pakistani specifically
- Never regenerate without reading this file first
