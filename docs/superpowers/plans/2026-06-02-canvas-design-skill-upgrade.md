# Canvas Design Skill Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace generic TED-Ed template designs with museum-quality, philosophy-driven art by adopting the Anthropic canvas-design skill methodology — design philosophy first, then visual expression — across Kamil's Canva skill and pipeline.

**Architecture:** Two-step process: (1) `scripts/design_philosopher.py` generates a named aesthetic movement + 4-6 paragraph manifesto for a given topic+channel, (2) `build_design_prompt()` in `canva_designer.py` uses that philosophy as the creative brief instead of a style template suffix. The `.claude/skills/canva/skill.md` is rewritten to embed the Anthropic canvas-design methodology so Claude follows it whenever the skill is invoked. The existing `kamil_canva_agent.py` orchestration is unchanged — only the prompt generation layer changes.

**Tech Stack:** Python 3.10+, `claude --dangerously-skip-permissions --print -p` subprocess (cwd=/tmp), Canva MCP (`mcp__claude_ai_Canva__generate-design`), brand kit `kAHLIxSiVa8`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `scripts/design_philosopher.py` | Create | Generates named aesthetic movement + philosophy manifesto for a topic |
| `scripts/canva_designer.py` | Modify | `build_design_prompt()` uses philosophy instead of style suffix |
| `.claude/skills/canva/skill.md` | Rewrite | Embed full Anthropic canvas-design methodology |
| `tests/test_design_philosopher.py` | Create | Unit tests for philosophy generation |

---

## Task 1: Create `scripts/design_philosopher.py`

**Files:**
- Create: `scripts/design_philosopher.py`
- Create: `tests/test_design_philosopher.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_design_philosopher.py`:

```python
#!/usr/bin/env python3
"""Tests for design_philosopher.py"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from design_philosopher import (
    build_philosophy_prompt,
    parse_philosophy_output,
    DesignPhilosophy,
)


class TestDesignPhilosophy(unittest.TestCase):
    def test_dataclass_fields(self):
        p = DesignPhilosophy(
            movement_name="Chromatic Silence",
            manifesto="Color as primary information system.",
            canvas_directive="Express through bold color fields.",
        )
        self.assertEqual(p.movement_name, "Chromatic Silence")
        self.assertIsNotNone(p.manifesto)
        self.assertIsNotNone(p.canvas_directive)


class TestBuildPhilosophyPrompt(unittest.TestCase):
    def test_prompt_contains_topic(self):
        prompt = build_philosophy_prompt("Daily workout for men", "fitness", "instagram_post")
        self.assertIn("Daily workout for men", prompt)

    def test_prompt_contains_channel(self):
        prompt = build_philosophy_prompt("AI tips", "tech", "youtube_thumbnail")
        self.assertIn("youtube_thumbnail", prompt)

    def test_prompt_requests_movement_name(self):
        prompt = build_philosophy_prompt("t", "fitness", "instagram_post")
        self.assertIn("movement_name", prompt)

    def test_prompt_requests_manifesto(self):
        prompt = build_philosophy_prompt("t", "fitness", "instagram_post")
        self.assertIn("manifesto", prompt)

    def test_prompt_requests_canvas_directive(self):
        prompt = build_philosophy_prompt("t", "fitness", "instagram_post")
        self.assertIn("canvas_directive", prompt)


class TestParsePhilosophyOutput(unittest.TestCase):
    def test_valid_json_parsed(self):
        import json
        raw = json.dumps({
            "movement_name": "Kinetic Silence",
            "manifesto": "Motion as the primary language of form. Space breathes.",
            "canvas_directive": "Bold geometric forms, high contrast, minimal text.",
        })
        result = parse_philosophy_output(raw)
        self.assertIsInstance(result, DesignPhilosophy)
        self.assertEqual(result.movement_name, "Kinetic Silence")

    def test_json_in_code_fence_parsed(self):
        import json
        raw = "Here's the philosophy:\n```json\n" + json.dumps({
            "movement_name": "Brutal Joy",
            "manifesto": "Heavy geometry meets exuberance.",
            "canvas_directive": "Oversized type, one color block, silence.",
        }) + "\n```"
        result = parse_philosophy_output(raw)
        self.assertIsInstance(result, DesignPhilosophy)
        self.assertEqual(result.movement_name, "Brutal Joy")

    def test_malformed_returns_fallback(self):
        result = parse_philosophy_output("not json")
        self.assertIsInstance(result, DesignPhilosophy)
        self.assertIsNotNone(result.movement_name)
        self.assertGreater(len(result.manifesto), 10)

    def test_partial_json_uses_defaults(self):
        import json
        raw = json.dumps({"movement_name": "Only Name"})
        result = parse_philosophy_output(raw)
        self.assertIsInstance(result, DesignPhilosophy)
        self.assertIsNotNone(result.manifesto)
