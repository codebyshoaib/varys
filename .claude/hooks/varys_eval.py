"""
varys_eval.py — Eval harness sync layer (direct Notion HTTP).

After every conversation:
1. log_to_eval() creates a row in the Notion Eval Log DB with Score UNSET (= unjudged).
2. judge_unreviewed() (nightly) queries rows with empty Score, has one claude -p pass
   rate the batch (0-100 + a one-line note per page_id), then HTTP-PATCHes each row:
   Score=<n>, Pass=(score>=70), Notes appended with the judge note.
3. Pass=false rows are minted into .beads/failures.jsonl (deduped by Notion page_id)
   to fuel varys-evolution-agent.py.
4. confidence_score() reports pass_pct / avg_score over all scored rows.

All DB reads/writes go through varys_notion.notion_request() (the mandated rate-limited
Notion HTTP wrapper — orchestrator Hard Rule #3). Only the rating *decision* is an LLM
task (claude -p); the Notion writes are plain HTTP.

Eval Log DB schema (the ONLY fields that exist):
  Name (title) · Task (text) · Agent (text) · Date (date) ·
  Pass (checkbox) · Score (number) · Notes (text)
"""

import json
import os
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from varys_notion import notion_request
try:
    from agent_config import cfg as _agent_cfg
except Exception:  # agent_config not importable in some test contexts
    def _agent_cfg(key, default=None):
        return os.environ.get(key) or default

VARYS_DIR     = Path(__file__).parent.parent.parent
# Real Eval Log DB (verified live). Config key first, then the verified literal.
EVAL_DB_ID    = _agent_cfg("NOTION_EVAL_LOG_DB_ID", "38390224-8f3d-81dc-894c-e17a94549101")
EVAL_LOG_FILE = Path("/tmp/varys-eval-pending.jsonl")  # local buffer before Notion write
FAILURES_FILE = VARYS_DIR / ".beads" / "failures.jsonl"

NOTION_CFG    = Path.home() / ".claude" / "hooks" / ".notion"
NOTION_VERSION = "2022-06-28"

PASS_THRESHOLD = 70          # score >= 70 -> Pass
_NOTE_MAX = 120
_TASK_MAX = 2000
_NOTES_MAX = 2000


# ── Config / HTTP plumbing ──────────────────────────────────────────────────

def _notion_api_key() -> str:
    """Resolve the Notion API key from .notion file, agent_config, then env."""
    if NOTION_CFG.exists():
        for line in NOTION_CFG.read_text().splitlines():
            line = line.strip()
            if line.startswith("NOTION_API_KEY") and "=" in line:
                return line.split("=", 1)[1].strip()
    return _agent_cfg("NOTION_API_KEY", "") or ""


def _notion_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


# ── Pure builders (unit-testable, no network) ────────────────────────────────

def _score_to_pass(score) -> bool:
    """score >= PASS_THRESHOLD -> True. None / non-numeric -> False."""
    try:
        return float(score) >= PASS_THRESHOLD
    except (TypeError, ValueError):
        return False


def _row_to_props(sender_name: str, request: str, reply: str,
                  source: str, mode: str, today: str) -> dict:
    """
    Build the Notion `properties` object for a new Eval Log row.
    Maps ONLY to the real schema. Score and Pass are deliberately left UNSET
    (absent) so the row reads as unjudged.
    """
    title = f"{sender_name}: {request[:60]}"
    agent = f"{source}/{mode}" if mode else (source or "")
    return {
        "Name":  {"title": [{"text": {"content": title}}]},
        "Task":  {"rich_text": [{"text": {"content": (request or "")[:_TASK_MAX]}}]},
        "Agent": {"rich_text": [{"text": {"content": agent[:200]}}]},
        "Notes": {"rich_text": [{"text": {"content": (reply or "")[:_NOTES_MAX]}}]},
        "Date":  {"date": {"start": today}},
    }


def _build_unjudged_query(target_date: str = None) -> dict:
    """
    Build the POST body for `/v1/databases/{id}/query` enumerating UNJUDGED rows
    (Score is empty). Optionally also constrained to Date == target_date.
    This is a proper DB query that ENUMERATES rows — not a full-text search.
    """
    score_empty = {"property": "Score", "number": {"is_empty": True}}
    if target_date:
        flt = {"and": [score_empty,
                       {"property": "Date", "date": {"equals": target_date}}]}
    else:
        flt = score_empty
    return {"filter": flt, "page_size": 100}


