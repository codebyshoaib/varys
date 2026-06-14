#!/usr/bin/env python3
"""Mirror signal events (ERROR/FATAL + self-heal actions) into the Notion
'Varys Observability' DB. If no direct Notion token, queue for MCP flush. Never raises."""
import json, os, sys, urllib.request
from pathlib import Path
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
try:
    from varys_notion import notion_request as _notion_request
except Exception:
    _notion_request = None

OBS_DB = os.environ.get("VARYS_OBS_DB", "8b0f5754470540dfb832a61380a2a9b9")  # Varys Observability DB
TOKEN_FILE = Path.home() / ".claude" / "hooks" / ".notion"
QUEUE = Path("/tmp/varys-notion-queue.jsonl")

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
        if _notion_request:
            _notion_request(req)
        else:
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
