#!/usr/bin/env python3
"""
friction_approval.py — DM approval loop for region-friction-coach.

The coach DMs Shoaib a preview and writes friction-pending.json. When Shoaib
replies in the DM, slack-worker.py calls maybe_handle() BEFORE its normal
claude -p pipeline:

  "post" / "send" / "approve" / "go"   → post the pending message to the channel
  "amend …" / "add …" / "remove …"     → Varys revises the message, re-asks for confirmation
  "cancel" / "discard"                 → drop it, post nothing

Only the registered approver (Shoaib) can act. Pending state is single-shot:
posting or cancelling clears it; amending replaces the message and keeps it open.

ponytail: word-prefix matching, not NLU. While a preview is pending, a normal DM
that happens to start with post/add/remove is the known ambiguity ceiling — the
amend path defends against it by letting the model bail with NOT_AN_EDIT.
"""
import json
import os
import subprocess
import urllib.request
from pathlib import Path

PENDING = Path.home() / ".varys-harness" / "friction-pending.json"

_POST   = ("post", "send", "approve", "go", "yes", "ship", "send it", "post it", "lgtm", "looks good")
_CANCEL = ("cancel", "discard", "drop it", "forget it", "no", "scrap")
_AMEND  = ("amend", "add", "remove", "change", "edit", "reword", "rewrite", "drop ",
           "take out", "replace", "shorten", "tighten", "instead", "rephrase")


def load_pending():
    if PENDING.exists():
        try:
            return json.loads(PENDING.read_text())
        except Exception:
            return None
    return None


def clear_pending():
    try:
        PENDING.unlink()
    except Exception:
        pass


def _starts(text, words):
    return any(text == w or text.startswith(w + " ") or text == w + "." for w in words)


def _post_to_channel(bot_token, channel_id, text):
    data = json.dumps({"channel": channel_id, "text": text, "unfurl_links": False}).encode()
    req = urllib.request.Request("https://slack.com/api/chat.postMessage", data=data,
        headers={"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return bool(json.loads(r.read()).get("ok"))
    except Exception:
        return False


def _amend(claude_bin, current_msg, instruction):
    """Revise the pending message per `instruction`. Returns new text, or None if the
    model judges the instruction isn't actually an edit to this message."""
    prompt = (
        "You are Varys, editing a Slack message that is about to be posted to a team channel.\n"
        "Apply the instruction to the message. Preserve Varys's measured voice, the per-person\n"
        "`<@U...>` mention lines, the italic _solution_ lines, and the `— Varys 🕷️` sign-off.\n"
        "If the instruction is clearly NOT an edit to this message (e.g. an unrelated question),\n"
        "output exactly NOT_AN_EDIT and nothing else.\n"
        "Output ONLY the full revised message text — no preamble, no code fences.\n\n"
        f"INSTRUCTION: {instruction}\n\nCURRENT MESSAGE:\n{current_msg}"
    )
    try:
        r = subprocess.run(
            [claude_bin, "--dangerously-skip-permissions", "--print", "-p", prompt],
            capture_output=True, text=True, timeout=180,
            env={**os.environ, "VARYS_CONTENT_AGENT": "1"},
        )
        out = (r.stdout or "").strip()
        if not out or out == "NOT_AN_EDIT" or out.startswith("NOT_AN_EDIT"):
            return None
        return out
    except Exception:
        return None


def maybe_handle(text, sender_id, bot_token, post_fn, claude_bin, approver_id):
    """Returns True if this DM was a friction-approval command and was handled (caller
    should mark the job done and stop). False → not for us; fall through to normal pipeline."""
    pend = load_pending()
    if not pend:
        return False
    if approver_id and sender_id and sender_id != approver_id:
        return False  # only the king approves

    t = (text or "").strip()
    tl = t.lower()
    target = pend.get("channel_target", "the channel")
    channel_id = pend.get("channel_id")
    message = pend.get("message", "")

    if _starts(tl, _CANCEL):
        clear_pending()
        post_fn(f"Discarded — nothing posted to #{target}. 🕷️ Varys")
        return True

    if _starts(tl, _POST):
        ok = _post_to_channel(bot_token, channel_id, message)
        if ok:
            clear_pending()
            post_fn(f"Posted to #{target}. 🕷️ Varys")
        else:
            post_fn(f"I couldn't post to #{target} — the message is still pending, try *post* again. 🕷️ Varys")
        return True

    if _starts(tl, _AMEND):
        revised = _amend(claude_bin, message, t)
        if not revised:
            return False  # model says it isn't an edit → let the normal pipeline answer it
        pend["message"] = revised
        try:
            PENDING.write_text(json.dumps(pend, indent=1))
        except Exception:
            pass
        post_fn(f"Revised. Reply *post* to send to #{target}, or keep amending:\n\n{revised}")
        return True

    return False
