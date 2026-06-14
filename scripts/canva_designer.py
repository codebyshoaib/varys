#!/usr/bin/env python3
"""
canva-designer.py — Dumb Canva MCP executor.

Receives a brief, calls Canva MCP, returns asset URLs.
Called by varys-canva-agent.py or directly from pipeline.

Usage:
  python3 scripts/canva-designer.py --topic "Django tips" --copy "5 tips..." \
    --channel linkedin --format card --brand-kit-id <id>

Outputs JSON: {"linkedin_card": {"design_url": ..., "export_url": ..., "canva_id": ...}}
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import sys as _sys_dp
_DP_DIR = str(Path(__file__).parent)
if _DP_DIR not in _sys_dp.path:
    _sys_dp.path.insert(0, _DP_DIR)
from design_philosopher import create_philosophy

# Template registry — one entry per channel+format combo
TEMPLATE_MAP = {
    ("linkedin", "card"):      {"template_name": "varys-linkedin-card",  "width": 1200, "height": 627},
    ("instagram", "post"):     {"template_name": "varys-ig-post",         "width": 1080, "height": 1080},
    ("instagram", "story"):    {"template_name": "varys-ig-story",        "width": 1080, "height": 1920},
    ("youtube",  "thumbnail"): {"template_name": "varys-yt-thumbnail",    "width": 1280, "height": 720},
}

# All formats produced per pipeline run
ALL_FORMATS = [
    ("linkedin",   "card"),
    ("instagram",  "post"),
    ("instagram",  "story"),
    ("youtube",    "thumbnail"),
]


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


class CanvaDesigner:
    def __init__(self, brand_kit_id: str):
        self.brand_kit_id = brand_kit_id

    def _call_mcp(self, prompt: str, template_name: str, width: int, height: int) -> dict:
        """
        Calls Canva MCP via `claude -p` subprocess with a tool-use prompt.
        Returns dict with design_url, export_url, canva_id.
        """
        instruction = (
            f"Use the Canva MCP to create a design. "
            f"Template: {template_name}. Brand kit ID: {self.brand_kit_id}. "
            f"Size: {width}x{height}. Design brief: {prompt}. "
            f"Return ONLY valid JSON: "
            f'{{\"design_url\": \"...\", \"export_url\": \"...\", \"canva_id\": \"...\"}}'
        )
        result = subprocess.run(
            ["claude", "-p", instruction, "--output-format", "json"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude -p failed: {result.stderr[:200]}")
        # claude -p with --output-format json wraps in {"result": ...}
        outer = json.loads(result.stdout)
        raw = outer.get("result", outer)
        if isinstance(raw, str):
            raw = json.loads(raw)
        return raw

    def create(self, topic: str, copy: str, channel: str, fmt: str) -> dict:
        """Create one design. Returns {design_url, export_url, canva_id}."""
        tmpl = TEMPLATE_MAP.get((channel, fmt), {
            "template_name": "brand-kit-default",
            "width": 1080,
            "height": 1080,
        })
        prompt = build_design_prompt(topic, copy, channel, fmt)
        return self._call_mcp(prompt, tmpl["template_name"], tmpl["width"], tmpl["height"])

    def create_all(self, topic: str, copy: str) -> dict:
        """Create all channel+format designs. Returns {channel_format: {urls}}."""
        import concurrent.futures
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futures = {
                ex.submit(self.create, topic, copy, ch, fmt): f"{ch}_{fmt}"
                for ch, fmt in ALL_FORMATS
            }
            for future in concurrent.futures.as_completed(futures):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception as e:
                    results[key] = {"error": str(e)}
        return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--copy", required=True)
    parser.add_argument("--channel", default="all")
    parser.add_argument("--format", dest="fmt", default="all")
    parser.add_argument("--brand-kit-id", required=True)
    args = parser.parse_args()

    designer = CanvaDesigner(brand_kit_id=args.brand_kit_id)

    if args.channel == "all":
        results = designer.create_all(args.topic, args.copy)
    else:
        results = {f"{args.channel}_{args.fmt}": designer.create(args.topic, args.copy, args.channel, args.fmt)}

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
