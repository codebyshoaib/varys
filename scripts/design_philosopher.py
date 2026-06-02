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
        f"You are a world-class art director creating a design philosophy for a {design_type} social post about '{topic}' for a {track} content creator. "
        f"Create an original aesthetic movement — not a template, not a style guide — a genuine philosophical stance. "
        f"Name the movement (1-2 evocative words). Write a 4-paragraph manifesto covering: "
        f"(1) the core visual philosophy and what it rejects, "
        f"(2) how space form and color operate in this movement, "
        f"(3) the emotional register and cultural references it draws from, "
        f"(4) what expert craftsmanship looks like here — meticulously labored painstaking master-level. "
        f"Then write a canvas_directive: 3-4 sentences of precise visual instruction for expressing this philosophy in a single {design_type} image — what visual elements dominate what is absent how text behaves as a visual element. "
        f"The philosophy must emphasize: 90 percent visual 10 percent text. No generic AI aesthetics. "
        f"Return ONLY valid JSON with keys: movement_name (string), manifesto (string), canvas_directive (string). "
        f"The topic '{topic}' is the soul embedded invisibly in the work — not announced just felt."
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
