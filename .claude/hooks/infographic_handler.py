#!/usr/bin/env python3
"""
infographic_handler.py — NLM-sourced infographic generator for Kamil.

Flow:
  extract_topic() → resolve NLM notebook → query for key points
  → image_generator.py --type info → upload_file_to_slack()
  → honest fallback on any step failure + log_capability_gap()
"""

import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_log import klog, klog_error

KAMIL_DIR = Path(__file__).parent.parent.parent
IMAGE_GEN = Path(__file__).parent / "image_generator.py"
sys.path.insert(0, str(IMAGE_GEN.parent))

_TOPIC_PATTERNS = [
    r"infographic\s+(?:about|on|for|of)\s+(.+)",
    r"(?:create|make|generate|build)\s+(?:an?\s+)?infographic\s+(?:about|on|for|of)?\s*(.+)",
    r"(?:create|make|generate|build)\s+(?:an?\s+)?image\s+(?:about|on|for|of)\s+(.+)",
    r"image\s+(?:about|on|for|of)\s+(.+)",
    r"visual\s+(?:for|about|on)\s+(.+)",
]

_FITNESS_KEYWORDS = {
    "fitness", "workout", "exercise", "training", "pull", "push", "swim",
    "cycle", "cycling", "calisthenics", "running", "gym", "muscle",
    "strength", "cardio", "hiit", "yoga", "sport", "health", "nutrition",
    "diet", "weight", "body", "stretching", "flexibility", "pullup",
}

_SLACK_CFG = Path.home() / ".claude" / "hooks" / ".slack"


def _load_bot_token() -> str:
    for key in ("SLACK_BOT_TOKEN", "BOT_TOKEN"):
        val = os.environ.get(key)
        if val:
            return val
    if _SLACK_CFG.exists():
        for line in _SLACK_CFG.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() in ("BOT_TOKEN", "SLACK_BOT_TOKEN"):
                    return v.strip()
    return ""


def extract_topic(text: str) -> str:
    """Extract the infographic topic from a natural language request."""
    clean = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    for pattern in _TOPIC_PATTERNS:
        m = re.search(pattern, clean, re.IGNORECASE)
        if m:
            topic = m.group(1).strip().rstrip(".,!?")
            topic = re.sub(r"\s+(please|now|quickly|for me)$", "", topic, flags=re.IGNORECASE)
            return topic
    fallback = re.sub(
        r"^.*?(infographic|image|visual|picture)\s*", "", clean, flags=re.IGNORECASE
    ).strip()
    return fallback or clean[:60]


def detect_palette(topic: str) -> str:
    """Return 'fitness' or 'tech' based on topic keywords."""
    words = set(topic.lower().split())
    if words & _FITNESS_KEYWORDS:
        return "fitness"
    return "tech"


def parse_nlm_points(raw: str) -> list[str]:
    """Parse NLM query output into a list of clean point strings (5-7 items)."""
    numbered = re.findall(r"^\s*\d+[.)]\s+(.+)", raw, re.MULTILINE)
    if len(numbered) >= 3:
        return [p.strip() for p in numbered[:7]]

    bulleted = re.findall(r"^\s*[-•*]\s+(.+)", raw, re.MULTILINE)
    if len(bulleted) >= 3:
        return [p.strip() for p in bulleted[:7]]

    sentences = re.split(r"(?<=[.!?])\s+", raw.strip())
    points = [s.strip() for s in sentences if len(s.strip()) > 15][:7]
    return points if points else [raw.strip()[:100]]


def _log_gap(gap_type: str, request_text: str, failed_step: str, fallback: str) -> None:
    try:
        from kamil_harness_db import get_db, log_capability_gap
        db = get_db()
        log_capability_gap(
            db,
            gap_type=gap_type,
            request_text=request_text[:300],
            failed_step=failed_step,
            fallback_used=fallback,
        )
    except Exception as e:
        klog_error("infographic_log_gap_fail", component="infographic_handler", error=str(e))


def _post_text(web, channel: str, thread_ts: str, text: str) -> None:
    web.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)