def _build_scored_query() -> dict:
    """POST body enumerating rows that already HAVE a Score (for confidence_score)."""
    return {"filter": {"property": "Score", "number": {"is_not_empty": True}},
            "page_size": 100}


def _build_low_query(target_date: str = None) -> dict:
    """POST body enumerating judged-but-failing rows (Pass = false) for the propose stage."""
    pass_false = {"property": "Pass", "checkbox": {"equals": False}}
    scored     = {"property": "Score", "number": {"is_not_empty": True}}
    conds = [pass_false, scored]
    if target_date:
        conds.append({"property": "Date", "date": {"equals": target_date}})
    return {"filter": {"and": conds}, "page_size": 100}


def _build_patch_props(score, note: str, existing_notes: str) -> dict:
    """
    Build the `properties` object for PATCH /v1/pages/{id}: set Score, Pass, and
    append the judge note to existing Notes. Pure — given inputs, deterministic.
    """
    notes = existing_notes or ""
    clean = _clean_note(note)
    if clean:
        notes = (f"{notes} | judge: {clean}" if notes else f"judge: {clean}")
    props = {
        "Score": {"number": int(score)},
        "Pass":  {"checkbox": _score_to_pass(score)},
    }
    if clean:
        props["Notes"] = {"rich_text": [{"text": {"content": notes[:_NOTES_MAX]}}]}
    return props


def _read_text_prop(prop: dict) -> str:
    """Extract plain text from a Notion title or rich_text property value."""
    if not isinstance(prop, dict):
        return ""
    parts = prop.get("title") or prop.get("rich_text") or []
    return "".join(p.get("plain_text", "") or
                   (p.get("text") or {}).get("content", "") for p in parts)


def _props_to_row(page: dict) -> dict:
    """
    Reduce a Notion page object to the fields the judge / propose stages need.
    `page_id` is the stable dedupe key (there is no Conv ID property anymore).
    """
    props = page.get("properties", {})
    score_prop = props.get("Score", {}) or {}
    pass_prop  = props.get("Pass", {}) or {}
    return {
        "page_id": page.get("id", ""),
        "name":    _read_text_prop(props.get("Name", {})),
        "task":    _read_text_prop(props.get("Task", {})),
        "agent":   _read_text_prop(props.get("Agent", {})),
        "notes":   _read_text_prop(props.get("Notes", {})),
        "score":   score_prop.get("number"),
        "pass":    bool(pass_prop.get("checkbox")),
    }


def _clean_note(raw: str) -> str:
    """
    Sanitise a judge-supplied note so it can never break a single JSON line:
    collapse all whitespace (incl. newlines) to single spaces and cap length.
    """
    note = " ".join((raw or "").split())  # collapses \n, \t, runs of spaces
    return note[:_NOTE_MAX]


# ── HTTP helpers (thin wrappers around notion_request) ───────────────────────

def _query_rows(api_key: str, body: dict) -> list:
    """Run one DB query, following pagination, return the list of page objects."""
    rows = []
    payload = dict(body)
    while True:
        req = urllib.request.Request(
            f"https://api.notion.com/v1/databases/{EVAL_DB_ID}/query",
            data=json.dumps(payload).encode(),
            headers=_notion_headers(api_key),
            method="POST",
        )
        _, body_bytes = notion_request(req)
        result = json.loads(body_bytes)
        rows.extend(result.get("results", []))
        if not result.get("has_more"):
            break
        payload["start_cursor"] = result.get("next_cursor")
    return rows


def _create_page(api_key: str, props: dict):
    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=json.dumps({"parent": {"database_id": EVAL_DB_ID},
                         "properties": props}).encode(),
        headers=_notion_headers(api_key),
        method="POST",
    )
    return notion_request(req)


def _patch_page(api_key: str, page_id: str, props: dict):
    req = urllib.request.Request(
        f"https://api.notion.com/v1/pages/{page_id}",
        data=json.dumps({"properties": props}).encode(),
        headers=_notion_headers(api_key),
        method="PATCH",
    )
    return notion_request(req)


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


