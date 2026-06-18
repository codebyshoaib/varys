#!/usr/bin/env python3
"""
canva_infographic.py — Single-panel deep infographic via Canva MCP.

Produces ONE professional infographic in NotebookLM style:
  - Clear header with topic + emotional hook
  - 5–6 data/insight blocks with icons
  - Clean hierarchy, one dominant color per track
  - Portrait 1080x1350 (Instagram/LinkedIn-ready)

Used as the NLM fallback when quota is exhausted. The goal is:
  "If someone didn't know this came from Canva vs NotebookLM, they couldn't tell."

Usage:
  python3 scripts/canva_infographic.py \
    --topic "How I use parallel agents" \
    --track tech \
    --hook "6 hours of work in 45 minutes" \
    --insights "Parallel agents never share state" "Each agent owns one task" \
               "Fan-out then synthesize" "The bottleneck is always the slowest agent" \
               "Context window per agent, not shared" \
    --angle awe \
    --output /tmp/infographic.png

Outputs JSON: {"design_id": str, "edit_url": str, "export_url": str, "local_path": str, "error": str|None}
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BRAND_KIT_ID = "kAHLIxSiVa8"

# Track → visual identity (matches NLM's clean professional palette)
TRACK_STYLE = {
    "fitness": {
        "palette": "deep forest green (#1B4332) header, warm cream (#FEFCE8) background, "
                   "coral accent (#F97316), charcoal text (#1C1917)",
        "icon_set": "minimalist line icons: running figure, mountain peak, water drop, flame, clock, body silhouette",
        "mood": "energetic but grounded — like a well-designed training plan",
    },
    "tech": {
        "palette": "deep navy (#0F172A) header, pure white (#FFFFFF) background, "
                   "electric blue accent (#3B82F6), dark slate text (#1E293B)",
        "icon_set": "minimalist line icons: code brackets, lightning bolt, circuit node, arrow, gear, brain",
        "mood": "sharp and precise — like a well-annotated architecture diagram",
    },
    "vlog": {
        "palette": "warm charcoal (#292524) header, soft cream (#FDF8F0) background, "
                   "golden amber accent (#D97706), warm brown text (#292524)",
        "icon_set": "minimalist line icons: camera, map pin, sun, moon, heart, person walking",
        "mood": "warm and editorial — like a beautifully designed travel journal spread",
    },
    "painting": {
        "palette": "deep plum (#3B0764) header, off-white (#FAFAF9) background, "
                   "gold accent (#B45309), warm grey text (#292524)",
        "icon_set": "minimalist line icons: paint brush, palette, canvas, sun, eye, hand",
        "mood": "calm and artistic — like a studio art book",
    },
}

DEFAULT_STYLE = TRACK_STYLE["tech"]


def build_infographic_prompt(topic: str, track: str, hook: str,
                              insights: list[str], angle: str) -> str:
    style = TRACK_STYLE.get(track, DEFAULT_STYLE)
    insights_formatted = "\n".join(
        f"  Block {i+1}: \"{ins}\"" for i, ins in enumerate(insights[:6])
    )

    return f"""Design a single-panel professional infographic for Instagram/LinkedIn (1080x1350px portrait).

TOPIC: {topic}
EMOTIONAL ANGLE: {angle} — every visual choice should reinforce this feeling

CONTENT STRUCTURE (top to bottom):
1. HEADER BAND (top ~18% of canvas)
   - Dark background: {style['palette'].split(',')[0].strip()}
   - Large bold white text: "{topic}"
   - Smaller subtext below: "{hook}"
   - Clean, confident — like a magazine cover header

2. INSIGHT GRID (middle ~65% of canvas)
   - Background: {style['palette'].split('background,')[1].split(',')[0].strip()}
   - {len(insights[:6])} insight blocks arranged in a clean grid (2 columns or stacked)
   - Each block: small icon on the left + bold short text on the right
   - Use {style['icon_set']}
   - Generous white space between blocks — never cramped
   - Text: {style['palette'].split('text')[0].split(',')[-1].strip()} text
   - Accent color for icons and dividers: {style['palette'].split('accent')[0].split(',')[-1].strip()}

   BLOCKS:
{insights_formatted}