def handle(
    text: str,
    channel: str,
    thread_ts: str,
    web,
    bot_token: str = None,
    sender_id: str = None,
) -> None:
    """Main entry point. Called from kamil-slack-listener when is_visual_request() is True."""
    if not bot_token:
        bot_token = _load_bot_token()

    topic = extract_topic(text)
    if not topic:
        _post_text(web, channel, thread_ts,
                   "What topic should the infographic cover? 🤖 Kamil")
        return

    _post_text(web, channel, thread_ts,
               f"🖼️ Generating infographic: *{topic}*... (1–2 min)\n🤖 Kamil")

    # Step 1: Resolve NLM notebook
    try:
        from notebooklm_handler import (
            registry_search, run_nlm, create_notebook, deep_research, upload_file_to_slack,
        )
    except ImportError as e:
        klog_error("infographic_import_fail", component="infographic_handler", error=str(e))
        _log_gap("inline_image_arbitrary", text, "import_notebooklm", "none")
        _post_text(web, channel, thread_ts,
                   "⚠️ NotebookLM module not available. Can't generate infographic right now.\n🤖 Kamil")
        return

    keywords = topic.lower().split()
    hits = registry_search(keywords)
    nb_id = hits[0]["id"] if hits else None

    if not nb_id:
        nb_id = create_notebook(topic, bot_token)
        if nb_id:
            deep_research(topic, bot_token, notebook_id=nb_id)
        else:
            _log_gap("inline_image_arbitrary", text, "nlm_notebook_create", "text_summary")
            _post_text(web, channel, thread_ts,
                       f"⚠️ NotebookLM isn't responding right now. "
                       f"Can't create a notebook for *{topic}*.\n"
                       f"Try `nlm research {topic}` later, or I can give you a text summary. Which?\n🤖 Kamil")
            return

    # Step 2: Query for structured key points
    query = f"List exactly 7 key facts about {topic}, one per line, starting each with a number."
    ok, raw = run_nlm(["notebook", "query", nb_id, query, "--json", "--profile", "default"],
                      timeout=120)

    if not ok or not raw.strip():
        _log_gap("inline_image_arbitrary", text, "nlm_query", "text_summary")
        _post_text(web, channel, thread_ts,
                   f"⚠️ Got the notebook but couldn't extract points for *{topic}*.\n"
                   f"Try: `nlm ask {topic} \"{query}\"`\n🤖 Kamil")
        return

    import json as _json
    try:
        data = _json.loads(raw)
        answer_raw = data.get("value", {}).get("answer", raw)
    except Exception:
        answer_raw = raw

    points = parse_nlm_points(answer_raw)
    if len(points) < 3:
        _log_gap("inline_image_arbitrary", text, "nlm_parse", "text_summary")
        _post_text(web, channel, thread_ts,
                   f"⚠️ Couldn't extract enough points from the research on *{topic}* "
                   f"(got {len(points)}).\n"
                   f"Here's the raw research:\n```{answer_raw[:600]}```\n🤖 Kamil")
        return

    # Step 3: Render PNG via direct import (avoids CLI separator issues)
    palette  = detect_palette(topic)
    ts_stamp = str(int(time.time()))
    outfile  = f"/tmp/infographic-{ts_stamp}.png"
    palette_dict = None

    try:
        from image_generator import make_info, PALETTES
        palette_dict = PALETTES.get(palette, PALETTES["tech"])
        img = make_info(
            title=topic[:40],
            points=points[:7],
            handle="@oykamal",
            palette=palette_dict,
        )
        img.save(outfile, "PNG")
        if not Path(outfile).exists():
            raise RuntimeError("save produced no file")
    except Exception as e:
        _log_gap("inline_image_arbitrary", text, "image_render", "text_points")
        klog_error("infographic_render_fail", component="infographic_handler", error=str(e))
        lines = [f"🖼️ *{topic}* — research points (image render failed)\n"]
        for i, p in enumerate(points, 1):
            lines.append(f"{i}. {p}")
        lines.append("\n_Pillow or font missing — install with `pip install Pillow`_\n🤖 Kamil")
        _post_text(web, channel, thread_ts, "\n".join(lines))
        return

    # Step 4: Upload to Slack
    comment = f"🖼️ *{topic}* — sourced from NotebookLM\n🤖 Kamil"
    ok = upload_file_to_slack(bot_token, channel, outfile,
                               title=f"Infographic: {topic}", comment=comment)
    try:
        if not ok:
            _log_gap("inline_image_arbitrary", text, "slack_upload", "file_path_fallback")
            _post_text(web, channel, thread_ts,
                       f"🖼️ Generated the infographic for *{topic}* but can't upload it — "
                       f"Kamil app needs `files:write` scope.\n"
                       f"Fix: api.slack.com/apps → Kamil → OAuth Scopes → add `files:write` → Reinstall.\n"
                       f"File saved at: `{outfile}`\n🤖 Kamil")
            return
        klog("infographic_posted", component="infographic_handler",
             topic=topic, nb_id=nb_id, palette=palette, points=len(points))
    finally:
        try:
            Path(outfile).unlink(missing_ok=True)
        except Exception:
            pass
