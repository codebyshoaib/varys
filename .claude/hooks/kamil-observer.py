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
        rows = []
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

# Auto-fix is OFF by default after the 2026-06-01 churn incident (observer re-fixed an
# already-fixed file 13× on stale errors + committed unverified edits). The observer now
# ESCALATES by default. To re-enable auto-fix, create ~/.claude/hooks/.observer-autofix
# AND ensure the diagnosis is verified-current. Escalate-only is the safe default.
AUTOFIX_ENABLED = (Path.home()/".claude"/"hooks"/".observer-autofix").exists()
HANDLED = ROOT/".beads"/"observer-handled.jsonl"

def already_handled(anom) -> bool:
    """Dedup against errors we've already escalated, so a lingering log entry in the
    1h Axiom window is not re-acted every run."""
    import hashlib
    sig = hashlib.sha1(f"{anom.get('component')}|{anom.get('error_type')}|{anom.get('context')}".encode()).hexdigest()[:16]
    try:
        if HANDLED.exists():
            for line in HANDLED.read_text().splitlines():
                if line.strip() == sig:
                    return True
        with open(HANDLED, "a") as f:
            f.write(sig + "\n")
    except Exception:
        pass
    return False

def main():
    k.start_trace()
    paused = PAUSED.exists()
    anomalies = query_anomalies()
    k.klog("observer_run", component="observer", anomalies=len(anomalies),
           paused=paused, autofix=AUTOFIX_ENABLED)
    for anom in anomalies:
        if already_handled(anom):
            continue  # stale/duplicate — already escalated, don't re-act
        ctx = f"{anom.get('component')} {anom.get('context')}"
        root_cause = f"{anom.get('error_type')} in {anom.get('component')} ({anom.get('context')})"
        # Escalate-only by default. Auto-fix only if explicitly enabled AND not fenced/paused.
        if AUTOFIX_ENABLED and not paused and not is_fenced(ctx):
            if not auto_fix(anom, root_cause):
                escalate(anom, root_cause, "auto-fix did not confirm FIXED")
        else:
            reason = ("auto-fix disabled (escalate-only default)" if not AUTOFIX_ENABLED
                      else "fenced or paused")
            escalate(anom, root_cause, reason)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try: k.klog_error("observer.main", e, component="observer", severity="FATAL")
        except Exception: pass