3. FOOTER BAND (bottom ~8% of canvas)
   - Same dark background as header
   - Small white text: "@shoaib"
   - Minimal — just the handle, nothing else

DESIGN RULES (non-negotiable):
- This must look like a NotebookLM infographic: clean, data-forward, professional
- NO decorative flourishes, NO gradient blobs, NO stock-photo backgrounds
- Typography hierarchy: topic title (largest) > insight text (medium) > handle (smallest)
- Every insight block must have exactly one icon + one line of bold text (max 10 words)
- Mood: {style['mood']}
- The viewer should be able to read every word in 8 seconds
- Total canvas: 1080x1350px, portrait orientation, full bleed

Brand kit ID: {BRAND_KIT_ID}
Return the design as a single image — not a carousel, not slides — ONE panel."""


def generate_infographic(topic: str, track: str, hook: str,
                          insights: list[str], angle: str = "awe",
                          output_path: str = None) -> dict:
    """Generate infographic via Canva MCP through a claude subprocess call."""
    prompt = build_infographic_prompt(topic, track, hook, insights, angle)

    mcp_prompt = f"""{prompt}

Use the Canva MCP tool to:
1. Call generate-design with the description above to create this infographic
2. Call export-design to get a PNG export URL
3. Return ONLY valid JSON in this exact format (no other text):
{{
  "design_id": "<canva design id>",
  "edit_url": "<canva edit URL>",
  "export_url": "<PNG export URL>",
  "error": null
}}

If any step fails, return:
{{"design_id": "", "edit_url": "", "export_url": "", "error": "<what failed>"}}"""

    try:
        r = subprocess.run(
            ["claude", "--dangerously-skip-permissions",
             "--model", "claude-sonnet-4-6",
             "--print", "-p", mcp_prompt],
            capture_output=True, text=True, timeout=180,
        )
        raw = r.stdout.strip()

        # Extract JSON from output
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(raw[start:end])
        else:
            return {"design_id": "", "edit_url": "", "export_url": "",
                    "local_path": "", "error": f"No JSON in output: {raw[:200]}"}

        # Download the export if we have a URL and output path
        local_path = ""
        if output_path and result.get("export_url"):
            try:
                req = urllib.request.Request(
                    result["export_url"],
                    headers={"User-Agent": "varys-content-pipeline/1.0"}
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    Path(output_path).write_bytes(resp.read())
                local_path = output_path
                print(f"[infographic] Downloaded to {output_path}")
            except Exception as e:
                print(f"[infographic] Download failed: {e}")

        result["local_path"] = local_path
        return result

    except subprocess.TimeoutExpired:
        return {"design_id": "", "edit_url": "", "export_url": "",
                "local_path": "", "error": "Claude subprocess timed out after 180s"}
    except Exception as e:
        return {"design_id": "", "edit_url": "", "export_url": "",
                "local_path": "", "error": str(e)}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--topic",    required=True)
    p.add_argument("--track",    default="tech", choices=["fitness", "tech", "vlog", "painting"])
    p.add_argument("--hook",     required=True, help="Short scroll-stopping subheader")
    p.add_argument("--insights", nargs="+", required=True, help="5-6 insight strings")
    p.add_argument("--angle",    default="awe", choices=["awe", "longing", "nostalgia", "belonging"])
    p.add_argument("--output",   default=None, help="Local path to save PNG")
    args = p.parse_args()

    result = generate_infographic(
        topic=args.topic,
        track=args.track,
        hook=args.hook,
        insights=args.insights,
        angle=args.angle,
        output_path=args.output,
    )
    print(json.dumps(result, indent=2))
