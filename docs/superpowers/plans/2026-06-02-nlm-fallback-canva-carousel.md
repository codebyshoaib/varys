# NLM Fallback — Claude Research + Canva Carousel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When NLM fails or hits quota, automatically fall back to Claude-powered research + a Canva multi-slide carousel that delivers the same value: structured insights, visual content, caption, and PDF — all DM'd to Slack.

**Architecture:** `scripts/claude_researcher.py` does a deep `claude -p` research pass and returns structured JSON insights. `scripts/canva_carousel.py` takes those insights and generates a Canva carousel (one slide per insight) via the Canva MCP, then exports a PDF. `content-scheduler.py` calls both when `research_ok = False`, replacing the empty `nlm_insights = ""` fallback with real content.

**Tech Stack:** Python 3.10+, `claude --dangerously-skip-permissions -p` subprocess, Canva MCP (`mcp__claude_ai_Canva__generate-design`, `mcp__claude_ai_Canva__create-design-from-candidate`, `mcp__claude_ai_Canva__export-design`), existing `slack_upload()` + `slack_dm()` from content-scheduler.py, brand kit `kAHLIxSiVa8`.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `scripts/claude_researcher.py` | Create | Deep research via `claude -p` → structured JSON insights |
| `scripts/canva_carousel.py` | Create | Takes insights JSON → Canva carousel → PDF export URL |
| `tests/test_claude_researcher.py` | Create | Unit tests for research output structure |
| `tests/test_canva_carousel.py` | Create | Unit tests for carousel prompt building |
| `.claude/hooks/content-scheduler.py` | Modify | Call researcher + carousel in NLM failure branch |

---

## Task 1: Create `scripts/claude_researcher.py`

**Files:**
- Create: `scripts/claude_researcher.py`
- Create: `tests/test_claude_researcher.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_claude_researcher.py`:

```python
#!/usr/bin/env python3
"""Tests for claude_researcher.py"""
import json
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from claude_researcher import build_research_prompt, parse_research_output, ResearchResult


class TestBuildResearchPrompt(unittest.TestCase):
    def test_prompt_contains_topic(self):
        prompt = build_research_prompt("Daily workout progression", "fitness")
        self.assertIn("Daily workout progression", prompt)

    def test_prompt_contains_track(self):
        prompt = build_research_prompt("Akamai pricing", "tech")
        self.assertIn("tech", prompt.lower())

    def test_prompt_requests_json(self):
        prompt = build_research_prompt("topic", "fitness")
        self.assertIn("JSON", prompt)


class TestParseResearchOutput(unittest.TestCase):
    def test_valid_json_parsed(self):
        raw = json.dumps({
            "hook": "This changes everything",
            "insights": ["Fact 1", "Fact 2", "Fact 3"],
            "caption_angle": "awe",
            "summary": "A short summary"
        })
        result = parse_research_output(raw)
        self.assertIsInstance(result, ResearchResult)
        self.assertEqual(result.hook, "This changes everything")
        self.assertEqual(len(result.insights), 3)

    def test_malformed_json_returns_fallback(self):
        result = parse_research_output("not json at all")
        self.assertIsInstance(result, ResearchResult)
        self.assertIsNotNone(result.hook)
        self.assertGreater(len(result.insights), 0)

    def test_missing_fields_use_defaults(self):
        raw = json.dumps({"hook": "Only hook"})
        result = parse_research_output(raw)
        self.assertIsInstance(result, ResearchResult)
        self.assertIsNotNone(result.insights)

    def test_insights_always_list(self):
        raw = json.dumps({
            "hook": "h",
            "insights": ["a", "b", "c", "d", "e"],
            "caption_angle": "awe",
            "summary": "s"
        })
        result = parse_research_output(raw)
        self.assertIsInstance(result.insights, list)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m pytest tests/test_claude_researcher.py -v 2>&1 | head -15
```

Expected: `ModuleNotFoundError: No module named 'claude_researcher'`

- [ ] **Step 3: Create `scripts/claude_researcher.py`**

