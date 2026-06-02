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


if __name__ == "__main__":
    unittest.main()