```

- [ ] **Step 2: Run tests to confirm FAIL**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m pytest tests/test_design_philosopher.py -v 2>&1 | head -15
```

Expected: `ModuleNotFoundError: No module named 'design_philosopher'`

- [ ] **Step 3: Create `scripts/design_philosopher.py`**

```python
#!/usr/bin/env python3
"""
design_philosopher.py — Generate a named aesthetic movement + manifesto for a topic.

Step 1 of the Anthropic canvas-design methodology:
  topic + channel → DesignPhilosophy (movement name + manifesto + canvas directive)

The philosophy is then fed into build_design_prompt() in canva_designer.py as the
creative brief, replacing generic style templates.

Usage:
  python3 scripts/design_philosopher.py --topic "Daily workout" --track fitness --format instagram_post
  # outputs JSON to stdout

Returns JSON:
  {
    "movement_name": "Kinetic Silence",
    "manifesto": "4-6 paragraph philosophy ...",
    "canvas_directive": "How to express this visually on the canvas"
  }
"""
import argparse
import json
import re
import subprocess
from dataclasses import dataclass


@dataclass
class DesignPhilosophy:
    movement_name: str
    manifesto: str
    canvas_directive: str


def build_philosophy_prompt(topic: str, track: str, design_type: str) -> str:
    return (
        f"You are a world-class art director creating a design philosophy for a {design_type} social post "
        f"about '{topic}' for a {track} content creator. "
        f"Create an original aesthetic movement — not a template, not a style guide — a genuine philosophical stance. "
        f"Name the movement (1-2 evocative words). Write a 4-paragraph manifesto for it covering: "
        f"(1) the core visual philosophy and what it rejects, "
        f"(2) how space, form, and color operate in this movement, "
        f"(3) the emotional register and cultural references it draws from, "
        f"(4) what expert craftsmanship looks like in this movement — meticulously labored, painstaking, master-level. "
        f"Then write a canvas_directive: 3-4 sentences of precise visual instruction for expressing this philosophy "
        f"in a single {design_type} image — what visual elements dominate, what is absent, how text behaves as a visual element. "
        f"The philosophy must emphasize: 90 percent visual, 10 percent text. No generic AI aesthetics. "
        f"Return ONLY valid JSON with keys: movement_name (string), manifesto (string), canvas_directive (string). "
        f"The topic '{topic}' is the soul embedded invisibly in the work — not announced, just felt."
    )


def parse_philosophy_output(raw: str) -> DesignPhilosophy:
    """Parse claude output into DesignPhilosophy. Returns fallback on any error."""
    try:
        cleaned = raw.strip()
        # Extract from code fence anywhere in output
        if "```" in cleaned:
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
            if match:
                cleaned = match.group(1)
        # Find first JSON object if not pure JSON
        if not cleaned.startswith("{"):
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                cleaned = match.group(0)
        data = json.loads(cleaned)
        return DesignPhilosophy(
            movement_name=str(data.get("movement_name", "Chromatic Tension")),
            manifesto=str(data.get("manifesto", "Visual language speaks louder than words. Form is meaning.")),
            canvas_directive=str(data.get("canvas_directive", "Bold composition, minimal text, maximum visual impact.")),
        )
    except Exception:
        return DesignPhilosophy(
            movement_name="Kinetic Silence",
            manifesto=(
                "This movement rejects decoration in favor of force. Every element earns its place "
                "through visual necessity, not habit. The canvas is a battlefield where only the essential survives. "
                "Space is not empty — it is taut, charged, waiting. Color does not decorate; it commands. "
                "Form communicates before the eye even settles. The work demands sustained attention and rewards it "
                "with layers that reveal themselves slowly, like a master craftsman's hand emerging from the surface. "
                "Typography is sculpture, not caption. This is work that took countless hours, and shows it."
            ),
            canvas_directive=(
                "Dominant geometric form anchors the composition. One color field commands attention; "
                "a second accent color appears sparingly. Typography is structural — large, weighted, "
                "integrated into the visual architecture rather than placed on top of it. "
                "90% of the canvas is image and form; text is a single essential gesture."
            ),
        )