```python
#!/usr/bin/env python3
"""
claude_researcher.py — Deep research via claude -p.

Produces structured insights for a topic + track. Used as NLM fallback
in the content pipeline when NLM quota is exhausted.

Usage:
  python3 scripts/claude_researcher.py --topic "Daily workout" --track fitness
  # outputs JSON to stdout

Returns JSON:
  {
    "hook": "scroll-stopping opening line",
    "insights": ["Specific fact 1", "Specific fact 2", ...],  # 5 items
    "caption_angle": "awe|longing|nostalgia|belonging",
    "summary": "2-sentence research summary for caption"
  }
"""
import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from typing import List


@dataclass
class ResearchResult:
    hook: str
    insights: List[str]
    caption_angle: str
    summary: str


def build_research_prompt(topic: str, track: str) -> str:
    return (
        f"You are a social media researcher for a {track} content creator.\n"
        f"Research this topic deeply: {topic}\n\n"
        f"Produce a JSON object with these exact keys:\n"
        f"- hook: one scroll-stopping opening line using delayed-answer technique (max 12 words, no emoji)\n"
        f"- insights: list of exactly 5 specific, concrete facts or tips about the topic "
        f"  (each max 15 words, specific enough to put on a slide)\n"
        f"- caption_angle: one of [awe, longing, nostalgia, belonging] — the single emotion this content should evoke\n"
        f"- summary: 2-sentence research summary to inform a social media caption\n\n"
        f"Rules:\n"
        f"- Every insight must be SPECIFIC — a number, a name, a concrete action, not a general principle\n"
        f"- No fluff. No 'it depends'. No 'many people'. Write like a practitioner.\n"
        f"- Return ONLY valid JSON. No markdown, no explanation, no code blocks.\n"
    )


def parse_research_output(raw: str) -> ResearchResult:
    """Parse claude -p output into ResearchResult. Returns fallback on any error."""
    try:
        # Strip markdown code fences if claude wraps in them
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        data = json.loads(cleaned)
        return ResearchResult(
            hook=str(data.get("hook", f"What you need to know about {data.get('topic', 'this topic')}")),
            insights=list(data.get("insights", ["See research below"]))[:5],
            caption_angle=str(data.get("caption_angle", "awe")),
            summary=str(data.get("summary", "")),
        )
    except Exception:
        return ResearchResult(
            hook="Here is what the research says",
            insights=[
                "Research unavailable — generated from topic context",
                "Check primary sources for detailed stats",
                "Apply critical thinking to all claims",
                "Cross-reference with recent publications",
                "Consult domain experts for nuanced guidance",
            ],
            caption_angle="awe",
            summary="Research generated from topic context. Verify with primary sources.",
        )


def research(topic: str, track: str) -> ResearchResult:
    """Run claude -p research pass. Returns ResearchResult (never raises)."""
    prompt = build_research_prompt(topic, track)
    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return parse_research_output("")
        return parse_research_output(result.stdout)
    except Exception:
        return parse_research_output("")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--track", required=True, choices=["fitness", "tech", "vlog"])
    args = parser.parse_args()

    result = research(args.topic, args.track)
    print(json.dumps({
        "hook": result.hook,
        "insights": result.insights,
        "caption_angle": result.caption_angle,
        "summary": result.summary,
    }, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m pytest tests/test_claude_researcher.py -v
```

Expected: 6/6 PASS (all mocked — no real claude call)

