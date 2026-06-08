#!/usr/bin/env python3
"""
notion_setup.py — Notion database creation helpers for the /setup wizard.

Called by the /setup slash command to create the 3 required databases
in the user's Notion workspace via the Notion REST API.
No third-party dependencies — uses urllib only.
"""
import json
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def _post(url: str, api_key: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=_headers(api_key), method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _get(url: str, api_key: str) -> dict:
    req = urllib.request.Request(url, headers=_headers(api_key), method="GET")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def test_connection(api_key: str) -> tuple[bool, str]:
    """Test that the API key is valid. Returns (ok, message)."""
    try:
        result = _get("https://api.notion.com/v1/users/me", api_key)
        name = result.get("name") or result.get("bot", {}).get("owner", {}).get("user", {}).get("name", "unknown")
        return True, f"Connected as: {name}"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "Invalid API token — check you copied it correctly."
        return False, f"HTTP error {e.code}: {e.reason}"
    except Exception as e:
        return False, f"Connection failed: {e}"


def create_parent_page(api_key: str, agent_name: str) -> str:
    """Create a top-level page '[AGENT_NAME] Brain' in the workspace. Returns page_id."""
    payload = {
        "parent": {"type": "workspace", "workspace": True},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": f"{agent_name} Brain"}}]
            }
        },
        "icon": {"type": "emoji", "emoji": "🧠"},
    }
    try:
        result = _post("https://api.notion.com/v1/pages", api_key, payload)
        return result["id"]
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        err = json.loads(body) if body else {}
        if "parent" in err.get("message", "").lower() or e.code == 400:
            payload["parent"] = {"type": "page_id", "page_id": _find_any_page(api_key)}
            result = _post("https://api.notion.com/v1/pages", api_key, payload)
            return result["id"]
        raise


def _find_any_page(api_key: str) -> str:
    """Find any accessible page to use as parent (fallback for restricted workspaces)."""
    result = _post(
        "https://api.notion.com/v1/search",
        api_key,
        {"filter": {"value": "page", "property": "object"}, "page_size": 1},
    )
    pages = result.get("results", [])
    if not pages:
        raise RuntimeError(
            "No pages found in your Notion workspace. "
            "Please create at least one page in Notion, then run /setup again."
        )
    return pages[0]["id"]


def create_harness_db(api_key: str, parent_id: str, agent_name: str) -> str:
    """Create the Harness task backlog DB. Returns database_id."""
    payload = {
        "parent": {"type": "page_id", "page_id": parent_id},
        "title": [{"type": "text", "text": {"content": f"{agent_name} Harness"}}],
        "icon": {"type": "emoji", "emoji": "⚙️"},
        "properties": {
            "Name": {"title": {}},
            "Status": {
                "select": {
                    "options": [
                        {"name": "Not started", "color": "gray"},
                        {"name": "In progress", "color": "blue"},
                        {"name": "Done", "color": "green"},
                        {"name": "Blocked", "color": "red"},
                        {"name": "In review", "color": "yellow"},
                        {"name": "Cancelled", "color": "default"},
                    ]
                }
            },
            "Phase": {
                "select": {
                    "options": [
                        {"name": "Research", "color": "purple"},
                        {"name": "Planning", "color": "blue"},
                        {"name": "In Dev", "color": "orange"},
                        {"name": "Testing", "color": "yellow"},
                        {"name": "Done", "color": "green"},
                        {"name": "Blocked", "color": "red"},
                    ]
                }
            },
            "Plan Summary": {"rich_text": {}},
            "Confidence": {"number": {"format": "number"}},
            "Last Activity": {"date": {}},
            "Agent Session ID": {"rich_text": {}},
            "Last Agent Update": {"date": {}},
            "GitHub PR": {"url": {}},
            "Slack Thread": {"url": {}},
        },
    }
    result = _post("https://api.notion.com/v1/databases", api_key, payload)
    return result["id"]


def create_work_log_db(api_key: str, parent_id: str, agent_name: str) -> str:
    """Create the Work Log session DB. Returns database_id."""
    payload = {
        "parent": {"type": "page_id", "page_id": parent_id},
        "title": [{"type": "text", "text": {"content": f"{agent_name} Work Log"}}],
        "icon": {"type": "emoji", "emoji": "📋"},
        "properties": {
            "Date": {"title": {}},
            "Summary": {"rich_text": {}},
            "Session ID": {"rich_text": {}},
            "Duration": {"number": {"format": "number"}},
            "Tasks Completed": {"rich_text": {}},
        },
    }
    result = _post("https://api.notion.com/v1/databases", api_key, payload)
    return result["id"]


def create_inbox_db(api_key: str, parent_id: str, agent_name: str) -> str:
    """Create the Slack Inbox DB (only if Slack enabled). Returns database_id."""
    payload = {
        "parent": {"type": "page_id", "page_id": parent_id},
        "title": [{"type": "text", "text": {"content": f"{agent_name} Inbox"}}],
        "icon": {"type": "emoji", "emoji": "📥"},
        "properties": {
            "Message": {"title": {}},
            "From": {"rich_text": {}},
            "Channel": {"rich_text": {}},
            "Status": {
                "select": {
                    "options": [
                        {"name": "New", "color": "red"},
                        {"name": "Read", "color": "yellow"},
                        {"name": "Actioned", "color": "green"},
                    ]
                }
            },
            "Received At": {"date": {}},
        },
    }
    result = _post("https://api.notion.com/v1/databases", api_key, payload)
    return result["id"]


def write_test_entry(api_key: str, db_id: str) -> str:
    """Write a test entry to the Work Log DB, return its page_id."""
    payload = {
        "parent": {"database_id": db_id},
        "properties": {
            "Date": {
                "title": [{"type": "text", "text": {"content": f"Setup test — {datetime.utcnow().isoformat()}"}}]
            },
            "Summary": {
                "rich_text": [{"type": "text", "text": {"content": "Automated setup verification entry"}}]
            },
        },
    }
    result = _post("https://api.notion.com/v1/pages", api_key, payload)
    return result["id"]


def delete_test_entry(api_key: str, page_id: str) -> None:
    """Archive (soft-delete) the test page."""
    data = json.dumps({"archived": True}).encode()
    req = urllib.request.Request(
        f"https://api.notion.com/v1/pages/{page_id}",
        data=data,
        headers=_headers(api_key),
        method="PATCH",
    )
    urllib.request.urlopen(req, timeout=10)
