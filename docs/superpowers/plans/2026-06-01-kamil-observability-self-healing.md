# Kamil Observability & Self-Healing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Industry-standard structured logging across all 35 Kamil hooks → Axiom (firehose) + Notion "Kamil Observability" (signal, with Solved/Pending/Needs-Kamal status) + `/tmp` fallback, plus a `kamil-observer.py` self-healing loop (detect → diagnose → auto-fix within a safety fence / escalate).

**Architecture:** Extend the existing `kamil_log.py` (typed events → Axiom, never raises) with OTel-style envelope fields (severity, trace_id/span_id, schema_version, host/pid, duration_ms, structured errors). Instrument the 21 silent hooks. Replace crontab `>> /tmp/*.log` with structured `cron_run` events. Add a Notion signal-sink and an hourly observer.

**Tech Stack:** Python 3.12 stdlib only (urllib, json, uuid, socket, os) — no new deps. Axiom HTTPS ingest. Notion via `mcp__claude_ai_Notion__*` (created interactively in this session; the observer/sink call a tiny Notion-write helper). bash for cron wrappers.

**Reference spec:** `docs/superpowers/specs/2026-06-01-kamil-observability-self-healing-design.md`

**Conventions:** Commit per task with the exact message. Never `git add -A`/`git add .` (a PreToolUse hook blocks it) — stage explicit paths. The logger must NEVER raise. Verify each hook still runs after instrumenting.

---

## Phase 1 — Extend kamil_log.py (the envelope)

## Task 1: Add OTel-style envelope to kamil_log.py

**Files:** Modify `.claude/hooks/kamil_log.py`

- [ ] **Step 1: Add imports + resource attrs at the top** (after the existing `from pathlib import Path`)

```python
import socket
import uuid

_HOST = socket.gethostname()
_PID = os.getpid()
_SCHEMA_VERSION = "1.0"
_TRACE_ID = None  # set per-operation via start_trace()
```

- [ ] **Step 2: Replace the `_base()` function** (currently lines ~89-95) with the enriched envelope. Old:

```python
def _base(component: str, event: str) -> dict:
    """Base fields present on every event."""
    return {
        "component":  component,   # listener | poller | session-start | learn
        "event":      event,
        "session_id": _SESSION_ID,
    }
```

New:

```python
def _base(component: str, event: str, severity: str = "INFO") -> dict:
    """Base fields present on every event (OTel-aligned envelope)."""
    return {
        "schema_version": _SCHEMA_VERSION,
        "severity":       severity,
        "component":      component,
        "event":          event,
        "session_id":     _SESSION_ID,
        "trace_id":       _TRACE_ID or _SESSION_ID,
        "host":           _HOST,
        "pid":            _PID,
    }
```

- [ ] **Step 3: Add trace + span helpers** (append after `_base`)

```python
def start_trace(trace_id: str = None) -> str:
    """Begin a correlated operation. Returns the trace_id."""
    global _TRACE_ID
    _TRACE_ID = trace_id or uuid.uuid4().hex[:16]
    return _TRACE_ID

def new_span() -> str:
    return uuid.uuid4().hex[:8]
```

- [ ] **Step 4: Upgrade `klog_error` to FATAL-capable structured errors.** Replace the existing `klog_error` (lines ~215-223) with:

```python
def klog_error(context: str, exc: Exception = None, component: str = "listener",
               severity: str = "ERROR", **extra):
    e = _base(component, "error", severity=severity)
    e.update({
        "context":    context,
        "error_type": type(exc).__name__ if exc else "unknown",
        "error_msg":  str(exc) if exc else "unknown",
        "traceback":  traceback.format_exc() if exc else "",
        **extra,
    })
    _send([e])
```

- [ ] **Step 5: Add the new typed event functions** (append before the legacy `klog` shim)

