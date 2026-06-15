#!/usr/bin/env python3
"""
varys_health.py — Write health events to Notion Health Log DB.

DB ID: 27e287b7-a3d1-46c6-b5e8-eb0d862d746f
Parent: 🧠 Shoaib's Agent Brain

Usage:
    from varys_health import log_health, log_error, log_healed, log_critique

All writes are async (fire-and-forget via Claude MCP subprocess) so they
never block the main listener thread.
"""

import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from varys_log import klog

HEALTH_DB   = "27e287b7-a3d1-46c6-b5e8-eb0d862d746f"
VARYS_DIR   = Path(__file__).parent.parent.parent
_SESSION_ID = datetime.utcnow().strftime("%Y%m%d-%H%M%S")


def _write_to_notion(event: str, service: str, severity: str, status: str,
                     root_cause: str = "", fix_applied: str = "",
                     error_snippet: str = "", latency_ms: float = None,
                     session_id: str = None):
    """Fire-and-forget: write one entry to Notion Health Log via Claude MCP."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    sid   = session_id or _SESSION_ID

    props = {
        "Event":         event[:200],
        "Service":       service,
        "Severity":      severity,
        "Status":        status,
        "Root Cause":    root_cause[:500] if root_cause else "",
        "Fix Applied":   fix_applied[:500] if fix_applied else "",
        "Error Snippet": error_snippet[:800] if error_snippet else "",
        "Session ID":    sid,
        "date:Date:start": today,
    }
    if latency_ms is not None:
        props["Latency ms"] = round(latency_ms, 1)

    # Build a self-contained Claude prompt that uses Notion MCP to write the entry
    prompt = f"""Use mcp__claude_ai_Notion__notion-create-pages to add ONE page to the Varys Health Log DB.

data_source_id: {HEALTH_DB}

Properties (use exactly these field names):
{json.dumps(props, indent=2)}

Reply only "ok" when done. No explanation."""

    env = os.environ.copy()
    env["VARYS_HEALTH_PROMPT"] = prompt
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'

    subprocess.Popen(
        ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$VARYS_HEALTH_PROMPT"'],
        cwd=str(VARYS_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _async(fn, *args, **kwargs):
    threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


# ── Public API ────────────────────────────────────────────────────────────────

def log_error(service: str, error: str, context: str = "", session_id: str = None):
    """Log a detected error. Status=detected, Severity=critical."""
    klog("health_error", component="varys-health", service=service,
         error=error[:200], ctx=context, severity="critical")
    _async(_write_to_notion,
           event         = f"Error in {service}: {error[:80]}",
           service       = service,
           severity      = "critical",
           status        = "detected",
           error_snippet = error,
           root_cause    = context,
           session_id    = session_id)


def log_healed(service: str, root_cause: str, fix: str, session_id: str = None):
    """Log a successful self-heal. Status=auto-fixed, Severity=healed."""
    klog("health_healed", component="varys-health", service=service,
         root_cause=root_cause[:200], fix=fix[:200], severity="healed")
    _async(_write_to_notion,
           event       = f"Self-healed: {service}",
           service     = service,
           severity    = "healed",
           status      = "auto-fixed",
           root_cause  = root_cause,
           fix_applied = fix,
           session_id  = session_id)


def log_needs_manual(service: str, root_cause: str, attempted: str, session_id: str = None):
    """Log when self-heal couldn't fix it."""
    klog("health_needs_manual", component="varys-health", service=service,
         root_cause=root_cause[:200], attempted=attempted[:200], severity="warning")
    _async(_write_to_notion,
           event       = f"Needs manual fix: {service}",
           service     = service,
           severity    = "warning",
           status      = "needs-manual",
           root_cause  = root_cause,
           fix_applied = attempted,
           session_id  = session_id)


def log_health(event: str, service: str = "other", details: str = "", session_id: str = None):
    """Log a general health/info event."""
    klog("health_info", component="varys-health", service=service,
         summary=event[:200], details=details[:200], severity="info")
    _async(_write_to_notion,
           event      = event,
           service    = service,
           severity   = "info",
           status     = "detected",
           root_cause = details,
           session_id = session_id)


def log_critique(score: int, reason: str, request: str, session_id: str = None):
    """
    Log a self-critique score.
    score: 0–100 (100 = Varys used tools perfectly, 0 = asked unnecessary questions)
    """
    severity = "info" if score >= 70 else "warning" if score >= 40 else "critical"
    _async(_write_to_notion,
           event         = f"Self-critique score: {score}/100",
           service       = "claude-session",
           severity      = severity,
           status        = "detected",
           root_cause    = reason[:300],
           error_snippet = f"Request: {request[:200]}",
           session_id    = session_id)


def log_response_quality(latency_ms: float, mode: str, clarification_asked: bool,
                         request: str, session_id: str = None):
    """Log response quality metrics per conversation."""
    severity = "warning" if clarification_asked else "info"
    event    = f"Response: {mode} mode, {round(latency_ms/1000, 1)}s"
    if clarification_asked:
        event += " — asked clarification ⚠️"
    _async(_write_to_notion,
           event         = event,
           service       = "claude-session",
           severity      = severity,
           status        = "detected",
           root_cause    = f"Mode: {mode} | Clarification asked: {clarification_asked}",
           error_snippet = f"Request: {request[:200]}",
           latency_ms    = latency_ms,
           session_id    = session_id)
