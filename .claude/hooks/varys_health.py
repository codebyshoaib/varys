#!/usr/bin/env python3
"""
varys_health.py — Log health events locally via varys_log.

Previously wrote to Notion Health Log DB via Claude MCP subprocess.
Now local-only: all events go to the local telemetry log via klog.
The public API (log_error, log_healed, log_critique, log_response_quality,
log_health) is unchanged — callers require no updates.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from varys_log import klog

_SESSION_ID = datetime.utcnow().strftime("%Y%m%d-%H%M%S")


# ── Public API ────────────────────────────────────────────────────────────────

def log_error(service: str, error: str, context: str = "", session_id: str = None):
    """Log a detected error. Severity=critical."""
    klog("health_error", component="varys-health", service=service,
         error=error[:200], ctx=context, severity="critical",
         session_id=session_id or _SESSION_ID)


def log_healed(service: str, root_cause: str, fix: str, session_id: str = None):
    """Log a successful self-heal. Severity=healed."""
    klog("health_healed", component="varys-health", service=service,
         root_cause=root_cause[:200], fix=fix[:200], severity="healed",
         session_id=session_id or _SESSION_ID)


def log_needs_manual(service: str, root_cause: str, attempted: str, session_id: str = None):
    """Log when self-heal couldn't fix it."""
    klog("health_needs_manual", component="varys-health", service=service,
         root_cause=root_cause[:200], attempted=attempted[:200], severity="warning",
         session_id=session_id or _SESSION_ID)


def log_health(event: str, service: str = "other", details: str = "", session_id: str = None):
    """Log a general health/info event."""
    klog("health_info", component="varys-health", service=service,
         summary=event[:200], details=details[:200], severity="info",
         session_id=session_id or _SESSION_ID)


def log_critique(score: int, reason: str, request: str, session_id: str = None):
    """
    Log a self-critique score.
    score: 0–100 (100 = Varys used tools perfectly, 0 = asked unnecessary questions)
    """
    severity = "info" if score >= 70 else "warning" if score >= 40 else "critical"
    klog("health_critique", component="varys-health", service="claude-session",
         score=score, reason=reason[:300], request=request[:200],
         severity=severity, session_id=session_id or _SESSION_ID)


def log_response_quality(latency_ms: float, mode: str, clarification_asked: bool,
                         request: str, session_id: str = None):
    """Log response quality metrics per conversation."""
    severity = "warning" if clarification_asked else "info"
    event    = f"Response: {mode} mode, {round(latency_ms / 1000, 1)}s"
    if clarification_asked:
        event += " — asked clarification"
    klog("health_response_quality", component="varys-health", service="claude-session",
         event=event, mode=mode, clarification_asked=clarification_asked,
         latency_ms=round(latency_ms, 1), request=request[:200],
         severity=severity, session_id=session_id or _SESSION_ID)
