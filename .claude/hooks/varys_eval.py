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
FAILURES_FILE = VARYS_DIR / ".beads" / "failures.jsonl"


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


def _parse_last_json(result: str, opener: str):
    """Return the last line that parses as JSON starting with opener ('{' or '[')."""
    if not result:
        return None
    closer = "}" if opener == "{" else "]"
    for line in reversed(result.strip().splitlines()):
        line = line.strip()
        if line.startswith(opener) and line.endswith(closer):
            try:
                return json.loads(line)
            except Exception:
                pass
    return None


def _reaction_signals() -> dict:
    """
    Build a {conv_id: signal} map from the local pending/reaction buffer.

    eval-tracker stores pending conversation actions keyed by action_id, not
    conv_id, and the Eval Log row uses conv_id. There is no shared key, so we
    surface the buffer's reaction evidence at a coarse level: if a conversation
    action for a channel/ts is still pending it means no reply was seen yet.
    We pass the raw buffer to the judge and let it correlate on request text —
    the judge already receives the request per row. Silence stays neutral.
    """
    signals = {}
    if not EVAL_LOG_FILE.exists():
        return signals
    try:
        for line in EVAL_LOG_FILE.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            cid = entry.get("conv_id")
            if cid:
                # Presence of a buffered conversation row with reacted info, if any.
                signals[cid] = entry.get("reacted", "unknown")
    except Exception:
        pass
    return signals


def _existing_failure_conv_ids() -> set:
    """conv_ids already minted into failures.jsonl (for dedupe)."""
    seen = set()
    if not FAILURES_FILE.exists():
        return seen
    try:
        for line in FAILURES_FILE.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            cid = entry.get("conv_id")
            if cid:
                seen.add(cid)
    except Exception:
        pass
    return seen


_NOTE_MAX = 120


def _clean_note(raw: str) -> str:
    """
    Sanitise a judge-supplied note so it can never break a single JSON line:
    collapse all whitespace (incl. newlines) to single spaces and cap length.
    json.dumps already escapes quotes, but a one-line entry must stay one line.
    """
    note = " ".join((raw or "").split())  # collapses \n, \t, runs of spaces
    return note[:_NOTE_MAX]


def _mint_failures(wrong_rows: list) -> int:
    """
    Append one failures.jsonl line per ❌ Wrong row, deduped by conv_id.

    Each entry carries a `ts` (ISO) so varys-evolution-agent's counter sees it.
    The minted entry depends ONLY on structured, sanitised fields (conv_id,
    failure_type, capped note) — never on free-form `request` text, which could
    carry newlines/quotes that corrupt the JSON line (and silently mint zero
    failures when _parse_last_json then returns None upstream).
    Returns the number of new entries written.
    """
    if not wrong_rows:
        return 0
    seen = _existing_failure_conv_ids()
    now  = datetime.utcnow().isoformat()
    today = datetime.now().strftime("%Y-%m-%d")
    minted = 0
    lines = []
    for row in wrong_rows:
        conv_id = (row.get("conv_id") or "").strip()
        if not conv_id or conv_id in seen:
            continue
        seen.add(conv_id)  # guard against dupes within this same batch too
        failure_type = (row.get("failure_type") or "unclassified").strip() or "unclassified"
        note         = _clean_note(row.get("note"))
        entry = {
            "ts": now,
            "date": today,
            "incident": f"Eval {conv_id} rated ❌ Wrong: {note}".strip().rstrip(":")
                        if note else f"Eval {conv_id} rated ❌ Wrong",
            "root_cause": failure_type,
            "lesson": note or "Rated ❌ Wrong by nightly auto-judge; review conversation.",
            "source": "auto-judge",
            "conv_id": conv_id,
        }
        lines.append(json.dumps(entry))
        minted += 1
    if lines:
        try:
            FAILURES_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(FAILURES_FILE, "a") as f:
                f.write("\n".join(lines) + "\n")
        except Exception:
            return 0
    return minted