# ── Write path (per conversation) ────────────────────────────────────────────

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
    Write a conversation row to the Eval Log DB (Score unset = unjudged).
    Runs in a background thread — never blocks the reply. Signature is unchanged
    so the listener call site does not need to change.
    """
    threading.Thread(
        target=_write_eval_entry,
        args=(conv_id, sender_name, request, reply, mode, source, latency_s),
        daemon=True,
    ).start()


def _write_eval_entry(conv_id, sender_name, request, reply, mode, source, latency_s):
    today = datetime.now().strftime("%Y-%m-%d")

    # Buffer locally first (instant, survives a Notion outage).
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

    api_key = _notion_api_key()
    if not api_key:
        return
    try:
        props = _row_to_props(sender_name, request, reply, source, mode, today)
        _create_page(api_key, props)
    except Exception:
        # Best-effort; the local buffer already holds the row.
        pass


# ── Failure minting ──────────────────────────────────────────────────────────

def _existing_failure_keys() -> set:
    """page_ids (and legacy conv_ids) already minted into failures.jsonl."""
    seen = set()
    if not FAILURES_FILE.exists():
        return seen
    try:
        for line in FAILURES_FILE.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            for k in ("page_id", "conv_id"):
                v = e.get(k)
                if v:
                    seen.add(v)
    except Exception:
        pass
    return seen


def _mint_failures(wrong_rows: list) -> int:
    """
    Append one failures.jsonl line per failing row, deduped by Notion page_id.

    Each entry carries a `ts` (ISO) so varys-evolution-agent's counter sees it.
    The minted entry depends ONLY on structured, sanitised fields (page_id,
    failure_type, capped note) — never on free-form task text, which could carry
    newlines/quotes that corrupt the JSON line. Returns the count of new entries.
    """
    if not wrong_rows:
        return 0
    seen  = _existing_failure_keys()
    now   = datetime.utcnow().isoformat()
    today = datetime.now().strftime("%Y-%m-%d")
    minted = 0
    lines = []
    for row in wrong_rows:
        page_id = (row.get("page_id") or "").strip()
        if not page_id or page_id in seen:
            continue
        seen.add(page_id)  # guard against dupes within this same batch too
        failure_type = (row.get("failure_type") or "unclassified").strip() or "unclassified"
        note = _clean_note(row.get("note"))
        entry = {
            "ts": now,
            "date": today,
            "incident": f"Eval {page_id} failed (Pass=false): {note}".rstrip(": ")
                        if note else f"Eval {page_id} failed (Pass=false)",
            "root_cause": failure_type,
            "lesson": note or "Scored < 70 by nightly auto-judge; review conversation.",
            "source": "auto-judge",
            "page_id": page_id,
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


# ── Judge (nightly) ──────────────────────────────────────────────────────────

_JUDGE_RUBRIC = """\
Rate each conversation on a 0-100 score using this rubric:
  100 — answered with tools, no needless clarification, useful/actionable reply.
  70  — good, complete answer the user could act on.
  30  — incomplete, hedged/slow, or asked a clarifying question a tool could answer.
  0   — wrong answer, had to be corrected, asked the user to do what a tool does,
        or did not address the request.
Also give a short failure_type slug (e.g. "wrong-intent", "asked-clarifying-question",
"missing-context", "too-slow", "off-topic") and a one-line note (<=120 chars, NO
newlines, NO double-quotes). For a clearly good answer use failure_type "" and an
empty note."""


def _build_judge_prompt(rows: list) -> str:
    """
    Build the claude -p prompt: rate a batch of rows, return JSON keyed by page_id.
    The model does NOT touch Notion — it only returns scores; we PATCH via HTTP.
    """
    payload = [
        {"page_id": r["page_id"], "task": (r.get("task") or "")[:600],
         "reply": (r.get("notes") or "")[:600], "agent": r.get("agent", "")}
        for r in rows
    ]
    return f"""You are Varys, acting as a strict eval judge. Rate these conversations.

{_JUDGE_RUBRIC}

