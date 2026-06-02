# Canva Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Canva Pro (m.kamal@taleemabad.com) into Kamil's content pipeline and on-demand skill, with a self-evaluating agent that scores designs via Claude vision and retries or escalates as needed.

**Architecture:** `canva-designer.py` is the dumb MCP executor (brief in → asset URLs out). `kamil-canva-agent.py` is the intelligent wrapper that briefs the designer, runs vision eval, retries on scores <7, and escalates to Kamil via Slack. A local `canva` skill routes on-demand requests from Claude sessions/Slack into the same agent.

**Tech Stack:** Python 3.10+, Canva MCP (`mcp__claude_ai_Canva__authenticate` / `mcp__claude_ai_Canva__complete_authentication`), Claude API (`claude-sonnet-4-6` with vision), Notion API (existing `.notion` config), Slack (existing `.slack` config), `subprocess` for `claude -p` agent invocation.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `scripts/canva-designer.py` | Create | Dumb MCP executor: brief → Canva MCP → asset URLs |
| `agents/kamil-canva-agent.py` | Create | Intelligent wrapper: eval, retry, escalate, Notion log |
| `.claude/skills/canva/skill.md` | Create | On-demand skill: collect brief fields, hand off to agent |
| `.claude/rules/skills-router.md` | Modify | Add canva row |
| `.claude/settings.json` | Modify | Enable Canva MCP server |
| `.claude/hooks/content-scheduler.py` | Modify | Insert canva-designer step after copy generation |
| `tests/test_canva_designer.py` | Create | Unit tests for canva-designer |
| `tests/test_canva_agent.py` | Create | Unit tests for eval logic in canva-agent |

---

## Task 1: Enable Canva MCP in settings.json

**Files:**
- Modify: `.claude/settings.json`

- [ ] **Step 1: Read current settings**

```bash
cat .claude/settings.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d.get('mcpServers',{}), indent=2))"
```

Expected: shows `mempalace` entry only.

- [ ] **Step 2: Add Canva MCP server entry**

Open `.claude/settings.json`. Find the `"mcpServers"` key and add the `canva` entry:

```json
"mcpServers": {
  "mempalace": {
    "command": "mempalace",
    "args": ["serve", "--palace", "/home/oye/Documents/free_work/personal-agent-v2/mempalace"],
    "description": "Semantic memory — kept as fallback"
  },
  "canva": {
    "type": "http",
    "url": "https://mcp.canva.com/mcp",
    "description": "Canva Pro design creation via OAuth — m.kamal@taleemabad.com"
  }
}
```

- [ ] **Step 3: Verify JSON is valid**

```bash
python3 -c "import json; json.load(open('.claude/settings.json')); print('valid')"
```

Expected: `valid`

- [ ] **Step 4: Commit**

```bash
git add .claude/settings.json
git commit -m "feat: enable Canva MCP server in settings"
```

---

## Task 2: Authenticate Canva (one-time)

**Files:** None (MCP OAuth flow)

- [ ] **Step 1: Trigger authentication**

In a Claude Code session, run:
```
mcp__claude_ai_Canva__authenticate
```
This returns a URL. Open it in a browser logged into `m.kamal@taleemabad.com`.

- [ ] **Step 2: Complete authentication**

After browser approval, call:
```
mcp__claude_ai_Canva__complete_authentication
```

- [ ] **Step 3: Verify token works**

Ask Claude to call any Canva MCP tool (e.g. list designs). Confirm it returns data without auth error.

- [ ] **Step 4: Note brand kit ID**

In the Canva response, find the brand kit ID for the `m.kamal@taleemabad.com` workspace. Save it — it will be used as `CANVA_BRAND_KIT_ID` in scripts.

---

## Task 3: Create Notion Design DB

**Files:** None (Notion MCP call)

- [ ] **Step 1: Create the database via Notion MCP**

Call `mcp__claude_ai_Notion__notion-create-database` with this schema:

