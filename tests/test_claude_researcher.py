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