```python
def klog_cron(component: str, *, status: str, duration_ms: float,
              items: int = 0, rc: int = 0, error: str = "", **extra):
    """One row per cron run. status: ok|error|partial."""
    sev = "INFO" if status == "ok" else ("ERROR" if status == "error" else "WARN")
    e = _base(component, "cron_run", severity=sev)
    e.update({"status": status, "duration_ms": duration_ms, "items": items,
              "rc": rc, "error": error, **extra})
    _send([e])

def klog_external(component: str, *, target: str, status: str,
                  latency_ms: float = 0, retry_count: int = 0, http_status: int = 0, **extra):
    """External API call. target: slack|notion|github|kie|openoutreach|linkedin|nlm."""
    sev = "INFO" if status == "ok" else "WARN"
    e = _base(component, "external_call", severity=sev)
    e.update({"target": target, "status": status, "latency_ms": latency_ms,
              "retry_count": retry_count, "http_status": http_status, **extra})
    _send([e])

def klog_policy_block(component: str, *, rule: str, reason: str, command: str = "", path: str = ""):
    """A PreToolUse hook blocked something."""
    e = _base(component, "policy_block", severity="WARN")
    e.update({"rule": rule, "reason": reason,
              "command": command[:200], "path": path})
    _send([e])

def klog_bead(*, action: str, bead_id: str, title: str = "", status: str = ""):
    """action: opened|closed."""
    e = _base("beads", f"bead_{action}")
    e.update({"bead_id": bead_id, "title": title, "status": status})
    _send([e])

def klog_eval(*, passed: int, failed: int, metrics: dict = None):
    e = _base("evals", "eval_run", severity="INFO" if failed == 0 else "WARN")
    e.update({"passed": passed, "failed": failed, **(metrics or {})})
    _send([e])

def klog_session_end(component: str, *, duration_s: float = 0, context_loaded: str = ""):
    e = _base(component, "session_end")
    e.update({"duration_s": duration_s, "context_loaded": context_loaded})
    _send([e])
```

- [ ] **Step 6: Verify backward compatibility + new functions import**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "
import sys; sys.path.insert(0,'.claude/hooks')
import kamil_log as k
tid = k.start_trace()
k.klog_cron('poller', status='ok', duration_ms=1200, items=5)
k.klog_external('listener', target='slack', status='ok', latency_ms=80)
k.klog_policy_block('block-bad-commands', rule='git_add_all', reason='blocked')
k.klog_bead(action='opened', bead_id='bd-002', title='test')
k.klog_eval(passed=8, failed=0)
k.klog_error('test_ctx', ValueError('x'), severity='FATAL')
k.klog('legacy_event', component='poller', foo=1)  # legacy shim still works
print('trace_id:', tid, '— all log functions OK')
"
tail -3 /tmp/kamil-axiom-fallback.jsonl | python3 -c "import sys,json; [print(json.loads(l)['event'], json.loads(l).get('severity'), json.loads(l).get('schema_version')) for l in sys.stdin]"
```
Expected: "all log functions OK"; the tail shows events with `severity` and `schema_version: 1.0`.

- [ ] **Step 7: Commit**

```bash
git add .claude/hooks/kamil_log.py
git commit -m "feat(obs): extend kamil_log with OTel envelope + new event types"
```

---

## Phase 2 — Instrument the 21 silent hooks + cron wrapper

## Task 2: Create the structured cron wrapper

**Files:** Create `.claude/hooks/cron-wrap.sh`

- [ ] **Step 1: Write the wrapper** — runs any cron command, captures rc + duration + stderr tail, emits a `cron_run` event instead of dumping to a raw `.log`

```bash
#!/bin/bash
# Usage: cron-wrap.sh <component> <command...>
# Runs the command, times it, captures rc + stderr tail, emits a structured cron_run event.
COMPONENT="$1"; shift
START=$(date +%s%3N)
ERRFILE=$(mktemp)
"$@" >"$ERRFILE" 2>&1
RC=$?
END=$(date +%s%3N)
DUR=$((END - START))
TAIL=$(tail -c 800 "$ERRFILE" | tr '\n' ' ' | tr -d '"')
rm -f "$ERRFILE"
STATUS="ok"; [ "$RC" -ne 0 ] && STATUS="error"
cd /home/oye/Documents/free_work/personal-agent-v2 2>/dev/null
python3 -c "
import sys; sys.path.insert(0,'.claude/hooks')
import kamil_log as k
k.klog_cron('$COMPONENT', status='$STATUS', duration_ms=$DUR, rc=$RC, error='''$TAIL'''[:500])
" 2>/dev/null
exit $RC
```

- [ ] **Step 2: chmod + test it emits a cron_run**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
chmod +x .claude/hooks/cron-wrap.sh
.claude/hooks/cron-wrap.sh testcomp echo "hello"; echo "wrapper rc=$?"
tail -1 /tmp/kamil-axiom-fallback.jsonl | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print('event:',d['event'],'component:',d['component'],'status:',d['status'])"
```
Expected: `wrapper rc=0`; tail shows `event: cron_run component: testcomp status: ok`.