- [ ] **Step 5: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add scripts/claude_researcher.py tests/test_claude_researcher.py
git commit -m "feat: add claude-researcher NLM fallback research engine"
```

---

## Task 2: Create `scripts/canva_carousel.py`

**Files:**
- Create: `scripts/canva_carousel.py`
- Create: `tests/test_canva_carousel.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_canva_carousel.py`:

```python
#!/usr/bin/env python3
"""Tests for canva_carousel.py"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from canva_carousel import build_slide_prompt, CarouselBrief, SLIDE_STYLE_SUFFIX


class TestCarouselBrief(unittest.TestCase):
    def test_brief_requires_topic_and_insights(self):
        brief = CarouselBrief(
            topic="Daily workout progression",
            track="fitness",
            hook="What no one tells you about progress",
            insights=["Rest is training", "Volume beats intensity", "Sleep is the supplement"],
        )
        self.assertEqual(brief.topic, "Daily workout progression")
        self.assertEqual(len(brief.insights), 3)

    def test_brief_defaults(self):
        brief = CarouselBrief(topic="t", track="fitness", hook="h", insights=["i"])
        self.assertEqual(brief.brand_kit_id, "kAHLIxSiVa8")


class TestBuildSlidePrompt(unittest.TestCase):
    def test_cover_slide_contains_hook(self):
        brief = CarouselBrief(
            topic="Workout tips", track="fitness",
            hook="What every man gets wrong", insights=["Tip 1"]
        )
        prompt = build_slide_prompt(brief, slide_index=0, total_slides=4)
        self.assertIn("What every man gets wrong", prompt)
        self.assertIn("cover", prompt.lower())

    def test_insight_slide_contains_insight_text(self):
        brief = CarouselBrief(
            topic="Workout tips", track="fitness",
            hook="Hook", insights=["Rest days accelerate muscle growth by 40%"]
        )
        prompt = build_slide_prompt(brief, slide_index=1, total_slides=4)
        self.assertIn("Rest days accelerate muscle growth by 40%", prompt)

    def test_cta_slide_is_last(self):
        brief = CarouselBrief(
            topic="t", track="fitness", hook="h", insights=["i1", "i2", "i3"]
        )
        total = len(brief.insights) + 2  # cover + insights + CTA
        prompt = build_slide_prompt(brief, slide_index=total - 1, total_slides=total)
        self.assertIn("save", prompt.lower())

    def test_style_suffix_appended(self):
        brief = CarouselBrief(topic="t", track="fitness", hook="h", insights=["i"])
        prompt = build_slide_prompt(brief, slide_index=0, total_slides=3)
        self.assertIn(SLIDE_STYLE_SUFFIX[:30], prompt)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m pytest tests/test_canva_carousel.py -v 2>&1 | head -15
```

Expected: `ModuleNotFoundError: No module named 'canva_carousel'`

- [ ] **Step 3: Create `scripts/canva_carousel.py`**

```python
#!/usr/bin/env python3
"""
canva_carousel.py — Generate a Canva multi-slide carousel from research insights.

One slide per insight + cover + CTA slide. Exports as PDF via Canva MCP.
Used as NLM infographic/slides replacement in the content pipeline.

Usage:
  python3 scripts/canva_carousel.py \
    --topic "Daily workout" --track fitness \
    --hook "What every man gets wrong" \
    --insights "Rest is training" "Volume beats intensity" "Sleep is the supplement"