Here are the rows (JSON). Each has page_id, task (the request), reply (Varys's answer),
and agent (source/mode):
{json.dumps(payload, ensure_ascii=False)}

Return ONLY one JSON object on the LAST line of your output, keyed by page_id:
{{"<page_id>": {{"score": <0-100>, "failure_type": "<slug or empty>", "note": "<one line>"}}, ...}}
Score every page_id you were given. Nothing after the JSON line."""


def judge_unreviewed(date: str = None) -> dict:
    """
    Auto-rate every unjudged row (empty Score) in the Eval Log DB with an LLM judge.

    HTTP-query unjudged rows -> ONE claude -p pass returns scores keyed by page_id
    -> HTTP-PATCH each row (Score, Pass=score>=70, Notes appended). Idempotent: only
    rows with an empty Score are queried/touched. Rows that end up Pass=false are
    minted into failures.jsonl (deduped by page_id).

    Returns {total, judged, passed, failed, avg_score, by_agent, minted}.
    """
    target_date = date or datetime.now().strftime("%Y-%m-%d")
    api_key = _notion_api_key()
    empty = {"total": 0, "judged": 0, "passed": 0, "failed": 0,
             "avg_score": 0, "by_agent": {}, "minted": 0}
    if not api_key:
        return empty

    try:
        pages = _query_rows(api_key, _build_unjudged_query(target_date))
    except Exception:
        return empty

    rows = [_props_to_row(p) for p in pages]
    rows = [r for r in rows if r.get("page_id")]
    if not rows:
        return empty

    result = _run_claude(_build_judge_prompt(rows), timeout=180)
    ratings = _parse_last_json(result, "{") or {}
    if not isinstance(ratings, dict) or not ratings:
        return {**empty, "total": len(rows)}

    judged = passed = failed = 0
    score_sum = 0
    by_agent: dict = {}
    wrong_rows: list = []

    for row in rows:
        page_id = row["page_id"]
        rating = ratings.get(page_id)
        if not isinstance(rating, dict) or rating.get("score") is None:
            continue
        try:
            score = int(rating.get("score"))
        except (TypeError, ValueError):
            continue
        score = max(0, min(100, score))
        note = rating.get("note") or ""
        failure_type = (rating.get("failure_type") or "").strip()
        is_pass = _score_to_pass(score)

        try:
            _patch_page(api_key, page_id,
                        _build_patch_props(score, note, row.get("notes", "")))
        except Exception:
            continue  # leave it unjudged; retried next run

        judged += 1
        score_sum += score
        agent = row.get("agent") or "unknown"
        bucket = by_agent.setdefault(agent, {"passed": 0, "failed": 0, "scored": 0})
        bucket["scored"] += 1
        if is_pass:
            passed += 1
            bucket["passed"] += 1
        else:
            failed += 1
            bucket["failed"] += 1
            wrong_rows.append({"page_id": page_id,
                               "failure_type": failure_type or "unclassified",
                               "note": note})

    minted = _mint_failures(wrong_rows)
    avg_score = round(score_sum / judged) if judged else 0

    return {
        "total":     len(rows),
        "judged":    judged,
        "passed":    passed,
        "failed":    failed,
        "avg_score": avg_score,
        "by_agent":  by_agent,
        "minted":    minted,
    }


# ── Confidence ───────────────────────────────────────────────────────────────

def confidence_score() -> dict:
    """
    Confidence over ALL scored rows in the Eval Log DB.
    Returns {total, scored, passed, failed, pass_pct, avg_score}.
    (total == scored here — we only enumerate rows that have a Score.)
    """
    empty = {"total": 0, "scored": 0, "passed": 0, "failed": 0,
             "pass_pct": 0, "avg_score": 0}
    api_key = _notion_api_key()
    if not api_key:
        return empty
    try:
        pages = _query_rows(api_key, _build_scored_query())
    except Exception:
        return empty

    scored = passed = failed = 0
    score_sum = 0
    for p in pages:
        row = _props_to_row(p)
        if row.get("score") is None:
            continue
        scored += 1
        score_sum += float(row["score"])
        if _score_to_pass(row["score"]):
            passed += 1
        else:
            failed += 1

    pass_pct  = round(passed / scored * 100) if scored else 0
    avg_score = round(score_sum / scored) if scored else 0
    return {"total": scored, "scored": scored, "passed": passed,
            "failed": failed, "pass_pct": pass_pct, "avg_score": avg_score}


# ── Propose-stage helper (consumed by varys-learn.sh) ────────────────────────

def low_rows(date: str = None) -> list:
    """
    Return judged-but-failing rows (Pass=false) for today (or all). Used by the
    nightly propose stage so it does not re-query Notion from a claude -p subprocess.
    Each row: {page_id, name, task, agent, notes, score}.
    """
    api_key = _notion_api_key()
    if not api_key:
        return []
    try:
        pages = _query_rows(api_key, _build_low_query(date))
    except Exception:
        return []
    return [_props_to_row(p) for p in pages]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "judge"
    if cmd == "judge":
        arg_date = sys.argv[2] if len(sys.argv) > 2 else None
        print(json.dumps(judge_unreviewed(arg_date)))
    elif cmd == "confidence":
        print(json.dumps(confidence_score()))
    elif cmd == "low":
        arg_date = sys.argv[2] if len(sys.argv) > 2 else None
        print(json.dumps(low_rows(arg_date)))
    else:
        print(json.dumps({"error": f"unknown command: {cmd}"}))
        sys.exit(1)