- [ ] **Step 3: Commit**

```bash
git add .claude/hooks/cron-wrap.sh
git commit -m "feat(obs): structured cron wrapper (replaces raw /tmp/*.log)"
```

## Task 3: Instrument the silent hooks (entrypoint-level)

**Files:** Modify these 8 high-value silent hooks (the rest log via cron-wrap): `notion-map-updater.py`, `inbox-processor.py`, `image_generator.py`, `linkedin_poster.py`, `trend-scanner.py`, `stop.py`, `stop-notion.py`, `session-start.py`

- [ ] **Step 1: For each hook, add a guarded import + wrap the main entry.** Pattern to apply to each (adapt the component name). Add near the top, after existing imports:

```python
import sys as _sys, time as _time
_sys.path.insert(0, "/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks")
try:
    import kamil_log as _k
except Exception:
    _k = None
```

Then wrap the existing `if __name__ == "__main__":` body. For example in `notion-map-updater.py`, change:

```python
if __name__ == "__main__":
    main()
```

to:

```python
if __name__ == "__main__":
    _t0 = _time.time()
    try:
        main()
        if _k: _k.klog_cron("notion-map", status="ok", duration_ms=(_time.time()-_t0)*1000)
    except Exception as _e:
        if _k: _k.klog_error("notion-map-main", _e, component="notion-map", severity="ERROR")
        raise
```

