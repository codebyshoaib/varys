---
type: rule
owner: varys
last_verified: 2026-06-19
paths:
  - ".claude/skills/linkedin-post/SKILL.md"
  - ".claude/hooks/linkedin_poster.py"
---

# Infographic Generation — Conventions (NotebookLM)

Hard-won from the first real LinkedIn run. Read before generating any infographic via NotebookLM (`nlm infographic create`).

## The pipeline

```
notebook create → source add --wait → infographic create → poll studio status
  → download → normalize to 4:5 → SHOW for human approval → linkedin_poster.py
```

Never post without the 4:5 normalization step and human approval.

## Command — always use these flags

```bash
nlm infographic create "$NB_ID" --orientation portrait --detail concise --style editorial --confirm
```

Valid values:

- `--orientation` : `landscape | portrait | square` (default landscape). LinkedIn → **portrait**.
- `--detail` : `concise | standard | detailed` (default standard). **`brief` is NOT valid — it errors.**
- `--style` : `auto_select | sketch_note | professional | bento_grid | editorial | instructional | bricks | clay | anime | kawaii | scientific`.
- `--focus "<topic>"` : optional steer.

## Gotchas (the whole reason this file exists)

1. **Always pass an explicit `--style`.** Default `auto_select` produces generic, dull, system-font output. `editorial` gave the best result — illustrated etching style, serif type, distinctive, not template-y. `bento_grid` is the modern-card alternative.

2. **Raw output is a 9:16 sliver → black gutters on LinkedIn.** Native portrait export is **1536×2752** (ratio ~0.56). LinkedIn caps portrait at **4:5 (0.8)**, so a taller image renders narrow with dark side bars. **You MUST pad to 4:5 before posting** (snippet below).

3. **`concise` caps at ~4 panels.** If the source has 5+ points, concise renders only 4 and re-rolling just swaps _which_ 4 (NLM is non-deterministic). To force all N panels use `--detail standard` — but that brings back more text per panel (the thing we were cutting). Trade-off: prefer concise + let the post caption carry the full list; the image is a visual hook, not the whole argument.

4. **Fonts/text are NOT controllable in NLM.** It auto-styles everything. If you need brand fonts or exact wording, NLM is the wrong tool — hand-build HTML + inline SVG icons and render via headless browser instead (see fallback below).

5. **Source content shapes the text.** NLM derives panel copy from the notebook sources. Write the source headline-first and lean for less text; verbose sources → verbose panels.

6. **Anonymize at the source.** Strip client / portal / people / company names from the source text BEFORE generating — NLM will surface whatever is in the sources. (We post about Taleemabad/PEFSIS work generically: "an upstream government portal", "our platform".)

## 4:5 normalization (required) — PIL, no ImageMagick needed

Samples the parchment/background colour from the corners and pads width to a true 4:5, then downscales to LinkedIn's 1080×1350.

```python
from PIL import Image
from collections import Counter
im = Image.open(SRC).convert("RGB"); w, h = im.size; px = im.load()
samp = []
P = 24
for cx, cy in [(0,0),(w-P,0),(0,h-P),(w-P,h-P),(w//2,0),(w//2,h-P)]:
    for x in range(cx, cx+P):
        for y in range(cy, cy+P):
            samp.append(px[min(x,w-1), min(y,h-1)])
bg = Counter([(r//8*8,g//8*8,b//8*8) for r,g,b in samp]).most_common(1)[0][0]
tw = int(round(h*0.8))                      # 4:5 target width
canvas = Image.new("RGB", (tw,h), bg); canvas.paste(im, ((tw-w)//2, 0))
canvas.resize((1080,1350), Image.LANCZOS).save(OUT)
```

Works cleanly when the infographic has a near-uniform background to its edges (editorial/professional do). For full-bleed dark/photo styles the flat-fill pad may seam — re-check visually.

## Posting

```bash
python3 /home/shoaib/varys/.claude/hooks/linkedin_poster.py --image <4x5.png> --text "<copy>"
```

- No `@handle` in the body. Hashtags: 3 max, last line only.
- Auth error → `python3 .claude/hooks/linkedin_oauth.py` then retry.

## HTML fallback (when NLM's look/fonts aren't enough)

Build the infographic as HTML + inline SVG icons (full control over type, palette, text density), then render:

- `file://` is **blocked** in our Playwright — serve it: `python3 -m http.server <port>` from the file's dir, navigate to `http://localhost:<port>/...`.
- Wait for `document.fonts.ready`; Google Fonts `@import` works (browser has network).
- Screenshot the card element (`page.locator('.card').screenshot(...)`), not the viewport.
- Clean up: the screenshot lands in CWD and a `.playwright-mcp/` dir — move to scratchpad and delete both; never leave them in a repo.
