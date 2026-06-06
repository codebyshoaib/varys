#!/usr/bin/env python3
"""
honesty_gate.py — Pre-send filter for Kamil's Slack responses.

Detects false delivery claims ("here it is", "I posted X") when no actual
file/upload happened. Rewrites to an honest fallback and logs the gap.

Usage:
    from honesty_gate import check, contains_delivery_claim

    answer = run_claude(prompt)
    answer = check(answer, uploaded=_upload_succeeded, request=text)
    web.chat_postMessage(..., text=answer)
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_log import klog, klog_error

KAMIL_DIR = Path(__file__).parent.parent.parent

DELIVERY_CLAIMS = [
    "here's the infographic",
    "here's your infographic",
    "here's the image",
    "here's your image",
    "here is the infographic",
    "here is the image",
    "i posted the infographic",
    "i posted the image",
    "i've posted the image",
    "i've posted the infographic",
    "i generated the infographic",
    "i generated the image",
    "i created the infographic",
    "i created the image",
    "i built the image",
    "i've uploaded the image",
    "i've uploaded the infographic",
    "uploaded it to slack",
    "posted it to slack",
]


def contains_delivery_claim(text: str) -> bool:
    """Return True if the text contains a false delivery claim phrase."""
    lower = text.lower()
    return any(claim in lower for claim in DELIVERY_CLAIMS)


def _rewrite_honest(draft: str, request: str) -> str:
    """
    Run a fast Claude call to rewrite the false-claim response honestly.
    Falls back to a canned message if Claude is unavailable.
    """
    prompt = (
        f"Rewrite this message to be honest. The agent claimed to have produced "
        f"or sent something but did not actually do it. "
        f"Remove the false claim. State clearly what wasn't possible "
        f"and offer 1-2 concrete alternatives that ARE possible. "
        f"Keep it under 3 lines. Sign off: 🤖 Kamil\n\n"
        f"Original request: \"{request[:200]}\"\n\n"
        f"Draft to rewrite:\n\"{draft[:600]}\""
    )
    try:
        nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
        env = os.environ.copy()
        env["_HONESTY_PROMPT"] = prompt
        result = subprocess.run(
            ["bash", "-c",
             f'{nvm} && claude --dangerously-skip-permissions --print -p "$_HONESTY_PROMPT"'],
            capture_output=True, text=True,
            cwd=str(KAMIL_DIR),
            timeout=30, env=env,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()[:500]
    except subprocess.TimeoutExpired as e:
        if e.process:
            e.process.kill()
        klog_error("honesty_gate_timeout", component="honesty_gate")
    except Exception as e:
        klog_error("honesty_gate_rewrite_fail", component="honesty_gate", error=str(e))

    return (
        "I wasn't able to produce that — something went wrong during generation. "
        "Try `nlm slides [topic]` for a slide deck, or ask me to describe the research instead. "
        "🤖 Kamil"
    )


def _log_gap(gap_type: str, request: str, draft: str) -> None:
    """Log to harness.db. Never raises."""
    try:
        from kamil_harness_db import get_db, log_capability_gap
        db = get_db()
        log_capability_gap(
            db,
            gap_type=gap_type,
            request_text=request[:300],
            failed_step="false_claim_in_response",
            fallback_used="honesty_gate_rewrite",
        )
    except Exception as e:
        klog_error("honesty_gate_log_fail", component="honesty_gate", error=str(e))

    klog("honesty_gate_fired", component="honesty_gate",
         gap_type=gap_type, request=request[:100], draft=draft[:100],
         severity="warning")


def check(
    draft: str,
    uploaded: bool,
    request: str,
    gap_type: str = "inline_image_arbitrary",
) -> str:
    """
    Main gate function. Call between run_claude() and chat_postMessage().

    Args:
        draft:    The response Claude produced.
        uploaded: True if a file was actually uploaded to Slack this request.
        request:  The original user request text (for context in rewrite).
        gap_type: The capability gap type to log if firing.

    Returns:
        Safe response text — either the original draft or an honest rewrite.
    """
    if not contains_delivery_claim(draft):
        return draft

    if uploaded:
        return draft

    _log_gap(gap_type, request, draft)
    rewritten = _rewrite_honest(draft, request)
    klog("honesty_gate_rewritten", component="honesty_gate",
         original_len=len(draft), rewritten_len=len(rewritten))
    return rewritten