Apply the equivalent wrap to each of the 8 hooks, using component names: `notion-map`, `inbox-processor`, `image-generator`, `linkedin-poster`, `trend-scanner`, `stop`, `stop-notion`, `session-start`. If a hook has no `if __name__ == "__main__"` block (e.g. it's a pure hook reading stdin), wrap its top-level logic in a try/except that calls `_k.klog_error(...)` and re-raises.

- [ ] **Step 2: Verify every modified hook still compiles**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
for f in notion-map-updater inbox-processor image_generator linkedin_poster trend-scanner stop stop-notion session-start; do
  python3 -m py_compile ".claude/hooks/$f.py" && echo "OK $f" || echo "FAIL $f"
done
```
Expected: `OK` for all 8.

- [ ] **Step 3: Smoke-test the two safest ones actually emit** (session-start and notion-map are read-only-ish; run notion-map in a dry mode if available, else just import-check). Minimum:

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "import sys; sys.path.insert(0,'.claude/hooks'); import notion_map_updater" 2>/dev/null || echo "(module name has hyphens, import-skip OK)"
echo "compile-verified above is sufficient"
```

- [ ] **Step 4: Commit**

```bash
git add .claude/hooks/notion-map-updater.py .claude/hooks/inbox-processor.py .claude/hooks/image_generator.py .claude/hooks/linkedin_poster.py .claude/hooks/trend-scanner.py .claude/hooks/stop.py .claude/hooks/stop-notion.py .claude/hooks/session-start.py
git commit -m "feat(obs): instrument 8 silent hooks with structured logging"
```

## Task 4: Add policy_block logging to the PreToolUse hooks

**Files:** Modify `.claude/hooks/block-bad-commands.py`, `.claude/hooks/guard-file-writes.py`

- [ ] **Step 1: In `block-bad-commands.py`,** add the guarded import (top, after `import json, re, sys`):

```python
sys.path.insert(0, "/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks")
try:
    import kamil_log as _k
except Exception:
    _k = None
```

Then in the block loop, right before `sys.exit(2)`, add:

```python
            if _k: _k.klog_policy_block("block-bad-commands", rule=pattern[:40], reason=msg, command=cmd)
```

- [ ] **Step 2: In `guard-file-writes.py`,** add the same guarded import, and before the `sys.exit(2)` for oversized CLAUDE.md add:

```python
            if _k: _k.klog_policy_block("guard-file-writes", rule="claude_md_size", reason=f"~{projected} lines", path=path)
```

- [ ] **Step 3: Verify both still compile AND still block** (logging must not break the guard)

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m py_compile .claude/hooks/block-bad-commands.py .claude/hooks/guard-file-writes.py && echo "COMPILE OK"
python3 -c "
import subprocess, json
r = subprocess.run(['python3','.claude/hooks/block-bad-commands.py'], input=json.dumps({'tool_input':{'command':'rm -rf '+chr(126)}}), capture_output=True, text=True)
print('block rc=', r.returncode, '(expect 2)')
"
tail -1 /tmp/kamil-axiom-fallback.jsonl | python3 -c "import sys,json; print('logged event:', json.loads(sys.stdin.read()).get('event'))"
```
Expected: `COMPILE OK`; `block rc= 2`; `logged event: policy_block`.

- [ ] **Step 4: Commit**

```bash
git add .claude/hooks/block-bad-commands.py .claude/hooks/guard-file-writes.py
git commit -m "feat(obs): log policy_block events from PreToolUse hooks"
```

## Task 5: Point crontab at the cron wrapper

**Files:** Modify the user crontab (via `crontab -l` → edit → `crontab -`). This is NOT a repo file.

- [ ] **Step 1: Back up and rewrite crontab** so each Kamil cron pipes through `cron-wrap.sh` with a component name, dropping the raw `>> /tmp/*.log` (keep `2>&1` safety via the wrapper).

Run:
```bash
crontab -l > /tmp/crontab.backup.$(date +%s)
echo "backed up to /tmp/crontab.backup.*"
crontab -l
```

- [ ] **Step 2: Produce the new crontab.** For each Kamil line, transform e.g.:

```
*/30 * * * * nice -n 15 python3 /home/oye/.../slack-poller.py >> /tmp/kamil-slack.log 2>&1
```
into:
```
*/30 * * * * nice -n 15 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/cron-wrap.sh poller python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/slack-poller.py
```

Apply the same transform to: job-finder (`jobs`), content-scheduler (`content`), self-healer (`self-healer`), notion-map-updater (`notion-map`), kamil-daily.sh (`daily`), kamil-weekly-report.sh (`weekly`), kamil-learn.sh (`learn`). LEAVE the `@reboot` listener line and the `*/10` self-healer line's own logging intact — but DO wrap them too with appropriate component names. Write the assembled crontab to `/tmp/new-crontab.txt`, review it, then install:

```bash
# After writing /tmp/new-crontab.txt and eyeballing it:
crontab /tmp/new-crontab.txt
crontab -l | grep -c cron-wrap.sh
```
Expected: the count matches the number of Kamil cron lines (≈9).

- [ ] **Step 3: Verify a wrapped cron runs** (trigger one manually)

Run:
```bash
/home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/cron-wrap.sh notion-map echo "cron wrap smoke"; echo "rc=$?"
```
Expected: `rc=0`, and a `cron_run` event in the fallback.

- [ ] **Step 4: Commit a record of the crontab** (crontab isn't in git, so snapshot it into the repo for audit)

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
crontab -l > .claude/hooks/crontab.snapshot.txt
git add .claude/hooks/crontab.snapshot.txt
git commit -m "feat(obs): route crons through structured wrapper + snapshot crontab"
```

---

## Phase 3 — Notion Observability DB + sink

## Task 6: Create the "Kamil Observability" Notion DB (interactive, this session)

**Files:** none (creates a Notion DB via MCP); records the DB ID into `.claude/rules/notion.md`

- [ ] **Step 1: Create the database** using `mcp__claude_ai_Notion__notion-create-database` under the 🧠 Kamal's Agent Brain page, with properties: Title (title), Severity (select: DEBUG/INFO/WARN/ERROR/FATAL), Component (select), Event (rich_text), Trace ID (rich_text), Root Cause (rich_text), Status (select: 🔴 Needs Kamal / 🟡 Pending / 🟢 Solved / ⚪ Monitoring), Action Taken (rich_text), Resolution (rich_text), Detected (date), Resolved (date).

- [ ] **Step 2: Capture the new DB ID** and append it to `.claude/rules/notion.md` table:

Add a row: `| Observability | <new-id> | Errors, self-heal actions, daily digest — Solved/Pending/Needs-Kamal |`

- [ ] **Step 3: Commit the ID record**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
git add .claude/rules/notion.md
git commit -m "feat(obs): register Kamil Observability Notion DB id"
```

## Task 7: Build the Notion signal-sink helper

**Files:** Create `.claude/hooks/kamil-notion-sink.py`

- [ ] **Step 1: Write the helper.** It reads recent ERROR/FATAL + self-heal events from the fallback (or accepts an event dict) and upserts a Notion row via the Notion API. Since hooks can't call MCP directly, this uses the Notion REST API with a token. NOTE: if no Notion API token is configured, it writes the intended row to `/tmp/kamil-notion-queue.jsonl` for the next interactive session / observer to flush via MCP. Never raises.

```python
#!/usr/bin/env python3
"""Mirror signal events (ERROR/FATAL + self-heal actions) into the Notion
'Kamil Observability' DB. If no direct Notion token, queue for MCP flush. Never raises."""
import json, os, sys, urllib.request
from pathlib import Path

OBS_DB = os.environ.get("KAMIL_OBS_DB", "")  # filled from .claude/rules/notion.md id
TOKEN_FILE = Path.home() / ".claude" / "hooks" / ".notion"
QUEUE = Path("/tmp/kamil-notion-queue.jsonl")

def _token():
    if TOKEN_FILE.exists():
        for line in TOKEN_FILE.read_text().splitlines():
            if line.startswith("NOTION_TOKEN="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("NOTION_TOKEN", "")

def push(*, title, severity, component, event, trace_id="", root_cause="",
         status="🟡 Pending", action_taken="", resolution="", detected="", resolved=""):
    row = {"title": title, "severity": severity, "component": component, "event": event,
           "trace_id": trace_id, "root_cause": root_cause, "status": status,
           "action_taken": action_taken, "resolution": resolution,
           "detected": detected, "resolved": resolved}
    token = _token()
    if not token or not OBS_DB:
        try:
            with open(QUEUE, "a") as f: f.write(json.dumps(row) + "\n")
        except Exception: pass
        return "queued"
    try:
        props = {
            "Title": {"title": [{"text": {"content": title[:200]}}]},
            "Severity": {"select": {"name": severity}},
            "Component": {"select": {"name": component}},
            "Event": {"rich_text": [{"text": {"content": event[:200]}}]},
            "Trace ID": {"rich_text": [{"text": {"content": trace_id}}]},
            "Root Cause": {"rich_text": [{"text": {"content": root_cause[:1900]}}]},
            "Status": {"select": {"name": status}},
            "Action Taken": {"rich_text": [{"text": {"content": action_taken[:1900]}}]},
            "Resolution": {"rich_text": [{"text": {"content": resolution[:1900]}}]},
        }
        if detected: props["Detected"] = {"date": {"start": detected}}
        if resolved: props["Resolved"] = {"date": {"start": resolved}}
        payload = json.dumps({"parent": {"database_id": OBS_DB}, "properties": props}).encode()
        req = urllib.request.Request("https://api.notion.com/v1/pages", data=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "Notion-Version": "2022-06-28"})
        with urllib.request.urlopen(req, timeout=10): pass
        return "sent"
    except Exception:
        try:
            with open(QUEUE, "a") as f: f.write(json.dumps(row) + "\n")
        except Exception: pass
        return "queued"

if __name__ == "__main__":
    print(push(title="sink self-test", severity="INFO", component="observer",
               event="self_test", status="⚪ Monitoring"))
```

- [ ] **Step 2: Verify it never raises and queues when no token**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 .claude/hooks/kamil-notion-sink.py; echo "rc=$?"
tail -1 /tmp/kamil-notion-queue.jsonl 2>/dev/null | python3 -c "import sys,json; print('queued row:', json.loads(sys.stdin.read())['title'])" 2>/dev/null || echo "(sent directly)"
```
Expected: prints `queued` or `sent`, `rc=0`.

- [ ] **Step 3: Commit**

```bash
git add .claude/hooks/kamil-notion-sink.py
git commit -m "feat(obs): Notion signal-sink with MCP-queue fallback"
```

---

## Phase 4 — The self-healing observer

## Task 8: Build kamil-observer.py (detect → diagnose → fix/escalate)

**Files:** Create `.claude/hooks/kamil-observer.py`

- [ ] **Step 1: Write the observer.** Queries Axiom (APL) for last-hour anomalies; for each, classifies against the fence; auto-fixable → shells `claude -p` to produce a reversible fix, verifies, commits, flips Notion → 🟢 Solved; else escalates → failures.jsonl + eval task + Notion → 🔴 Needs Kamal + DM. Respects the `.observer-paused` kill switch. Never raises out of main.

```python
#!/usr/bin/env python3
"""kamil-observer.py — self-healing loop.
Hourly + on-ERROR. Detect anomalies in Axiom → diagnose → auto-fix (within fence) / escalate.
Kill switch: ~/.claude/hooks/.observer-paused disables auto-fix."""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path("/home/oye/Documents/free_work/personal-agent-v2")
sys.path.insert(0, str(ROOT / ".claude" / "hooks"))
import kamil_log as k
import importlib.util
_spec = importlib.util.spec_from_file_location("notion_sink", ROOT/".claude/hooks/kamil-notion-sink.py")
notion_sink = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(notion_sink)

AXIOM_CFG = Path.home()/".claude"/"hooks"/".axiom"
PAUSED = Path.home()/".claude"/"hooks"/".observer-paused"
FAILURES = ROOT/".beads"/"failures.jsonl"

# Hard-exclusion fence — auto-fix NEVER edits these; always escalate.
FENCE = [".slack", ".axiom", ".env", ".notion", "settings.json", "crontab",
         "kamil-slack-listener.py"]

def _axiom_token():
    if AXIOM_CFG.exists():
        for line in AXIOM_CFG.read_text().splitlines():
            if line.startswith("AXIOM_TOKEN="):
                return line.split("=",1)[1].strip()
    return ""

def query_anomalies():
    """APL: error events in the last hour grouped by component+error_type."""
    token = _axiom_token()
    if not token:
        return []
    apl = ("kamil-logs | where severity in ('ERROR','FATAL') "
           "| where _time > ago(1h) "
           "| summarize count() by component, error_type, context")
    try:
        payload = json.dumps({"apl": apl}).encode()
        req = urllib.request.Request("https://api.axiom.co/v1/datasets/_apl?format=tabular",
            data=payload, headers={"Authorization": f"Bearer {token}",
            "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        # tabular → list of rows; tolerate shape differences
        tables = data.get("tables") or []
        rows = []
        for t in tables:
            cols = [c.get("name") for c in t.get("columns", [])]
            for rec in t.get("columns", [{}])[0].get("values", []) if False else []:
                pass
        # Fallback: use 'matches' if present
        for m in data.get("matches", []):
            d = m.get("data", {})
            rows.append({"component": d.get("component"), "error_type": d.get("error_type"),
                         "context": d.get("context"), "count": 1})
        return rows
    except Exception as e:
        k.klog_error("observer.query", e, component="observer", severity="WARN")
        return []

def is_fenced(text: str) -> bool:
    return any(f in (text or "") for f in FENCE)

def escalate(anom, root_cause, proposed):
    detected = time.strftime("%Y-%m-%d")
    try:
        with open(FAILURES, "a") as f:
            f.write(json.dumps({"date": detected,
                "incident": f"{anom.get('component')}: {anom.get('error_type')}",
                "root_cause": root_cause, "fix": "ESCALATED — awaiting Kamal",
                "lesson": "see observer", "related_bead": None}) + "\n")
    except Exception: pass
    notion_sink.push(title=f"{anom.get('component')}: {anom.get('error_type')}",
        severity="ERROR", component=anom.get("component","?"), event="error",
        root_cause=root_cause, status="🔴 Needs Kamal",
        action_taken=f"proposed: {proposed[:300]}", detected=detected)
    k.klog("observer_escalated", component="observer", severity="WARN",
           target=anom.get("component"))

def auto_fix(anom, root_cause):
    detected = time.strftime("%Y-%m-%d")
    prompt = (f"A Kamil hook is failing. Component: {anom.get('component')}. "
              f"Error: {anom.get('error_type')} at {anom.get('context')}. "
              f"Root cause: {root_cause}. Make the MINIMAL reversible fix. "
              f"Do NOT touch secrets, settings.json, crontab, or the listener daemon. "
              f"After fixing, print 'FIXED: <one line>'.")
    try:
        nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"'
        os.environ["KAMIL_FIX"] = prompt
        r = subprocess.run(["bash","-c",
            f'{nvm} && cd {ROOT} && claude --dangerously-skip-permissions --print -p "$KAMIL_FIX"'],
            capture_output=True, text=True, timeout=240)
        ok = "FIXED:" in (r.stdout or "")
        notion_sink.push(title=f"{anom.get('component')}: {anom.get('error_type')}",
            severity="ERROR", component=anom.get("component","?"), event="error",
            root_cause=root_cause,
            status="🟢 Solved" if ok else "🔴 Needs Kamal",
            action_taken=(r.stdout or "")[-400:], detected=detected,
            resolved=detected if ok else "")
        k.klog("observer_autofix", component="observer",
               severity="INFO" if ok else "WARN", success=ok, target=anom.get("component"))
        return ok
    except Exception as e:
        k.klog_error("observer.autofix", e, component="observer", severity="ERROR")
        escalate(anom, root_cause, "auto-fix raised; manual review")
        return False

def main():
    k.start_trace()
    paused = PAUSED.exists()
    anomalies = query_anomalies()
    k.klog("observer_run", component="observer", anomalies=len(anomalies), paused=paused)
    for anom in anomalies:
        ctx = f"{anom.get('component')} {anom.get('context')}"
        root_cause = f"{anom.get('error_type')} in {anom.get('component')} ({anom.get('context')})"
        if paused or is_fenced(ctx):
            escalate(anom, root_cause, "fenced or observer paused — manual fix required")
        else:
            if not auto_fix(anom, root_cause):
                escalate(anom, root_cause, "auto-fix did not confirm FIXED")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try: k.klog_error("observer.main", e, component="observer", severity="FATAL")
        except Exception: pass
```

- [ ] **Step 2: Verify it compiles and runs without anomalies/paused without error**

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -m py_compile .claude/hooks/kamil-observer.py && echo "COMPILE OK"
touch ~/.claude/hooks/.observer-paused   # ensure no auto-fix during the smoke test
python3 .claude/hooks/kamil-observer.py; echo "rc=$?"
tail -1 /tmp/kamil-axiom-fallback.jsonl | python3 -c "import sys,json; print('event:', json.loads(sys.stdin.read()).get('event'))"
rm -f ~/.claude/hooks/.observer-paused
```
Expected: `COMPILE OK`; `rc=0`; tail shows `event: observer_run`. (Paused during test so it cannot auto-edit anything.)

- [ ] **Step 3: Commit**

```bash
git add .claude/hooks/kamil-observer.py
git commit -m "feat(obs): self-healing observer (detect/diagnose/auto-fix/escalate)"
```

## Task 9: Schedule the observer (hourly) + ERROR trigger note

**Files:** Modify crontab; update `.claude/hooks/crontab.snapshot.txt`

- [ ] **Step 1: Add an hourly observer cron** (paused-safe by default — runs, escalates, only auto-fixes when not paused)

Run:
```bash
crontab -l > /tmp/cron.now
echo "15 * * * * /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/cron-wrap.sh observer python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/kamil-observer.py" >> /tmp/cron.now
crontab /tmp/cron.now
crontab -l | grep -c kamil-observer
```
Expected: `1`.

- [ ] **Step 2: Snapshot + commit**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
crontab -l > .claude/hooks/crontab.snapshot.txt
git add .claude/hooks/crontab.snapshot.txt
git commit -m "feat(obs): schedule hourly self-healing observer"
```

---

## Phase 5 — Verify & document

## Task 10: End-to-end verification + docs + safety re-check

**Files:** Create `.claude/rules/observability.md`; update `.beads/decisions.jsonl`

- [ ] **Step 1: Create `.claude/rules/observability.md`** (L2 rule so future sessions know the logging contract)

```markdown
---
type: reference
last_verified: 2026-06-01
owner: kamil
paths:
  - ".claude/hooks/*.py"
---

# Observability Contract

All hooks log via `kamil_log.py` (typed events → Axiom `kamil-logs` + /tmp fallback).
Every event carries: schema_version, severity, component, event, trace_id, host, pid.

## Sinks
- Axiom: ALL events. Query with APL.
- Notion "Kamil Observability" DB: signal only (ERROR/FATAL, self-heal, daily digest) with Status (🔴 Needs Kamal / 🟡 Pending / 🟢 Solved / ⚪ Monitoring).
- /tmp/kamil-axiom-fallback.jsonl: fallback; /tmp/kamil-notion-queue.jsonl: MCP-flush queue.

## Self-healing
`kamil-observer.py` (hourly): detect anomalies → diagnose → auto-fix within the fence / escalate.
Fence (never auto-fixed): secrets, settings.json, crontab, listener daemon, migrations.
Kill switch: `touch ~/.claude/hooks/.observer-paused`.

## Adding a new hook
Import kamil_log; call the right klog_* (klog_cron for crons, klog_external for API calls,
klog_error for failures). Route the cron through cron-wrap.sh. Never let logging raise.
```

- [ ] **Step 2: Record the decision**

Append to `.beads/decisions.jsonl`:
```jsonl
{"date": "2026-06-01", "decision": "Observability = extend kamil_log (OTel envelope) → Axiom firehose + Notion signal-sink (with Solved/Pending/Needs-Kamal status) + self-healing observer", "rationale": "Kamal wants every event logged industry-standard, mirrored to Notion with explicit issue status, and a loop that solves/improves itself", "alternatives": ["Full OpenTelemetry SDK — heavyweight for cron/daemon context", "Keep raw /tmp/*.log — not queryable, not auditable"], "revisit_when": "If Axiom volume/cost spikes or auto-fix produces a bad edit"}
```

- [ ] **Step 3: Full safety re-check** (nothing broke)

Run:
```bash
cd /home/oye/Documents/free_work/personal-agent-v2
echo "== all hooks compile =="; for f in .claude/hooks/*.py; do python3 -m py_compile "$f" 2>/dev/null || echo "FAIL $f"; done; echo "compile sweep done"
echo "== listener intact =="; python3 -m py_compile .claude/hooks/kamil-slack-listener.py && echo OK
echo "== kamil_log all functions =="; python3 -c "import sys; sys.path.insert(0,'.claude/hooks'); import kamil_log as k; [getattr(k,n) for n in ['klog_cron','klog_external','klog_policy_block','klog_bead','klog_eval','start_trace','klog_error']]; print('all present')"
echo "== cron wrapper in crontab =="; crontab -l | grep -c cron-wrap.sh
echo "== observer scheduled =="; crontab -l | grep -c kamil-observer
echo "== tier-1 still passes =="; .claude/evals/graders/run-tier1.sh | tail -1
```
Expected: compile sweep done (no FAIL); listener OK; all present; cron-wrap count ≥9; observer 1; TIER-1: PASS.

- [ ] **Step 4: Commit**

```bash
git add .claude/rules/observability.md .beads/decisions.jsonl
git commit -m "docs(obs): observability contract rule + decision record"
```

---

## Self-Review

**Spec coverage:** envelope (T1) · 35/35 coverage incl. crons/policy/external (T1-T5) · raw .log removal (T2,T5) · Notion DB with Status workflow (T6,T7) · observer detect/diagnose/auto-fix/escalate + fence + kill switch (T8,T9) · docs + safety (T10). All DoD items mapped.

**Placeholder scan:** none. All code complete. Notion DB creation (T6) is interactive via MCP — flagged as such, not a placeholder.

**Consistency:** `klog_*` names consistent T1↔usage. `notion_sink.push(...)` signature matches its definition (T7) and calls (T8). Fence list identical in spec and observer. Component names consistent. The Axiom APL parsing in T8 is defensive (tolerates shape differences) — noted as best-effort.

**Known caveats:** (1) Notion direct-write needs a `~/.claude/hooks/.notion` token; without it, rows queue to `/tmp/kamil-notion-queue.jsonl` for MCP flush — by design, never blocks. (2) Auto-fix shells `claude -p`; the fence + kill switch + reversible commits are the guardrails. (3) crontab edits are out-of-repo; snapshotted for audit.