def create_philosophy(topic: str, track: str, design_type: str) -> DesignPhilosophy:
    """Run claude to generate design philosophy. Returns DesignPhilosophy (never raises)."""
    prompt = build_philosophy_prompt(topic, track, design_type)
    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt],
            capture_output=True, text=True, timeout=120,
            cwd="/tmp",
        )
        if result.returncode != 0 or not result.stdout.strip():
            return parse_philosophy_output("")
        return parse_philosophy_output(result.stdout)
    except Exception:
        return parse_philosophy_output("")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--track", required=True, choices=["fitness", "tech", "vlog"])
    parser.add_argument("--format", dest="design_type", required=True)
    args = parser.parse_args()

    result = create_philosophy(args.topic, args.track, args.design_type)
    print(json.dumps({
        "movement_name": result.movement_name,
        "manifesto": result.manifesto,
        "canvas_directive": result.canvas_directive,
    }, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to confirm PASS**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m pytest tests/test_design_philosopher.py -v
```

Expected: 9/9 PASS

- [ ] **Step 5: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add scripts/design_philosopher.py tests/test_design_philosopher.py
git commit -m "feat: add design_philosopher — philosophy-first canvas design approach"
```

---

## Task 2: Update `build_design_prompt()` in `scripts/canva_designer.py`

**Files:**
- Modify: `scripts/canva_designer.py`

The current `build_design_prompt()` appends a generic style suffix. Replace it with a philosophy-driven prompt that uses the Anthropic canvas-design methodology.

- [ ] **Step 1: Read the current build_design_prompt function**

```bash
grep -n "def build_design_prompt" /home/oye/Documents/free_work/personal-agent-v2/scripts/canva_designer.py
sed -n '38,55p' /home/oye/Documents/free_work/personal-agent-v2/scripts/canva_designer.py
```

Confirm the function signature is `build_design_prompt(topic, copy, channel, fmt)`.

- [ ] **Step 2: Add design_philosopher import at top of canva_designer.py**

Find the imports block (lines 1-15). After `from pathlib import Path`, add:

```python
import sys as _sys
_SCRIPTS_DIR = str(Path(__file__).parent)
if _SCRIPTS_DIR not in _sys.path:
    _sys.path.insert(0, _SCRIPTS_DIR)
from design_philosopher import create_philosophy, DesignPhilosophy
```

- [ ] **Step 3: Replace build_design_prompt() with the new philosophy-driven version**

Find the entire `build_design_prompt` function and replace it with:

```python
def build_design_prompt(topic: str, copy: str, channel: str, fmt: str) -> str:
    """
    Two-step Anthropic canvas-design approach:
    1. Generate a named aesthetic movement + manifesto (design_philosopher)
    2. Express that philosophy visually on the canvas
    """
    tmpl = TEMPLATE_MAP.get((channel, fmt), {})
    w = tmpl.get("width", 1080)
    h = tmpl.get("height", 1080)

    # Step 1: Generate design philosophy
    philosophy = create_philosophy(topic, channel, fmt)

    # Step 2: Build canvas expression prompt from philosophy
    return (
        f"You are expressing the aesthetic movement '{philosophy.movement_name}' as a single {channel} {fmt} "
        f"design ({w}x{h}px). "
        f"PHILOSOPHY: {philosophy.manifesto} "
        f"CANVAS DIRECTIVE: {philosophy.canvas_directive} "
        f"CONTENT SOUL (embedded invisibly, not announced): The topic '{topic}' lives in the visual DNA — "
        f"felt by those who know it, invisible to those who don't. "
        f"The only text permitted: '{copy}' — treated as a sculptural typographic element, "
        f"not a caption. It is part of the composition, not placed on top of it. "
        f"CRITICAL QUALITY STANDARD: This must look like it took countless hours of expert craftsmanship. "
        f"Museum-quality. Painstaking attention. The work of someone at the absolute top of their field. "
        f"90% visual composition, 10% essential text. Full bleed, no border, no frame. "
        f"DO NOT produce generic AI aesthetics. DO NOT produce clip-art or illustration templates. "
        f"DO NOT include layout labels or meta-instructions in the image."
    )
```

- [ ] **Step 4: Verify syntax is clean**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "import ast; ast.parse(open('scripts/canva_designer.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 5: Run existing canva_designer tests to confirm nothing broke**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m pytest tests/test_canva_designer.py -v
```

Expected: all tests PASS. Note: `test_prompt_includes_topic_and_copy` may need updating — the new prompt still contains topic and copy, just structured differently. If it fails, check what the test asserts and confirm topic/copy are still present in the new prompt.

- [ ] **Step 6: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add scripts/canva_designer.py
git commit -m "feat: philosophy-driven build_design_prompt via Anthropic canvas-design methodology"
```

---

## Task 3: Rewrite `.claude/skills/canva/skill.md`

**Files:**
- Modify: `.claude/skills/canva/skill.md`

- [ ] **Step 1: Rewrite the skill file**

Replace the entire contents of `.claude/skills/canva/skill.md` with:

```markdown
# Canva Design Skill

Kamil's on-demand Canva design interface. Triggered when Kamil asks to create
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
4. **Build Canva prompt** using the philosophy (see Task 2 prompt structure)
5. **Call** `mcp__claude_ai_Canva__generate-design` with `brand_kit_id=kAHLIxSiVa8`
6. **All 4 candidates** are generated — pick the most artistically resolved one (not the safest)
7. **Save** via `mcp__claude_ai_Canva__create-design-from-candidate`
8. **Export** PNG via `mcp__claude_ai_Canva__export-design` (format: png, quality: pro)
9. **Download + post to Slack** DM (`D0B415M06SK`) using `files.getUploadURLExternal` flow
10. **Share edit URL** so Kamil can refine

**Brand kit ID:** `kAHLIxSiVa8`  
**Slack DM:** `D0B415M06SK`

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
```

- [ ] **Step 2: Verify file was written**

```bash
head -5 /home/oye/Documents/free_work/personal-agent-v2/.claude/skills/canva/skill.md
```

Expected: first line is `# Canva Design Skill`

- [ ] **Step 3: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/skills/canva/skill.md
git commit -m "feat: rewrite canva skill with Anthropic canvas-design philosophy methodology"
```

---

## Task 4: Smoke test — generate one design with the new approach

**Files:** None (live test)

- [ ] **Step 1: Test design_philosopher standalone**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 scripts/design_philosopher.py --topic "Daily workout progression for men" --track fitness --format instagram_post 2>&1
```

Expected: JSON with `movement_name` (evocative 1-2 words), `manifesto` (multiple sentences), `canvas_directive` (3-4 sentences). Should NOT be generic — should read like an art manifesto.

- [ ] **Step 2: Test build_design_prompt produces philosophy-driven output**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "
import sys; sys.path.insert(0, 'scripts')
from canva_designer import build_design_prompt
prompt = build_design_prompt('Daily workout for men', 'Built different.', 'instagram', 'post')
print(prompt[:600])
"
```

Expected: prompt contains a movement name, manifesto language, canvas directive — NOT a TED-Ed suffix.

- [ ] **Step 3: Run all tests**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m pytest tests/ -v 2>&1 | tail -15
```

Expected: all tests pass.

- [ ] **Step 4: Generate a live Canva design with the new approach**

In a Claude session with Canva MCP connected, invoke the canva skill:

```
Make an Instagram post about daily workout progression for men. Copy: "Built different."
```

The skill should:
1. Generate a philosophy (movement name + manifesto visible in process)
2. Build a philosophy-driven Canva prompt
3. Generate candidates
4. Post to Slack DM

Compare the result to the previous TED-Ed output — should look like art, not a template.

- [ ] **Step 5: Commit any fixes**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add -p
git commit -m "fix: smoke test fixes for philosophy-driven canvas design"
```

---

## Self-Review

**Spec coverage:**
- ✅ Anthropic canvas-design 2-step methodology (philosophy → canvas) — Tasks 1 + 2
- ✅ Named aesthetic movement with manifesto — Task 1 `DesignPhilosophy` dataclass
- ✅ Topic embedded as invisible soul, not announced — Task 2 prompt
- ✅ Text as sculptural element — Task 2 prompt
- ✅ Museum-quality craftsmanship demanded — Task 2 prompt
- ✅ Skill updated to embed full methodology — Task 3
- ✅ Quality gate updated to require philosophy — Task 3
- ✅ Smoke test with live Canva generation — Task 4

**No placeholders.**

**Type consistency:**
- `DesignPhilosophy` defined in Task 1, imported in Task 2
- `create_philosophy(topic, channel, fmt)` signature used consistently
- `build_design_prompt(topic, copy, channel, fmt)` signature unchanged — existing callers unaffected