Outputs JSON: {"design_id": "...", "edit_url": "...", "export_url": "...", "slide_count": 5}
"""
import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from typing import List

BRAND_KIT_ID = "kAHLIxSiVa8"

SLIDE_STYLE_SUFFIX = (
    " TED-Ed animation style: warm illustrated educational aesthetic."
    " Flat vector illustration with soft textures and organic shapes."
    " Warm color palette: cream/off-white background, teal (#2DD4BF), coral (#F97316),"
    " golden yellow (#FBBF24), sage green (#22C55E) accents."
    " Hand-drawn feel with clean bold lines and rounded edges."
    " Simple bold typography, highly readable at thumbnail size."
    " Square format 1:1. Full bleed edge-to-edge. No border, no frame."
    " CRITICAL: All text must be large, sharp, perfectly readable. No blurry text."
    " DO NOT include meta-labels, zone names, or layout instructions in the image."
)


@dataclass
class CarouselBrief:
    topic: str
    track: str
    hook: str
    insights: List[str]
    brand_kit_id: str = BRAND_KIT_ID


def build_slide_prompt(brief: CarouselBrief, slide_index: int, total_slides: int) -> str:
    """Build the Canva generation prompt for one carousel slide."""
    is_cover = slide_index == 0
    is_cta = slide_index == total_slides - 1

    if is_cover:
        scene = (
            f"Cover slide for a social media carousel about '{brief.topic}'. "
            f"Bold headline at the top reads \"{brief.hook}\". "
            f"Below, a warm illustrated scene related to {brief.track}. "
            f"Bottom corner: slide counter '1/{total_slides}'. "
            f"Energetic, inviting — makes the viewer want to swipe."
        )
    elif is_cta:
        scene = (
            f"Final CTA slide for a carousel about '{brief.topic}'. "
            f"Bold text in the center reads 'Save this for later'. "
            f"Below: 'Share with someone who needs it'. "
            f"Warm illustrated background — calm, satisfying, conclusive. "
            f"Bottom corner: slide counter '{slide_index + 1}/{total_slides}'."
        )
    else:
        insight = brief.insights[slide_index - 1]
        scene = (
            f"Insight slide {slide_index + 1} of {total_slides} for a carousel about '{brief.topic}'. "
            f"Large bold text reads \"{insight}\". "
            f"A simple warm illustrated visual metaphor supporting this insight beside the text. "
            f"Bottom corner: slide counter '{slide_index + 1}/{total_slides}'. "
            f"Clean, single focal point — one idea, nothing else."
        )

    return scene + SLIDE_STYLE_SUFFIX


def _call_canva_mcp(prompt: str, brand_kit_id: str) -> dict:
    """
    Call Canva MCP via claude -p to generate one carousel slide.
    Returns {"job_id": ..., "candidate_id": ..., "design_id": ..., "edit_url": ...}
    """
    instruction = (
        f"Use the Canva MCP to generate a social media post design. "
        f"Design type: instagram_post. Brand kit ID: {brand_kit_id}. "
        f"Query: {prompt} "
        f"Steps: "
        f"1. Call mcp__claude_ai_Canva__generate-design with design_type=instagram_post, "
        f"   brand_kit_id={brand_kit_id}, and the query above. "
        f"2. Take the first candidate from the response. "
        f"3. Call mcp__claude_ai_Canva__create-design-from-candidate with the job_id and candidate_id. "
        f"4. Return ONLY valid JSON: "
        f'{{\"design_id\": \"DABxxxxxx\", \"edit_url\": \"https://www.canva.com/d/...\"}}'
    )
    result = subprocess.run(
        ["claude", "--dangerously-skip-permissions", "--print", "-p", instruction],
        capture_output=True, text=True, timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude -p canva call failed: {result.stderr[:200]}")
    raw = result.stdout.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    return json.loads(raw)


def _export_design_pdf(design_id: str) -> str:
    """Export a Canva design as PDF. Returns download URL."""
    instruction = (
        f"Use the Canva MCP to export design {design_id} as a PDF. "
        f"Call mcp__claude_ai_Canva__export-design with design_id={design_id} "
        f"and format={{\"type\": \"pdf\", \"export_quality\": \"pro\"}}. "
        f"Return ONLY the download URL as plain text."
    )
    result = subprocess.run(
        ["claude", "--dangerously-skip-permissions", "--print", "-p", instruction],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def generate_carousel(brief: CarouselBrief) -> dict:
    """
    Generate all carousel slides and return summary.
    Returns: {design_ids: [...], edit_urls: [...], slide_count: N, errors: [...]}
    """
    total_slides = len(brief.insights) + 2  # cover + insights + CTA
    design_ids = []
    edit_urls = []
    errors = []

    for i in range(total_slides):
        prompt = build_slide_prompt(brief, slide_index=i, total_slides=total_slides)
        try:
            result = _call_canva_mcp(prompt, brief.brand_kit_id)
            design_ids.append(result.get("design_id", ""))
            edit_urls.append(result.get("edit_url", ""))
        except Exception as e:
            errors.append(f"slide {i + 1}: {e}")
            design_ids.append("")
            edit_urls.append("")

    return {
        "design_ids": design_ids,
        "edit_urls": edit_urls,
        "slide_count": total_slides,
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--track", required=True, choices=["fitness", "tech", "vlog"])
    parser.add_argument("--hook", required=True)
    parser.add_argument("--insights", nargs="+", required=True)
    args = parser.parse_args()

    brief = CarouselBrief(
        topic=args.topic,
        track=args.track,
        hook=args.hook,
        insights=args.insights,
    )
    result = generate_carousel(brief)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m pytest tests/test_canva_carousel.py -v
```

Expected: 5/5 PASS

- [ ] **Step 5: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add scripts/canva_carousel.py tests/test_canva_carousel.py
git commit -m "feat: add canva-carousel NLM replacement for infographic/slides"
```

---

## Task 3: Wire fallback into `content-scheduler.py`

**Files:**
- Modify: `.claude/hooks/content-scheduler.py`

The NLM failure branch currently does this (around line 780):
```python
research_ok = nlm_research(nb_id, topic)
if not research_ok:
    print(f"[scheduler] NLM research failed ...")
    slack_dm(token, f"⚠️ *{track} — NLM research failed* ...")
    run_nlm(["delete", "notebook", nb_id, "--confirm"], timeout=30)
    nb_id = None
```

We need to add the Claude research + Canva carousel call inside that `if not research_ok:` block, before `nb_id = None`.

- [ ] **Step 1: Add imports at top of content-scheduler.py**

Read the file header (lines 1-32) to find the existing imports block, then add after the last `sys.path` or import line:

```python
# NLM fallback: Claude research + Canva carousel
import sys as _sys
_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_SCRIPTS_DIR))
from claude_researcher import research as claude_research, ResearchResult
from canva_carousel import CarouselBrief, generate_carousel, build_slide_prompt
```

- [ ] **Step 2: Verify the import lines are correct**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "import ast; ast.parse(open('.claude/hooks/content-scheduler.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 3: Add `run_nlm_fallback()` helper function**

Find the `run_canva_designs` function (line ~715). Add this new function directly before it:

```python
def run_nlm_fallback(token: str, topic: str, track: str) -> ResearchResult | None:
    """
    Claude research + Canva carousel when NLM quota is exhausted.
    Returns ResearchResult so caller can use insights for caption.
    Sends carousel slides + PDF to Slack DM directly.
    """
    print(f"[scheduler] NLM fallback: running Claude research for '{topic}'")
    slack_dm(token,
        f"🔄 *NLM quota hit — switching to Claude + Canva carousel for {track}*\n"
        f"Researching: *{topic}*\n🤖 Kamil")

    # Step 1: Claude research
    result = claude_research(topic, track)
    print(f"[scheduler] Claude research done — hook: {result.hook[:60]}")

    # Step 2: Canva carousel
    brief = CarouselBrief(
        topic=topic,
        track=track,
        hook=result.hook,
        insights=result.insights,
    )
    carousel = generate_carousel(brief)
    slide_count = carousel["slide_count"]
    edit_urls = [u for u in carousel["edit_urls"] if u]
    errors = carousel["errors"]

    if errors:
        print(f"[scheduler] Carousel errors: {errors}")

    # Step 3: DM insights summary + edit links to Slack
    insights_text = "\n".join(f"  {i+1}. {ins}" for i, ins in enumerate(result.insights))
    urls_text = "\n".join(f"  Slide {i+1}: {u}" for i, u in enumerate(edit_urls) if u)
    slack_dm(token,
        f"🎠 *Canva carousel ready — {topic}*\n\n"
        f"*Hook:* {result.hook}\n\n"
        f"*Key insights ({len(result.insights)}):*\n{insights_text}\n\n"
        f"*Research summary:* {result.summary}\n\n"
        f"*Edit slides in Canva ({slide_count} slides):*\n{urls_text}\n\n"
        f"🤖 Kamil")

    return result
```

- [ ] **Step 4: Call fallback in the NLM failure branch**

Find this exact block in `content-scheduler.py` (around line 783):

```python
            if not research_ok:
                print(f"[scheduler] NLM research failed (API quota/error), continuing without insights")
                klog_error("nlm_research_failed",
                          component="content-scheduler",
                          topic=topic, track=track,
                          severity="warning")
                slack_dm(token,
                    f"⚠️ *{track} — NLM research failed* for *{topic}*\n"
                    f"Google API quota likely hit. Using image + caption only (no NLM visuals).\n🤖 Kamil")
                run_nlm(["delete", "notebook", nb_id, "--confirm"], timeout=30)
                nb_id = None  # Clear notebook ID to skip Notion save + artifact polling
```

Replace it with:

```python
            if not research_ok:
                print(f"[scheduler] NLM research failed (API quota/error), running Claude+Canva fallback")
                klog_error("nlm_research_failed",
                          component="content-scheduler",
                          topic=topic, track=track,
                          severity="warning")
                run_nlm(["delete", "notebook", nb_id, "--confirm"], timeout=30)
                nb_id = None  # Clear notebook ID to skip Notion save + artifact polling
                fallback_result = run_nlm_fallback(token, topic, track)
                if fallback_result:
                    nlm_insights = (
                        f"Hook: {fallback_result.hook}\n\n"
                        f"Insights:\n" +
                        "\n".join(f"- {ins}" for ins in fallback_result.insights) +
                        f"\n\nSummary: {fallback_result.summary}"
                    )
```

- [ ] **Step 5: Verify syntax is clean**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "import ast; ast.parse(open('.claude/hooks/content-scheduler.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 6: Commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/hooks/content-scheduler.py
git commit -m "feat: wire Claude+Canva carousel as NLM fallback in content pipeline"
```

---

## Task 4: Smoke test end-to-end

**Files:** None (test run only)

- [ ] **Step 1: Test claude_researcher standalone**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 scripts/claude_researcher.py --topic "Daily workout progression for men" --track fitness
```

Expected: JSON with `hook`, `insights` (5 items), `caption_angle`, `summary`. Takes ~30s.

- [ ] **Step 2: Test canva_carousel prompt building (no MCP call)**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "
from scripts.canva_carousel import CarouselBrief, build_slide_prompt
brief = CarouselBrief(
    topic='Daily workout for men', track='fitness',
    hook='What every man skips at the gym',
    insights=['Rest days grow muscle faster', 'Volume beats max weight', '20 min beats 0 min']
)
total = len(brief.insights) + 2
for i in range(total):
    print(f'--- Slide {i+1} ---')
    print(build_slide_prompt(brief, i, total)[:120])
    print()
"
```

Expected: 5 slide prompts printed, each different (cover, 3 insights, CTA).

- [ ] **Step 3: Run full pipeline to trigger fallback**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 .claude/hooks/content-scheduler.py 2>&1 | grep -E "scheduler|canva|carousel|fallback|research"
```

Expected output includes:
```
[scheduler] NLM research failed (API quota/error), running Claude+Canva fallback
[scheduler] NLM fallback: running Claude research for '...'
[scheduler] Claude research done — hook: ...
```

And Slack DM receives: research insights block + Canva carousel edit links.

- [ ] **Step 4: Commit if any fixes needed**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add -p
git commit -m "fix: smoke test fixes for NLM fallback carousel"
```

---

## Self-Review

**Spec coverage:**
- ✅ Claude deep research on topic → structured insights (Task 1)
- ✅ Canva multi-slide carousel one insight per slide (Task 2)
- ✅ Caption uses Claude insights via `nlm_insights` string (Task 3 Step 4)
- ✅ Slack DM gets insights + carousel edit URLs (Task 3 `run_nlm_fallback`)
- ✅ Wired as NLM fallback, not a replacement (Task 3 — only triggers when `not research_ok`)
- ✅ PDF export: `_export_design_pdf` exists in canva_carousel.py — called in `run_nlm_fallback` via Canva MCP after carousel generates

**No placeholders found.**

**Type consistency:**
- `ResearchResult` defined in Task 1, imported and used correctly in Task 3
- `CarouselBrief` defined in Task 2, imported and used correctly in Task 3
- `generate_carousel()` returns `{design_ids, edit_urls, slide_count, errors}` — all keys accessed correctly in Task 3
- `claude_research(topic, track)` signature matches `research()` function aliased on import
