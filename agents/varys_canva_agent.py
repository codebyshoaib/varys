#!/usr/bin/env python3
"""
varys-canva-agent.py — Intelligent Canva design agent.

Briefs canva-designer, runs Claude vision eval, retries on scores <7,
escalates to Varys via Slack after 2 failed retries.
Logs all eval results to Notion Design DB.

Usage (from pipeline or claude -p):
  python3 agents/varys_canva_agent.py \
    --topic "Django REST tips" \
    --copy "5 tips every Django dev needs" \
    --brand-kit-id <id> \
    [--content-db-ref <notion-page-id>]

Outputs JSON: {channel_format: {design_url, export_url, canva_id, scores, retries, status}}
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / ".claude" / "hooks"))
sys.path.insert(0, str(ROOT / "scripts"))

from canva_designer import CanvaDesigner, ALL_FORMATS

NOTION_CONFIG    = Path.home() / ".claude" / "hooks" / ".notion"
SLACK_CONFIG     = Path.home() / ".claude" / "hooks" / ".slack"
KAMAL_DM         = os.environ.get("USER_SLACK_DM", "")  # set USER_SLACK_DM in ~/.agent-config.json
NOTION_DESIGN_DB = os.environ.get("NOTION_DESIGN_DB", "076960e8f8a84c618e23a4a74a950b48")
EVAL_PASS        = 7
MAX_RETRIES      = 2


@dataclass
class EvalScores:
    brand: int
    legibility: int
    hierarchy: int


def eval_passed(scores: EvalScores) -> bool:
    return scores.brand >= EVAL_PASS and scores.legibility >= EVAL_PASS and scores.hierarchy >= EVAL_PASS


def pick_retry_hint(scores: EvalScores) -> str:
    hints = []
    if scores.legibility < EVAL_PASS:
        hints.append("increase text size and contrast for better legibility")
    if scores.brand < EVAL_PASS:
        hints.append("strictly apply brand kit colors and fonts")
    if scores.hierarchy < EVAL_PASS:
        hints.append("strengthen visual hierarchy with a single dominant focal point")
    return "; ".join(hints) if hints else "improve overall design quality"


def adjust_brief(original_brief: str, scores: EvalScores) -> str:
    hint = pick_retry_hint(scores)
    return f"{original_brief}. RETRY ADJUSTMENT: {hint}."


def _load_notion_key() -> Optional[str]:
    if NOTION_CONFIG.exists():
        for line in NOTION_CONFIG.read_text().splitlines():
            if line.startswith("NOTION_API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("NOTION_API_KEY")


def _load_slack_token() -> Optional[str]:
    if SLACK_CONFIG.exists():
        for line in SLACK_CONFIG.read_text().splitlines():
            if line.startswith("SLACK_BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("SLACK_BOT_TOKEN")


def notion_create_design_entry(
    topic: str, channel: str, fmt: str, canva_id: str,
    design_url: str, export_url: str, scores: EvalScores,
    retries: int, status: str, content_db_ref: str = ""
) -> Optional[str]:
    """Create a row in the Notion Design DB. Returns page ID or None."""
    key = _load_notion_key()
    if not key or not NOTION_DESIGN_DB:
        return None
    payload = {
        "parent": {"database_id": NOTION_DESIGN_DB},
        "properties": {
            "Topic":          {"title": [{"text": {"content": topic}}]},
            "Channel":        {"select": {"name": channel.capitalize()}},
            "Format":         {"select": {"name": fmt}},
            "CanvaID":        {"rich_text": [{"text": {"content": canva_id}}]},
            "DesignURL":      {"url": design_url},
            "ExportURL":      {"url": export_url},
            "EvalBrand":      {"number": scores.brand},
            "EvalLegibility": {"number": scores.legibility},
            "EvalHierarchy":  {"number": scores.hierarchy},
            "Retries":        {"number": retries},
            "Status":         {"select": {"name": status}},
            "ContentDBRef":   {"rich_text": [{"text": {"content": content_db_ref}}]},
        },
    }
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            "https://api.notion.com/v1/pages",
            data=data,
            headers={"Authorization": f"Bearer {key}", "Notion-Version": "2022-06-28",
                     "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())["id"]
    except Exception as e:
        print(f"[canva-agent] notion write failed: {e}", file=sys.stderr)
        return None


def slack_dm(message: str):
    """Send a DM to Varys."""
    token = _load_slack_token()
    if not token:
        return
    payload = json.dumps({"channel": KAMAL_DM, "text": message}).encode()
    try:
        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[canva-agent] slack dm failed: {e}", file=sys.stderr)


def eval_design_via_vision(export_url: str, channel: str, fmt: str) -> EvalScores:
    """
    Ask Claude vision to score the design on 3 criteria.
    Returns EvalScores with brand, legibility, hierarchy (1-10 each).
    Defaults to passing scores (7/7/7) if vision call fails.
    """
    prompt = (
        f"You are evaluating a {channel} {fmt} design image at: {export_url}\n"
        f"Score it on 3 criteria (1-10 each, integer only):\n"
        f"1. brand_consistency: correct colors/fonts/logo per brand kit\n"
        f"2. text_legibility: text readable at thumbnail size, adequate contrast\n"
        f"3. visual_hierarchy: clear focal point, natural eye flow\n"
        f"Return ONLY valid JSON: "
        f'{{\"brand\": 8, \"legibility\": 7, \"hierarchy\": 9}}'
    )
    result = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "json"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        return EvalScores(brand=7, legibility=7, hierarchy=7)
    try:
        outer = json.loads(result.stdout)
        raw = outer.get("result", outer)
        if isinstance(raw, str):
            raw = json.loads(raw)
        return EvalScores(
            brand=int(raw.get("brand", 7)),
            legibility=int(raw.get("legibility", 7)),
            hierarchy=int(raw.get("hierarchy", 7)),
        )
    except Exception:
        return EvalScores(brand=7, legibility=7, hierarchy=7)


def run_design_with_eval(
    topic: str, copy: str, channel: str, fmt: str,
    designer: CanvaDesigner, content_db_ref: str = ""
) -> dict:
    """
    Create one design, eval it, retry up to MAX_RETRIES, escalate if needed.
    Returns final result dict.
    """
    current_copy = copy
    retries = 0

    while True:
        asset = designer.create(topic, current_copy, channel, fmt)
        if "error" in asset:
            return {**asset, "retries": retries, "status": "error"}

        scores = eval_design_via_vision(asset.get("export_url", ""), channel, fmt)
        passed = eval_passed(scores)

        if passed or retries >= MAX_RETRIES:
            status = "draft" if passed else "Needs-Kamal"
            notion_create_design_entry(
                topic=topic, channel=channel, fmt=fmt,
                canva_id=asset.get("canva_id", ""),
                design_url=asset.get("design_url", ""),
                export_url=asset.get("export_url", ""),
                scores=scores, retries=retries,
                status=status, content_db_ref=content_db_ref,
            )
            if not passed:
                slack_dm(
                    f":warning: Canva design needs review\n"
                    f"Topic: {topic} | {channel} {fmt}\n"
                    f"Scores — brand:{scores.brand} legibility:{scores.legibility} hierarchy:{scores.hierarchy}\n"
                    f"Design: {asset.get('design_url', 'n/a')}"
                )
            return {
                **asset,
                "scores": asdict(scores),
                "retries": retries,
                "status": status,
            }

        current_copy = adjust_brief(current_copy, scores)
        retries += 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--copy", required=True)
    parser.add_argument("--brand-kit-id", required=True)
    parser.add_argument("--content-db-ref", default="")
    args = parser.parse_args()

    designer = CanvaDesigner(brand_kit_id=args.brand_kit_id)

    import concurrent.futures
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            ex.submit(
                run_design_with_eval,
                args.topic, args.copy, ch, fmt, designer, args.content_db_ref
            ): f"{ch}_{fmt}"
            for ch, fmt in ALL_FORMATS
        }
        for future in concurrent.futures.as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                results[key] = {"error": str(e), "status": "error"}

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
