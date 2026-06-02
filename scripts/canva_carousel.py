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

Outputs JSON: {"design_ids": [...], "edit_urls": [...], "slide_count": N, "errors": [...]}
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
    Returns {"design_id": ..., "edit_url": ...}
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
        ["claude", "--dangerously-skip-permissions", "--print", "-p", "-"],
        input=instruction,
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
    """Export a Canva design as PDF. Returns download URL or empty string."""
    instruction = (
        f"Use the Canva MCP to export design {design_id} as a PDF. "
        f"Call mcp__claude_ai_Canva__export-design with design_id={design_id} "
        f"and format={{\"type\": \"pdf\", \"export_quality\": \"pro\"}}. "
        f"Return ONLY the download URL as plain text."
    )
    result = subprocess.run(
        ["claude", "--dangerously-skip-permissions", "--print", "-p", "-"],
        input=instruction,
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