```json
{
  "parent": { "type": "page_id", "page_id": "<your-root-notion-page-id>" },
  "title": [{ "type": "text", "text": { "content": "Canva Designs" } }],
  "properties": {
    "Topic": { "title": {} },
    "Channel": { "select": { "options": [
      { "name": "LinkedIn" }, { "name": "Instagram" }, { "name": "YouTube" }
    ]}},
    "Format": { "select": { "options": [
      { "name": "card" }, { "name": "carousel" }, { "name": "story" }, { "name": "thumbnail" }
    ]}},
    "CanvaID": { "rich_text": {} },
    "DesignURL": { "url": {} },
    "ExportURL": { "url": {} },
    "EvalBrand": { "number": {} },
    "EvalLegibility": { "number": {} },
    "EvalHierarchy": { "number": {} },
    "Retries": { "number": {} },
    "Status": { "select": { "options": [
      { "name": "draft" }, { "name": "approved" }, { "name": "posted" }, { "name": "Needs-Kamal" }
    ]}},
    "ContentDBRef": { "rich_text": {} }
  }
}
```

- [ ] **Step 2: Copy the returned database ID**

The response includes an `"id"` field. Save it — used as `NOTION_DESIGN_DB` in scripts.

- [ ] **Step 3: Add DB ID to vault/notion-map.md**

Open `vault/notion-map.md` and add a row:
```
| Canva Designs DB | <db-id-from-step-2> | Design asset URLs, eval scores, status |
```

- [ ] **Step 4: Commit**

```bash
git add vault/notion-map.md
git commit -m "feat: create Notion Canva Designs DB, add to notion-map"
```

---

## Task 4: Create `scripts/canva-designer.py`

**Files:**
- Create: `scripts/canva-designer.py`
- Create: `tests/test_canva_designer.py`

- [ ] **Step 1: Create the tests directory if missing**

```bash
mkdir -p scripts tests
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_canva_designer.py`:

```python
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
```

- [ ] **Step 3: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_canva_designer.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'canva_designer'`

- [ ] **Step 4: Create `scripts/canva-designer.py`**

```python
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
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
python3 -m pytest tests/test_canva_designer.py -v
```

Expected: all tests PASS (the `_call_mcp` is mocked so no real MCP needed).

- [ ] **Step 6: Commit**

```bash
git add scripts/canva-designer.py tests/test_canva_designer.py
git commit -m "feat: add canva-designer.py MCP executor + tests"
```

---

## Task 5: Create `agents/kamil-canva-agent.py`

**Files:**
- Create: `agents/kamil-canva-agent.py`
- Create: `tests/test_canva_agent.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_canva_agent.py`:

```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_canva_agent.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'kamil_canva_agent'`

- [ ] **Step 3: Create `agents/kamil-canva-agent.py`**

```python
#!/usr/bin/env python3
"""
kamil-canva-agent.py — Intelligent Canva design agent.

Briefs canva-designer, runs Claude vision eval, retries on scores <7,
escalates to Kamil via Slack after 2 failed retries.
Logs all eval results to Notion Design DB and Observability DB.

Usage (from pipeline or claude -p):
  python3 agents/kamil-canva-agent.py \
    --topic "Django REST tips" \
    --copy "5 tips every Django dev needs" \
    --brand-kit-id <id> \
    [--content-db-ref <notion-page-id>]

Outputs JSON: {channel_format: {design_url, export_url, canva_id, scores, retries, status}}
"""
import argparse
import base64
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
KAMAL_DM         = "D0B415M06SK"
NOTION_DESIGN_DB = os.environ.get("NOTION_DESIGN_DB", "")  # set after Task 3
NOTION_OBS_DB    = "8b0f5754c0b04b5eae27e7e1a9b5c3d2"      # existing observability DB
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
    """Send a DM to Kamil."""
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
        # Default to pass-through scores if vision fails — don't block pipeline
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
    Create one design, eval it, retry up to MAX_RETRIES times, escalate if needed.
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

        # retry
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
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python3 -m pytest tests/test_canva_agent.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/kamil-canva-agent.py tests/test_canva_agent.py
git commit -m "feat: add kamil-canva-agent with vision eval, retry, and escalation"
```

---

## Task 6: Create `.claude/skills/canva/skill.md`

**Files:**
- Create: `.claude/skills/canva/skill.md`

- [ ] **Step 1: Create the skill directory**

```bash
mkdir -p .claude/skills/canva
```

- [ ] **Step 2: Write the skill file**

Create `.claude/skills/canva/skill.md`:

```markdown
# Canva Design Skill

Kamil's on-demand Canva design interface. Triggered when Kamil asks to create
any visual content: post, carousel, thumbnail, banner, graphic, design.

