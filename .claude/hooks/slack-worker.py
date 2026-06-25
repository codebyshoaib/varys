#!/usr/bin/env python3
"""
slack-worker.py — Process a single slack_queue job.

Usage:
    python3 slack-worker.py --job-id <row_id>

Reads job from DB, marks processing, runs claude -p, posts reply to Slack.
Exit 0 = done. Exit 1 = failed (drain caller will mark retry with stderr as failure_context).
"""
import argparse
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
REPO  = HOOKS.parent.parent
sys.path.insert(0, str(HOOKS))

from varys_harness_db import (
    get_db, mark_slack_processing, mark_slack_done, mark_slack_retry,
    enqueue_meeting,
)
from varys_log import klog_error
from varys_eval import log_to_eval, parse_stream_json
from agent_config import cfg

AGENT_NAME    = cfg("AGENT_NAME", "Varys")
USER_NAME     = cfg("USER_NAME", "Shoaib")
SHOAIB_USER_ID = cfg("USER_SLACK_ID", "")
WORKSPACE     = cfg("SLACK_WORKSPACE", "")
DB_PAGE_HARNESS = cfg("NOTION_HARNESS_DB_ID", "")


def _repo_cwd(text: str) -> str:
    registry_path = REPO / ".claude" / "rules" / "repos-registry.json"
    try:
        registry = json.loads(registry_path.read_text())
        for name, info in registry.get("repos", {}).items():
            if name.lower() in text.lower():
                return info["abs_path"]
    except Exception:
        pass
    return str(REPO)


def _claude_bin() -> str:
    c = shutil.which("claude")
    if c:
        return c
    # ponytail: daemon runs without nvm in PATH; fall back to glob
    hits = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/claude")))
    return hits[-1] if hits else "claude"


def _load_bot_token() -> str:
    slack_cfg = Path.home() / ".claude" / "hooks" / ".slack"
    if slack_cfg.exists():
        for line in slack_cfg.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("SLACK_BOT_TOKEN", "")


