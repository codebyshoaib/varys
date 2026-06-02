#!/usr/bin/env python3
"""Tests for canva-designer.py"""
import json
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from canva_designer import CanvaDesigner, TEMPLATE_MAP, build_design_prompt


class TestTemplateMap(unittest.TestCase):
    def test_all_channel_format_combos_covered(self):
        expected = {
            ("linkedin", "card"),
            ("instagram", "post"),
            ("instagram", "story"),
            ("youtube", "thumbnail"),
        }
        for key in expected:
            self.assertIn(key, TEMPLATE_MAP, f"Missing template key: {key}")

    def test_template_map_has_required_fields(self):
        for key, val in TEMPLATE_MAP.items():
            self.assertIn("template_name", val)
            self.assertIn("width", val)
            self.assertIn("height", val)


class TestBuildDesignPrompt(unittest.TestCase):
    def test_prompt_includes_topic_and_copy(self):
        prompt = build_design_prompt(
            topic="Django REST tips",
            copy="5 tips every Django dev needs",
            channel="linkedin",
            fmt="card",
        )
        self.assertIn("Django REST tips", prompt)
        self.assertIn("5 tips every Django dev needs", prompt)
        self.assertIn("linkedin", prompt.lower())

    def test_prompt_includes_size(self):
        prompt = build_design_prompt("t", "c", "linkedin", "card")
        self.assertIn("1200", prompt)
        self.assertIn("627", prompt)


class TestCanvaDesigner(unittest.TestCase):
    def setUp(self):
        self.designer = CanvaDesigner(brand_kit_id="test-brand-kit")

    def test_result_has_required_keys(self):
        mock_result = {
            "design_url": "https://canva.com/design/abc",
            "export_url": "https://export.canva.com/abc.png",
            "canva_id": "abc123",
        }
        with patch.object(self.designer, "_call_mcp", return_value=mock_result):
            result = self.designer.create(
                topic="test", copy="test copy", channel="linkedin", fmt="card"
            )
        self.assertIn("design_url", result)
        self.assertIn("export_url", result)
        self.assertIn("canva_id", result)

    def test_missing_template_falls_back_gracefully(self):
        with patch.object(self.designer, "_call_mcp", return_value={
            "design_url": "https://canva.com/design/x",
            "export_url": "https://export.canva.com/x.png",
            "canva_id": "x1",
        }):
            result = self.designer.create("t", "c", "unknown_channel", "unknown_fmt")
        self.assertIn("design_url", result)
