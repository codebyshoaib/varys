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
import shutil
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
REPO  = HOOKS.parent.parent
sys.path.insert(0, str(HOOKS))

from varys_harness_db import get_db, mark_slack_processing, mark_slack_done
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
- Anything else (chat, an info question you just answered, a joke) → append NOTHING.
  Only emit WORK for a genuine code-change request, never for questions or discussion."""


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

    mark_slack_processing(db, row_id)

    bot_token = _load_bot_token()
    if not bot_token:
        print("[slack-worker] no BOT_TOKEN found", file=sys.stderr)
        return 1

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

    # Extract trailing directive (NLM: or WORK:) if claude appended one.
    nlm_directive = None
    work_directive = None
    lines = answer.splitlines()
    if lines and lines[-1].startswith("NLM:"):
        nlm_directive = lines[-1][4:].strip()
        answer = "\n".join(lines[:-1]).strip()
    elif lines and lines[-1].startswith("WORK:"):
        work_directive = lines[-1][5:].strip()
        answer = "\n".join(lines[:-1]).strip()

    _slack_post(bot_token, channel, thread_ts, answer)

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