def judge_unreviewed(date: str = None) -> dict:
    """
    Auto-rate every 🔁 Unreviewed row in the Eval Log DB with an LLM judge.

    One claude -p pass over the batch: read rows → rate all → patch all in Notion.
    Applies the conversation rubric (see varys_eval_tracker.py). Idempotent: only
    rows still Unreviewed are touched. After rating, ❌ Wrong rows are minted into
    failures.jsonl (deduped by conv_id) to fuel the evolution agent.

    Returns {total, good, partial, wrong, scored, minted}.
    """
    target_date = date or datetime.now().strftime("%Y-%m-%d")
    signals = _reaction_signals()
    signals_blob = json.dumps(signals) if signals else "{}"

    prompt = f"""You are Varys, acting as a strict eval judge. Rate today's unreviewed conversations.

## Step 1 — read the rows
Use mcp__claude_ai_Notion__notion-search to find pages in DB {EVAL_DB_ID} where
Rating is "🔁 Unreviewed" AND date:Date:start is "{target_date}".
For each, read: page id, Conversation title, Sender, Request, Varys Reply, Mode, Source, Conv ID.
If there are no such rows, skip to Step 4 and return all-zero counts.

## Step 2 — rate each row (conversation rubric)
Assign Rating ∈ {{"✅ Good","⚠️ Partial","❌ Wrong"}}:
- ✅ Good  — answered with tools, no needless clarification, useful/actionable reply.
- ⚠️ Partial — answer was okay but incomplete, or asked a clarifying question a tool could
              have answered, or was slow/hedged.
- ❌ Wrong — wrong answer, Varys had to be corrected, asked the user to do what a tool does,
            or the reply did not address the request.

Reaction signal (weight toward ❌ Wrong / ⚠️ Partial when present; silence is NEUTRAL,
never penalise silence): this JSON maps Conv ID → reaction evidence where known.
If a Conv ID maps to "reacted":"no" combined with a repeat/correction in the thread,
lean Partial/Wrong. {signals_blob}

Also assign a short Failure Type (e.g. "asked-clarifying-question", "wrong-intent",
"missing-context", "too-slow", "privacy", "off-topic") and a one-line note.
✅ Good rows get Failure Type "" and an empty note.

## Step 3 — patch each row
For each row, use mcp__claude_ai_Notion__notion-update-page to set:
  Rating = <your rating>
  Failure Type = <your failure type>
  (append the one-line note to the existing "Your Note" field if that property exists)
Only patch rows that are still "🔁 Unreviewed". Do not touch already-rated rows.

## Step 4 — return JSON (LAST line of your output, nothing after it)
{{"total": N, "good": N, "partial": N, "wrong": N, "scored": N,
  "by_source": {{"<source>": {{"good": N, "partial": N, "wrong": N}}}},
  "by_mode":   {{"<mode>":   {{"good": N, "partial": N, "wrong": N}}}},
  "wrong_rows": [{{"conv_id":"...", "failure_type":"...", "note":"..."}}]}}

total = rows seen. scored = rows you patched.
by_source / by_mode = today's rating counts grouped by the row's Source and Mode
(so the nightly DM can show a per-source / per-mode breakdown). Use the row's
actual Source/Mode strings as keys.
wrong_rows = ONLY the ❌ Wrong ones. For each, include ONLY:
  - conv_id      — the Conv ID string
  - failure_type — short slug (e.g. "wrong-intent", "asked-clarifying-question")
  - note         — ONE line, ≤120 chars, NO newlines and NO double-quotes
Do NOT include the free-form Request text in wrong_rows — it can break the JSON line.
The whole return value MUST be a single valid JSON object on one line."""

    result = _run_claude(prompt, timeout=180)
    parsed = _parse_last_json(result, "{")
    if not parsed:
        return {"total": 0, "good": 0, "partial": 0, "wrong": 0, "scored": 0, "minted": 0}

    wrong_rows = parsed.get("wrong_rows") or []
    minted = _mint_failures(wrong_rows)

    return {
        "total":     int(parsed.get("total", 0) or 0),
        "good":      int(parsed.get("good", 0) or 0),
        "partial":   int(parsed.get("partial", 0) or 0),
        "wrong":     int(parsed.get("wrong", 0) or 0),
        "scored":    int(parsed.get("scored", 0) or 0),
        "minted":    minted,
        "by_source": parsed.get("by_source") or {},
        "by_mode":   parsed.get("by_mode") or {},
    }


if __name__ == "__main__":
    # CLI entrypoint for varys-learn.sh: `python3 varys_eval.py judge [YYYY-MM-DD]`
    cmd = sys.argv[1] if len(sys.argv) > 1 else "judge"
    if cmd == "judge":
        arg_date = sys.argv[2] if len(sys.argv) > 2 else None
        print(json.dumps(judge_unreviewed(arg_date)))
    elif cmd == "confidence":
        print(json.dumps(confidence_score()))
    else:
        print(json.dumps({"error": f"unknown command: {cmd}"}))
        sys.exit(1)
