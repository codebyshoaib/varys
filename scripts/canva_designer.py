#!/usr/bin/env python3
"""
canva-designer.py — Dumb Canva MCP executor.

Receives a brief, calls Canva MCP, returns asset URLs.
Called by kamil-canva-agent.py or directly from pipeline.

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

# Template registry — one entry per channel+format combo
TEMPLATE_MAP = {
    ("linkedin", "card"):      {"template_name": "kamil-linkedin-card",  "width": 1200, "height": 627},
    ("instagram", "post"):     {"template_name": "kamil-ig-post",         "width": 1080, "height": 1080},
    ("instagram", "story"):    {"template_name": "kamil-ig-story",        "width": 1080, "height": 1920},
    ("youtube",  "thumbnail"): {"template_name": "kamil-yt-thumbnail",    "width": 1280, "height": 720},
}

# All formats produced per pipeline run
ALL_FORMATS = [
    ("linkedin",   "card"),
    ("instagram",  "post"),
    ("instagram",  "story"),
    ("youtube",    "thumbnail"),
]


def build_design_prompt(topic: str, copy: str, channel: str, fmt: str) -> str:
    tmpl = TEMPLATE_MAP.get((channel, fmt), {})
    w = tmpl.get("width", 1080)
    h = tmpl.get("height", 1080)
    template_name = tmpl.get("template_name", "brand-kit-default")
    return (
        f"Create a {channel} {fmt} design ({w}x{h}px) using the template '{template_name}'. "
        f"Topic: {topic}. "
        f"Headline copy: {copy}. "
        f"Apply brand kit colors and fonts. "
        f"Ensure text is legible at thumbnail size. "
        f"Clear visual hierarchy with one focal point."
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
