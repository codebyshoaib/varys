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