def _slack_post(token: str, channel: str, thread_ts: str, text: str) -> None:
    payload = json.dumps({"channel": channel, "thread_ts": thread_ts, "text": text}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        resp = json.loads(r.read())
    if not resp.get("ok"):
        raise RuntimeError(f"Slack post failed: {resp.get('error')}")


def _slack_react(token: str, channel: str, msg_ts: str, emoji: str) -> None:
    payload = json.dumps({"channel": channel, "timestamp": msg_ts, "name": emoji}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/reactions.add",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        resp = json.loads(r.read())
    if not resp.get("ok") and resp.get("error") != "already_reacted":
        raise RuntimeError(f"Slack react failed: {resp.get('error')}")


def _fetch_fresh_thread_history(token: str, channel: str, thread_ts: str, is_dm: bool) -> str:
    """Re-fetch thread history from Slack just before building the prompt (always fresh)."""
    try:
        if is_dm:
            url = f"https://slack.com/api/conversations.history?channel={channel}&limit=20"
        else:
            url = (f"https://slack.com/api/conversations.replies"
                   f"?channel={channel}&ts={thread_ts}&limit=30")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        if not data.get("ok"):
            return ""
        messages = data.get("messages", [])
        if is_dm:
            messages = list(reversed(messages))
        lines = []
        for m in messages:
            uid    = m.get("user", "")
            bot_id = m.get("bot_id", "")
            if bot_id:
                who = AGENT_NAME
            elif uid == SHOAIB_USER_ID:
                who = USER_NAME
            else:
                who = f"<@{uid}>"
            text = re.sub(r"<@[A-Z0-9]+>", "", m.get("text", "")).strip()
            if text:
                lines.append(f"{who}: {text}")
        return "\n".join(lines)
    except Exception:
        return ""


def _create_work_bead(work_directive, request_text, channel, thread_ts, sender_id, source):
    """
    Turn a Slack engineering request into a tracked, origin-linked bead.
    work_directive format: "<repo> | <title>". Links the bead's context_key to the
    Slack origin thread so the orchestrator reports plan/PR back HERE, not a guessed channel.
    """
    repo, _, title = work_directive.partition("|")
    repo, title = repo.strip(), title.strip()
    if not title:                       # tolerate "title only" (no repo|)
        title, repo = repo, ""
    if not title:
        return
    bd_bin = shutil.which("bd") or str(Path.home() / ".local" / "bin" / "bd")
    desc = (f"[varys-origin] channel={channel} thread={thread_ts} "
            f"sender={sender_id or ''} repo={repo}\n\nFrom Slack ({source}): {request_text[:500]}")
    try:
        r = subprocess.run(
            [bd_bin, "create", title, "-t", "bug", "-d", desc, "--silent"],
            capture_output=True, text=True, cwd=str(REPO), timeout=15,
        )
        bead_id = (r.stdout or "").strip().split()[-1] if r.returncode == 0 and r.stdout.strip() else ""
        if not bead_id:
            print(f"[slack-worker] WORK bead create failed: {r.stderr[:200]}", file=sys.stderr)
            return
        # Link origin → the SAME context_key poll-beads will mint (idempotent on bead_id).
        from varys_harness_db import register_entity, link_entities
        db = get_db()
        ctx = register_entity(db, "beads", bead_id, "ticket", f"beads:{bead_id}")
        slack_ent = register_entity(db, "slack", f"{channel}/{thread_ts}", "thread",
                                    f"https://slack.com/archives/{channel}/p{thread_ts.replace('.','')}")
        link_entities(db, ctx, slack_ent, "origin", session_id="slack-worker")
        db.close()
        print(f"[slack-worker] WORK bead {bead_id} ({repo or 'no-repo'}) linked to {channel}/{thread_ts}")
    except Exception as e:
        print(f"[slack-worker] WORK bead error: {e}", file=sys.stderr)


def _build_prompt(
    text: str, thread_history: str, source: str,
    sender_name: str, is_third_party: bool, is_dm: bool,
    failure_context: str,
) -> str:
    caps_path = REPO / ".claude" / "rules" / "CAPABILITIES.md"
    caps_block = caps_path.read_text() if caps_path.exists() else ""
    prev = f"[Previous attempt failed: {failure_context[:500]}]\n\n" if failure_context else ""

    if is_third_party:
        return f"""{prev}You are {AGENT_NAME} — {USER_NAME}'s AI agent at Taleemabad, replying on behalf of a conversation.

{sender_name or "Someone"} says: "{text}"

Thread so far:
{thread_history or "(no prior context)"}

Reply warmly and briefly (1–3 lines). Do NOT reveal private info about {USER_NAME}, the team, or internal systems. Do NOT sign off as "{AGENT_NAME}". Reply naturally."""

    return f"""{prev}You are {AGENT_NAME} — a senior team member at Taleemabad.

Your ONE job here: write the reply text to the Slack message below. Nothing else.

## CRITICAL — how delivery works
The system posts your output to Slack for you. You do NOT send anything yourself.
- Do NOT call any Slack API, curl, or chat.postMessage. Just write the reply.
- Do NOT call mcp__slack__slack_reply_to_thread, mcp__slack__slack_post_message, or ANY mcp__slack__* write tool. These are BLOCKED by a PreToolUse hook. If you call them, the hook denial becomes your reply instead of your actual answer — that is the bug the user sees.
- Do NOT say "I sent", "I posted", "I DM'd", "sent as a DM", or anything about delivery.
- Do NOT reason about channels, threads, DMs, or whether you're "in" a channel — that is the system's job, not yours.
- Whatever text you output IS the message. Write it as the reply itself.

## HOW TO ANSWER
- Just answer the question directly and well. You can research first (WebSearch, WebFetch, gh, reading repo files) if it helps.
- Be warm, concise, decisive. Slack format: *bold*, bullets, emoji — no markdown headers.
- If it's casual (banter, joke), be casual and brief.
- If it asks for an explanation, give a clear, genuinely useful one.
- NEVER offer execution options or ask questions the code/web can answer. Look it up, then answer.

## NotebookLM — you CAN do this (do NOT refuse it)
You have a working NotebookLM integration (the `nlm` CLI). On any topic you can generate:
  research | infographic | slides | mindmap | podcast | brief | quiz   — and `ask <notebook> <question>` to query one.
These run ASYNC (~2–5 min) and the finished artifact is posted back here when ready. That delay is NORMAL — it is NOT a failure and NOT a reason to refuse.

If the user asks for ANY NotebookLM artifact (slides, mindmap, podcast, "notebooklm infographic", research, etc.):
1. Do NOT refuse, do NOT ask which option they want. Just start it.
2. Briefly acknowledge it's generating and will land here in ~2–5 min.
3. Append ONE final line, EXACTLY this format:
   NLM: <subcommand> <topic>
   where <subcommand> is one of: research infographic slides mindmap podcast brief quiz ask
   ("visual" → infographic. The notebook is auto-created + researched first if it doesn't exist — you don't need to do that step.)
   Examples:  NLM: infographic graphify   |   NLM: slides graphify   |   NLM: research multi-tenant auth   |   NLM: mindmap django signals

## DO NOT
- Do NOT claim you did something you didn't.
- Do NOT generate arbitrary standalone images yourself — that's the only visual you can't do (NLM artifacts above ARE fine).

## WHAT {AGENT_NAME.upper()} CANNOT DO
{caps_block}

## CONTEXT
Taleemabad, Pakistan — EdTech, Django + React, multi-tenant LMS.

## THREAD HISTORY
{thread_history or "(no prior messages)"}

## CURRENT MESSAGE
Source: {source}
{USER_NAME} says: "{text}"

Write the reply now. Output ONLY the reply text — no headers, no meta-commentary, no delivery talk. Sign off: 🕷️ {AGENT_NAME}

Then, if applicable, append ONE directive line as the VERY LAST line:
- NLM request → `NLM: <subcommand> <topic>` (see above)
- REAL ENGINEERING WORK on a repo (an explicit ask to fix/build/implement/add/change code,
  e.g. "fix the X bug in compliance-tracker", "add endpoint Y to taleemabad-core") →
  `WORK: <repo> | <≤10-word imperative title>`. The repo must be named or unmistakable from context.
  For a WORK item your reply text MUST be a SHORT acknowledgement only (1 line, e.g.
  "On it — I'll post a plan in this thread shortly."). Do NOT attempt the fix yourself here.
- No text reply needed (someone said "thanks", "ok", sent an emoji, or the message is purely
  informational and an emoji reaction is the right response) →
  Output NOTHING except: `REACT: <emoji_name>`
  e.g. `REACT: white_check_mark`, `REACT: thumbsup`, `REACT: eyes`, `REACT: raised_hands`, `REACT: fire`
  The system adds that emoji reaction to their message — no text posted. Use this when a reaction is genuinely more natural than words.
- Anything else (chat, an info question you just answered, a joke) → append NOTHING.
  Only emit WORK for a genuine code-change request, never for questions or discussion."""


def _parse_pre_tool_text(stdout: str) -> str:
    """Return text from the first assistant message, stopping before any tool_use block.

    When a drift-leak occurs Claude's *final* result is meta-commentary, but the
    original good reply is in the first assistant event's text blocks (before it
    tried to call mcp__slack__*). This extracts that pre-tool text for HTTP fallback.
    """
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if ev.get("type") != "assistant":
            continue
        texts = []
        for block in (ev.get("message", {}) or {}).get("content", []) or []:
            if block.get("type") == "text" and block.get("text"):
                texts.append(block["text"])
            elif block.get("type") == "tool_use":
                break  # stop before the Slack tool call
        if texts:
            return "\n".join(texts).strip()
    return ""


_ACTIVE_RECORDING_FILE = Path.home() / ".varys-harness" / "active_recording.json"


def _handle_start_recording(
    db, bot_token: str,
    channel: str, thread_ts: str,
    name_hint: str,
) -> int:
    """Handle 'start recording [name]' command. Returns exit code."""
    import datetime

    if _ACTIVE_RECORDING_FILE.exists():
        try:
            state = json.loads(_ACTIVE_RECORDING_FILE.read_text())
            existing_name = state.get("meeting_name", "unknown")
        except Exception:
            existing_name = "unknown"
        _slack_post(bot_token, channel, thread_ts,
                    f"Already recording *{existing_name}*. Reply `stop recording` to finish first.")
        return 0

    now = datetime.datetime.now()
    date_slug = now.strftime("%Y-%m-%d_%H-%M")
    meeting_name = name_hint if name_hint else date_slug
    # Sanitise meeting_name for filesystem use
    meeting_name_fs = re.sub(r'[^\w\-]', '_', meeting_name).strip('_') or date_slug

    output_dir = REPO / "vault" / "projects" / "meeting-notes" / "recordings" / date_slug
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = str(output_dir / f"{meeting_name_fs}.flac")

    try:
        proc = subprocess.Popen(
            [
                "ffmpeg", "-f", "pulse", "-i", "default.monitor",
                "-f", "pulse", "-i", "default",
                "-filter_complex", "amix=inputs=2:normalize=0",
                "-ar", "16000", "-ac", "1", "-c:a", "flac",
                audio_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        klog_error("start_recording", exc, component="slack-worker")
        _slack_post(bot_token, channel, thread_ts,
                    f"Failed to start ffmpeg: {exc}. Is ffmpeg installed?")
        return 1

    state = {
        "pid":          proc.pid,
        "meeting_name": meeting_name,
        "audio_path":   audio_path,
        "output_dir":   str(output_dir),
        "channel":      channel,
        "thread_ts":    thread_ts,
        "started_at":   now.isoformat(),
    }
    _ACTIVE_RECORDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ACTIVE_RECORDING_FILE.write_text(json.dumps(state, indent=2))

    _slack_post(bot_token, channel, thread_ts,
                f"🎙️ Recording *{meeting_name}* started. Reply `stop recording` to finish.")
    print(f"[slack-worker] recording started: pid={proc.pid} name={meeting_name}")
    return 0


def _handle_stop_recording(
    db, bot_token: str,
    channel: str, thread_ts: str,
) -> int:
    """Handle 'stop recording' command. Returns exit code."""
    if not _ACTIVE_RECORDING_FILE.exists():
        _slack_post(bot_token, channel, thread_ts,
                    "No active recording. Use `start recording [name]` to begin.")
        return 0

    try:
        state = json.loads(_ACTIVE_RECORDING_FILE.read_text())
    except Exception as exc:
        klog_error("stop_recording_read_state", exc, component="slack-worker")
        _ACTIVE_RECORDING_FILE.unlink(missing_ok=True)
        _slack_post(bot_token, channel, thread_ts,
                    "Active recording state was corrupt — cleaned up. No audio was enqueued.")
        return 1

    pid          = state.get("pid")
    meeting_name = state.get("meeting_name", "unknown")
    audio_path   = state.get("audio_path", "")
    output_dir   = state.get("output_dir", "")
    orig_channel = state.get("channel", channel)
    orig_thread  = state.get("thread_ts", thread_ts)

    pid_alive = False
    if pid:
        try:
            os.kill(pid, signal.SIGINT)
            # Wait up to 5s for graceful exit
            for _ in range(10):
                try:
                    os.kill(pid, 0)   # probe — raises if dead
                    time.sleep(0.5)
                except ProcessLookupError:
                    break
            pid_alive = False
        except ProcessLookupError:
            # PID was already dead (stale crash scenario)
            pid_alive = False
        except Exception as exc:
            klog_error("stop_recording_kill", exc, component="slack-worker")

    _ACTIVE_RECORDING_FILE.unlink(missing_ok=True)

    # Enqueue even if PID was stale — partial audio is better than nothing
    audio_exists = Path(audio_path).exists() if audio_path else False
    if not audio_exists:
        _slack_post(bot_token, orig_channel, orig_thread,
                    f"Recording *{meeting_name}* stopped but no audio file found at `{audio_path}`. "
                    "Nothing to transcribe.")
        return 0

    try:
        job_id = enqueue_meeting(
            db,
            meeting_name=meeting_name,
            audio_path=audio_path,
            output_dir=output_dir,
            channel=orig_channel,
            thread_ts=orig_thread,
        )
    except Exception as exc:
        klog_error("stop_recording_enqueue", exc, component="slack-worker")
        _slack_post(bot_token, orig_channel, orig_thread,
                    f"Recording *{meeting_name}* stopped but failed to queue transcription: {exc}")
        return 1

    _slack_post(bot_token, orig_channel, orig_thread,
                f"✅ Recording *{meeting_name}* stopped. Transcription queued (job `{job_id[:8]}`) — "
                "I'll post the summary here when done. (~2–4× realtime on CPU so be patient 🐢)")
    print(f"[slack-worker] recording stopped and enqueued: {job_id} name={meeting_name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()

    db  = get_db()
    row = db.execute(
        "SELECT id, source, channel, thread_ts, sender_id, sender_name, text, "
        "thread_history, is_dm, is_third_party, job_id, retry_count, priority, failure_context "
        "FROM slack_queue WHERE id=? AND status IN ('pending', 'processing')",
        (args.job_id,),
    ).fetchone()

    if not row:
        print(f"[slack-worker] job {args.job_id} not found", file=sys.stderr)
        return 1

    (row_id, source, channel, thread_ts, sender_id, sender_name,
     text, thread_history, is_dm, is_third_party, job_id, retry_count,
     priority, failure_context) = row

    # Extract the original message ts from the row_id (format: "slack-{channel}-{msg_ts}")
    # Used for reactions.add, which targets the specific message, not the thread root.
    _prefix = f"slack-{channel}-"
    msg_ts = row_id[len(_prefix):] if row_id.startswith(_prefix) else thread_ts

    mark_slack_processing(db, row_id)

    bot_token = _load_bot_token()
    if not bot_token:
        print("[slack-worker] no BOT_TOKEN found", file=sys.stderr)
        return 1

    # Re-fetch thread history live — the enqueued snapshot may be stale if the
    # thread grew between enqueue and drain. Fall back to stored value on failure.
    fresh_history = _fetch_fresh_thread_history(bot_token, channel, thread_ts, bool(is_dm))
    if fresh_history:
        thread_history = fresh_history

    # ── Recording commands — handled before the normal claude -p pipeline ─────
    text_lower = (text or "").lower().strip()
    _start_match = re.search(r'\bstart recording\s*(.*)', text_lower)
    _stop_match  = re.search(r'\bstop recording\b', text_lower)

    if _start_match:
        rc = _handle_start_recording(
            db=db, bot_token=bot_token,
            channel=channel, thread_ts=thread_ts,
            name_hint=_start_match.group(1).strip(),
        )
        if rc == 0:
            mark_slack_done(db, row_id)
        return rc
    if _stop_match:
        rc = _handle_stop_recording(
            db=db, bot_token=bot_token,
            channel=channel, thread_ts=thread_ts,
        )
        if rc == 0:
            mark_slack_done(db, row_id)
        return rc
    # ── End recording commands ────────────────────────────────────────────────

    # ── Region-friction-coach approval loop (DM only) ─────────────────────────
    # Coach DMs Shoaib a preview + registers friction-pending.json. His reply
    # ("post" / "amend …" / "cancel") is consumed here before the normal pipeline.
    if is_dm:
        import friction_approval
        handled = friction_approval.maybe_handle(
            text=text, sender_id=sender_id, bot_token=bot_token,
            post_fn=lambda t: _slack_post(bot_token, channel, thread_ts, t),
            claude_bin=_claude_bin(), approver_id=SHOAIB_USER_ID,
        )
        if handled:
            mark_slack_done(db, row_id)
            return 0
    # ── End friction approval ─────────────────────────────────────────────────

    # ── PR review fast-path ───────────────────────────────────────────────────
    _PR_TRIGGERS = ("review this pr", "review the pr", "review pr", "code review")
    if not is_third_party and any(t in text_lower for t in _PR_TRIGGERS):
        _pr_match = re.search(
            r'https://github\.com/[^\s>]+/pull/\d+',
            text + "\n" + (thread_history or ""),
        )
        if not _pr_match:
            _slack_post(bot_token, channel, thread_ts,
                        "I couldn't find a PR URL in this thread — share the link and I'll review it. 🕷️ Varys")
            mark_slack_done(db, row_id)
            return 0

        pr_url = _pr_match.group(0).rstrip(")")
        ts_clean = thread_ts.replace(".", "")
        slack_thread_url = f"https://{WORKSPACE}.slack.com/archives/{channel}/p{ts_clean}"

        _u = pr_url.lower()
        if "compliancetracker" in _u:
            skill_cmd = f"/compliancetracker-pr-reviewer {pr_url} {slack_thread_url}"
        elif "taleemabad-core" in _u:
            skill_cmd = f"/taleemabad-pr-review-lite {pr_url}"
        else:
            skill_cmd = None

        if skill_cmd:
            _slack_post(bot_token, channel, thread_ts,
                        f"On it — running `{skill_cmd.split()[0]}` on {pr_url} 🔍")
            subprocess.run(
                [_claude_bin(), "--dangerously-skip-permissions", "--print", "-p", skill_cmd],
                capture_output=True, text=True,
                cwd=str(REPO), timeout=900,
            )
            # skill posted inline GitHub comments + Slack summary itself (Step 3)
            mark_slack_done(db, row_id)
            return 0
        # unknown repo — fall through to generic handler
    # ── End PR review fast-path ───────────────────────────────────────────────

    prompt = _build_prompt(
        text=text,
        thread_history=thread_history or "",
        source=source,
        sender_name=sender_name or "",
        is_third_party=bool(is_third_party),
        is_dm=bool(is_dm),
        failure_context=failure_context or "",
    )

    t0 = time.time()
    result = subprocess.run(
        # stream-json (+ --verbose, required with --print) so we can capture which
        # tools the agent ACTUALLY called — fed to the eval judge to catch fabricated
        # tool-use. parse_stream_json falls back to raw stdout if the format changes.
        [_claude_bin(), "--dangerously-skip-permissions", "--print",
         "--output-format", "stream-json", "--verbose", "-p", prompt],
        capture_output=True, text=True,
        cwd=_repo_cwd(text), timeout=300,
        # Rumi principle: this agent writes text only. The harness (_slack_post below)
        # delivers it. VARYS_CONTENT_AGENT=1 lets block-agent-slack-drift.py hard-deny
        # any Slack send the agent tries, so it can't pick its own channel.
        env={**os.environ, "VARYS_CONTENT_AGENT": "1"},
    )
    latency_s = round(time.time() - t0, 1)

    if result.returncode != 0 or not result.stdout.strip():
        error_msg = result.stderr.strip()[:1000] or "no output"
        print(f"[slack-worker] claude failed: {error_msg}", file=sys.stderr)
        return 1

    answer, tools_used = parse_stream_json(result.stdout)
    answer = answer.strip()

    # Guard: if the final output is meta-commentary from a blocked Slack MCP tool call
    # (drift hook fired, Claude then said "I don't have channel id" / "spawned harness" etc.)
    # recover the actual reply from the stream and post it via raw HTTP.
    _DRIFT_LEAK = re.compile(
        r"don[''t]+ have.{0,40}channel|"
        r"spawned harness agent|"
        r"cannot post to Slack|"
        r"I.{0,10}m unable to (send|post|reply)",
        re.I,
    )
    if _DRIFT_LEAK.search(answer):
        print(f"[slack-worker] drift-leak detected: {answer[:200]}", file=sys.stderr)
        klog_error("drift_leak_suppressed", RuntimeError(f"drift leak: {answer[:200]}"), component="slack-worker")

        # Recover the original text from the stream: first assistant message,
        # text blocks only, stopping before any tool_use block appears.
        recovered = _parse_pre_tool_text(result.stdout)
        if recovered:
            try:
                _slack_post(bot_token, channel, thread_ts, recovered)
                print(f"[slack-worker] drift-leak recovered via HTTP fallback: {len(recovered)} chars")
                mark_slack_done(db, row_id)
                return 0
            except Exception as http_err:
                klog_error("drift_leak_http_fallback_failed", http_err, component="slack-worker")
                print(f"[slack-worker] HTTP fallback also failed: {http_err}", file=sys.stderr)

        # Recovery unavailable or HTTP failed — leave as pending so drain retries.
        mark_slack_retry(db, row_id, failure_context=f"drift-leak (no recovery): {answer[:200]}")
        return 1

    # Extract trailing directive (NLM:, WORK:, or REACT:) if claude appended one.
    nlm_directive = None
    work_directive = None
    react_emoji = None
    lines = answer.splitlines()
    if lines and lines[-1].startswith("NLM:"):
        nlm_directive = lines[-1][4:].strip()
        answer = "\n".join(lines[:-1]).strip()
    elif lines and lines[-1].startswith("WORK:"):
        work_directive = lines[-1][5:].strip()
        answer = "\n".join(lines[:-1]).strip()
    elif lines and lines[-1].startswith("REACT:"):
        react_emoji = re.sub(r"[^a-z0-9_\-]", "", lines[-1][6:].strip().lower())
        answer = "\n".join(lines[:-1]).strip()

    if react_emoji and not answer:
        # Pure reaction — no text reply needed
        try:
            _slack_react(bot_token, channel, msg_ts, react_emoji)
            print(f"[slack-worker] reacted :{react_emoji}: to {msg_ts}")
        except Exception as e:
            print(f"[slack-worker] react failed ({e}), skipping", file=sys.stderr)
    else:
        if answer:
            _slack_post(bot_token, channel, thread_ts, answer)
        if react_emoji:
            # Both a text reply and a reaction (model included text before REACT:)
            try:
                _slack_react(bot_token, channel, msg_ts, react_emoji)
            except Exception:
                pass

    # Eval Log: this is the LIVE reply path, so logging MUST happen here (the listener's
    # handle_message is not the runtime path). thread = full history, tools = what the
    # agent actually called — both feed the nightly judge. Third-party replies are
    # excluded (they're not Varys-as-Shoaib answers and would skew the eval).
    if not is_third_party:
        log_to_eval(
            conv_id     = f"{channel}-{thread_ts}",
            sender_name = sender_name or USER_NAME,
            request     = text,
            reply       = answer,
            mode        = "dm" if is_dm else "mention",
            source      = source,
            latency_s   = latency_s,
            thread      = thread_history or "",
            tools       = ", ".join(tools_used),
            block       = True,   # short-lived process; must write before exit
        )

    # WORK directive → create an origin-tagged bead so the orchestrator tracks it,
    # plans in THIS thread, and (on Shoaib's "go") implements + PRs back HERE.
    # Origin is linked to the bead's context_key now, keyed by the same bead_id that
    # poll-beads will register — so the manager resolves this thread, not a guessed channel.
    if work_directive and thread_ts:
        _create_work_bead(work_directive, text, channel, thread_ts, sender_id, source)

    if nlm_directive:
        # NLM artifacts take 2–5 min — run notebooklm_handler in a DETACHED process
        # so it outlives this short-lived worker. It posts the artifact to Slack itself.
        subprocess.Popen(
            ["python3", str(HOOKS / "notebooklm_handler.py"), "--handle", f"nlm {nlm_directive}"],
            env={**os.environ, "SLACK_BOT_TOKEN": bot_token,
                 "NLM_POST_CHANNEL": channel, "USER_SLACK_ID": SHOAIB_USER_ID},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, cwd=str(REPO),
        )
        print(f"[slack-worker] nlm dispatched (detached): {nlm_directive}")

    mark_slack_done(db, row_id)
    print(f"[slack-worker] done: {row_id} → {len(answer)} chars posted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