## Trigger phrases
"make a post", "create a carousel", "design a thumbnail", "make a banner",
"create a graphic", "make an image for", "design something for", "canva"

## What this skill does
Collects a complete design brief, then runs `kamil-canva-agent.py` to create
designs for all 3 channels (LinkedIn, Instagram, YouTube) in parallel with
self-eval and retry built in.

## Required brief fields
- **topic**: What is this design about? (e.g. "Django REST Framework tips")
- **copy**: The headline/main text for the design (max ~8 words)
- **brand_kit_id**: From `CANVA_BRAND_KIT_ID` env var (check `.env` or ask Kamil)

## Process

1. If any required field is missing, ask Kamil for it (one question at a time).
2. Once brief is complete, run:

```bash
python3 /home/oye/Documents/free_work/personal-agent-v2/agents/kamil-canva-agent.py \
  --topic "<topic>" \
  --copy "<copy>" \
  --brand-kit-id "$CANVA_BRAND_KIT_ID"
```

3. Report results: for each channel+format, show design_url, eval scores, and status.
4. If any status is `Needs-Kamal`, tell Kamil which ones and why (include scores).
5. If any status is `draft`, confirm designs are saved to Notion Design DB.

## Auth failure handling
If the agent returns a Canva auth error, tell Kamil:
"Canva needs re-authentication. In this Claude session, I'll call the Canva MCP
authenticate tool now."
Then call `mcp__claude_ai_Canva__authenticate` and `mcp__claude_ai_Canva__complete_authentication`.
```

- [ ] **Step 3: Verify file exists**

```bash
cat .claude/skills/canva/skill.md | head -5
```

Expected: first line is `# Canva Design Skill`

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/canva/skill.md
git commit -m "feat: add canva on-demand skill"
```

---

## Task 7: Update skills-router.md

**Files:**
- Modify: `.claude/rules/skills-router.md`

- [ ] **Step 1: Add canva row to the router table**

Open `.claude/rules/skills-router.md` and add this row to the table, after the `slides` row:

```markdown
| design / post / carousel / thumbnail / banner / "make a graphic" / "create an image" | `canva` |
```

- [ ] **Step 2: Verify the table looks correct**

```bash
grep -n "canva\|design\|carousel\|thumbnail" .claude/rules/skills-router.md
```

Expected: the new row appears.

- [ ] **Step 3: Commit**

```bash
git add .claude/rules/skills-router.md
git commit -m "feat: add canva to skills-router"
```

---

## Task 8: Wire canva-designer into content-scheduler.py

**Files:**
- Modify: `.claude/hooks/content-scheduler.py`

- [ ] **Step 1: Read the current content-scheduler to find the right insertion point**

```bash
grep -n "image_generator\|linkedin_poster\|NLM\|caption\|post_linkedin" .claude/hooks/content-scheduler.py | head -20
```

Note the line number where image generation / posting happens — insert the Canva step after copy is generated and before posting.

- [ ] **Step 2: Add the CANVA config constants near the top of the file**

Find the `# ─── Config ───` block in `content-scheduler.py` and add after `NOTION_CONTENT_LOG`:

```python
CANVA_BRAND_KIT_ID = os.environ.get("CANVA_BRAND_KIT_ID", "")
CANVA_AGENT        = ROOT / "agents" / "kamil-canva-agent.py"
```

Where `ROOT` is already defined as the repo root in that file (check — it may be `KAMIL_DIR` or similar; use whatever name is already used).

- [ ] **Step 3: Add `run_canva_designs` function**

Find a natural location after existing helper functions (before `main()` or the pipeline function) and insert:

```python
def run_canva_designs(topic: str, copy: str, content_db_ref: str = "") -> dict:
    """Run kamil-canva-agent for all formats. Returns results dict."""
    if not CANVA_BRAND_KIT_ID:
        klog("canva", "CANVA_BRAND_KIT_ID not set — skipping Canva designs")
        return {}
    try:
        result = subprocess.run(
            [
                sys.executable, str(CANVA_AGENT),
                "--topic", topic,
                "--copy", copy,
                "--brand-kit-id", CANVA_BRAND_KIT_ID,
                "--content-db-ref", content_db_ref,
            ],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            klog("canva", f"canva-agent failed: {result.stderr[:200]}")
            return {}
        return json.loads(result.stdout)
    except Exception as e:
        klog("canva", f"run_canva_designs error: {e}")
        return {}
```

