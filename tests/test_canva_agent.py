#!/usr/bin/env python3
"""Tests for kamil-canva-agent.py eval logic."""
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "agents"))

from kamil_canva_agent import EvalScores, eval_passed, adjust_brief, pick_retry_hint


class TestEvalScores(unittest.TestCase):
    def test_all_pass(self):
        scores = EvalScores(brand=8, legibility=9, hierarchy=7)
        self.assertTrue(eval_passed(scores))

    def test_one_fail(self):
        scores = EvalScores(brand=8, legibility=6, hierarchy=9)
        self.assertFalse(eval_passed(scores))

    def test_boundary_pass(self):
        scores = EvalScores(brand=7, legibility=7, hierarchy=7)
        self.assertTrue(eval_passed(scores))

    def test_boundary_fail(self):
        scores = EvalScores(brand=7, legibility=6, hierarchy=7)
        self.assertFalse(eval_passed(scores))


class TestAdjustBrief(unittest.TestCase):
    def test_legibility_fail_adds_hint(self):
        scores = EvalScores(brand=8, legibility=5, hierarchy=8)
        hint = pick_retry_hint(scores)
        self.assertIn("legib", hint.lower())

    def test_brand_fail_adds_hint(self):
        scores = EvalScores(brand=4, legibility=8, hierarchy=8)
        hint = pick_retry_hint(scores)
        self.assertIn("brand", hint.lower())

    def test_hierarchy_fail_adds_hint(self):
        scores = EvalScores(brand=8, legibility=8, hierarchy=4)
        hint = pick_retry_hint(scores)
        self.assertIn("hierarch", hint.lower())

    def test_adjusted_brief_includes_hint(self):
        scores = EvalScores(brand=8, legibility=5, hierarchy=8)
        original = "Make a LinkedIn card about Django"
        adjusted = adjust_brief(original, scores)
        self.assertIn("Django", adjusted)
        self.assertGreater(len(adjusted), len(original))
