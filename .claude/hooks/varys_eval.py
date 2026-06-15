"""
varys_eval.py — Eval harness sync layer.

After every conversation:
1. Auto-creates a row in Notion Eval Log DB (Rating = Unreviewed)
2. Shoaib reviews: sets Rating + optionally adds a note
3. varys-learn.sh reads ❌ Wrong / ⚠️ Partial rows nightly
4. Classifies failure type, proposes exact prompt fix, DMs Shoaib
5. Shoaib approves → Varys applies fix → marks Fix Applied

Eval Log DB: collection://2e46d119-159e-4634-9195-a7343e590dbe
"""

import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

VARYS_DIR     = Path(__file__).parent.parent.parent
EVAL_DS_ID    = "2e46d119-159e-4634-9195-a7343e590dbe"
EVAL_DB_ID    = "94017dd157b44f3ca96423ad2ad989da"
EVAL_LOG_FILE = Path("/tmp/varys-eval-pending.jsonl")  # local buffer before Notion write


def _run_claude(prompt: str, timeout: int = 90) -> str:
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    env = os.environ.copy()
    env["VARYS_PROMPT"] = prompt
    try:
        result = subprocess.run(
            ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$VARYS_PROMPT"'],
            capture_output=True, text=True,
            cwd=str(VARYS_DIR), timeout=timeout, env=env,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def log_to_eval(
    conv_id: str,
    sender_name: str,
    request: str,
    reply: str,
    mode: str,
    source: str,
    latency_s: float,
):
    """
    Write conversation to Eval Log DB in Notion.
    Runs in background thread — never blocks the reply.
    """
    threading.Thread(
        target=_write_eval_entry,
        args=(conv_id, sender_name, request, reply, mode, source, latency_s),
        daemon=True,
    ).start()


def _write_eval_entry(conv_id, sender_name, request, reply, mode, source, latency_s):
    today  = datetime.now().strftime("%Y-%m-%d")
    title  = f"{sender_name}: {request[:60]}"

    # Buffer locally first (instant)
    entry = {
        "conv_id": conv_id, "sender": sender_name, "request": request,
        "reply": reply, "mode": mode, "source": source,
        "latency_s": latency_s, "date": today, "written": False,
    }
    try:
        with open(EVAL_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass

    # Write to Notion
    prompt = f"""You are Varys. Write one entry to the Eval Log DB.

Use mcp__claude_ai_Notion__notion-create-pages:
  parent: data_source_id = {EVAL_DS_ID}

Properties:
  Conversation: "{title}"
  Sender: "{sender_name}"
  Request: "{request[:500]}"
  Varys Reply: "{reply[:500]}"
  Mode: "{mode}"
  Source: "{source}"
  Rating: "🔁 Unreviewed"
  Conv ID: "{conv_id}"
  Latency S: {latency_s}
  date:Date:start: "{today}"

No page content needed. Reply only "done" when created."""

    _run_claude(prompt, timeout=60)


def read_low_rated_evals() -> list:
    """
    Read ❌ Wrong and ⚠️ Partial entries from Eval Log DB.
    Used by nightly learn loop.
    Returns list of dicts with full conversation details.
    """
    prompt = f"""You are Varys. Query the Eval Log DB for low-rated conversations.

Use mcp__claude_ai_Notion__notion-search to find pages in DB {EVAL_DB_ID}
where Rating is "❌ Wrong" or "⚠️ Partial" and Fix Applied is false.

For each result, extract: Conversation title, Sender, Request, Varys Reply,
Rating, Failure Type, Your Note, Conv ID.

Return a JSON array on the last line:
[{{"title":"...", "sender":"...", "request":"...", "reply":"...", "rating":"...",
   "failure_type":"...", "your_note":"...", "conv_id":"..."}}]"""

    result = _run_claude(prompt, timeout=90)
    if result:
        for line in reversed(result.strip().splitlines()):
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                try:
                    return json.loads(line)
                except Exception:
                    pass
    return []


def confidence_score() -> dict:
    """
    Calculate Varys's current confidence score from Eval Log DB.
    Returns {total, good, partial, wrong, score_pct}
    """
    prompt = f"""Query the Eval Log DB (ID: {EVAL_DB_ID}) and count entries by Rating.

Use mcp__claude_ai_Notion__notion-search to search for all pages in this DB.
Count: how many are ✅ Good, ⚠️ Partial, ❌ Wrong, 🔁 Unreviewed.

Return JSON on last line:
{{"total": N, "good": N, "partial": N, "wrong": N, "unreviewed": N, "score_pct": N}}

score_pct = good / (good + partial + wrong) * 100, ignore unreviewed."""

    result = _run_claude(prompt, timeout=60)
    if result:
        for line in reversed(result.strip().splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except Exception:
                    pass
    return {"total": 0, "good": 0, "partial": 0, "wrong": 0, "score_pct": 0}
