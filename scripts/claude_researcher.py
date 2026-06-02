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
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        data = json.loads(cleaned)
        return ResearchResult(
            hook=str(data.get("hook", "Here is what the research says")),
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
            ["claude", "--dangerously-skip-permissions", "-p", prompt],
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