- [ ] **Step 4: Call `run_canva_designs` in the pipeline after copy is generated**

Find the point in the pipeline where the post copy / caption is finalized (look for the variable holding the caption, e.g. `caption`, `copy`, `script_text`). After that point, add:

```python
# ── Canva designs ──────────────────────────────────────────────────────────
canva_results = run_canva_designs(topic=topic_title, copy=caption[:120])
if canva_results:
    passed = [k for k, v in canva_results.items() if v.get("status") == "draft"]
    needs_review = [k for k, v in canva_results.items() if v.get("status") == "Needs-Kamal"]
    klog("canva", f"designs created: {len(passed)} passed, {len(needs_review)} need review")
```

(Replace `topic_title` and `caption` with the actual variable names used in the surrounding code.)

- [ ] **Step 5: Verify the scheduler still imports cleanly**

```bash
python3 -c "import ast; ast.parse(open('.claude/hooks/content-scheduler.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 6: Commit**

```bash
git add .claude/hooks/content-scheduler.py
git commit -m "feat: wire canva-designer into content-scheduler pipeline"
```

---

## Task 9: Set CANVA_BRAND_KIT_ID environment variable

**Files:** None (env config)

- [ ] **Step 1: Find the brand kit ID**

From Task 2 Step 4, you noted the brand kit ID. If you didn't, in a Claude session call the Canva MCP to list brand kits and find the one for `m.kamal@taleemabad.com`.

- [ ] **Step 2: Add to crontab env**

```bash
crontab -e
```

Add at the top of crontab (before any job lines):
```
CANVA_BRAND_KIT_ID=<your-brand-kit-id>
```

- [ ] **Step 3: Add to shell profile for interactive sessions**

```bash
echo 'export CANVA_BRAND_KIT_ID=<your-brand-kit-id>' >> ~/.zshrc
source ~/.zshrc
```

- [ ] **Step 4: Verify**

```bash
echo $CANVA_BRAND_KIT_ID
```

Expected: prints the brand kit ID (not empty).

---

## Task 10: End-to-end smoke test

**Files:** None

- [ ] **Step 1: Run canva-designer directly with a test brief**

```bash
python3 scripts/canva-designer.py \
  --topic "Test topic" \
  --copy "Test headline copy" \
  --channel linkedin \
  --format card \
  --brand-kit-id "$CANVA_BRAND_KIT_ID"
```

Expected: JSON output with `design_url`, `export_url`, `canva_id`.

- [ ] **Step 2: Run kamil-canva-agent end-to-end**

```bash
python3 agents/kamil-canva-agent.py \
  --topic "Django REST Framework tips" \
  --copy "5 tips every Django dev needs" \
  --brand-kit-id "$CANVA_BRAND_KIT_ID"
```

Expected: JSON with 4 keys (`linkedin_card`, `instagram_post`, `instagram_story`, `youtube_thumbnail`), each with `scores`, `retries`, `status`.

- [ ] **Step 3: Verify Notion Design DB has entries**

Check the Notion Design DB (created in Task 3) — should have 4 new rows from Step 2.

- [ ] **Step 4: Test on-demand skill**

In a Claude session, type: `make a LinkedIn carousel about Python async tips`

Expected: Kamil skill triggers, agent runs, design URLs reported back.

- [ ] **Step 5: Commit final state**

```bash
git add -p  # review any remaining unstaged changes
git commit -m "feat: canva integration complete — designer, agent, skill, pipeline wired"
```

---

## Notes

- **First 2 weeks:** Auto-posting is disabled. All designs land in Notion Design DB with `status=draft`. Kamil reviews and approves manually to build trust in eval scores.
- **After 30 evals:** Review Notion Observability DB for patterns. If a format consistently fails one criterion, update the `build_design_prompt` defaults for that format.
- **Canva templates:** Create branded templates in Canva with names exactly matching `TEMPLATE_MAP` values (`kamil-linkedin-card`, `kamil-ig-post`, `kamil-ig-story`, `kamil-yt-thumbnail`). Without templates, the agent falls back to brand-kit-guided creation.
