#!/usr/bin/env python3
"""
content-scheduler.py — Daily social media content pipeline for Kamal.

Flow:
  1. Fetch next pending topic from Notion Content Calendar DB
  2. Create a NotebookLM notebook for it (or reuse existing)
  3. Generate slides + mindmap via nlm CLI
  4. Generate a local image (fitness or tech palette) via image_generator
  5. Post to LinkedIn with AI-written caption
  6. Mark topic as Done in Notion
  7. DM Kamal on Slack with what was posted

Notion DB: Content Calendar (ID in NOTION_CONTENT_DB below)
Cron: 0 11 * * * python3 .claude/hooks/content-scheduler.py >> /tmp/kamil-content.log 2>&1

Topic page properties expected:
  Topic (title)       — e.g. "Pull-up Progression"
  Category (select)   — "fitness" | "tech"
  Status (select)     — "Pending" | "In Progress" | "Done"
  PostType (select)   — "qa" | "steps" | "info" | "tip"  (optional, auto-detected)
  Question (text)     — for qa type (optional)
  Answer (text)       — for qa type (optional)
  Points (text)       — comma-separated for steps/info (optional)
"""

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_log import klog, klog_error

# ─── Config ───────────────────────────────────────────────────────────────────

HOOKS_DIR   = Path(__file__).parent
KAMIL_DIR   = HOOKS_DIR.parent.parent

SLACK_CFG   = Path.home() / ".claude" / "hooks" / ".slack"
KAMAL_DM    = "D0B415M06SK"

# Notion Content Calendar DB — created during May 25 session
# If this is wrong, Kamal can update it here
NOTION_CONTENT_DB = "36bd8747b3b1810da374e059835f00cd"

HANDLES = {
    "fitness": "@oykamal",
    "tech":    "@oykamal",
}

# ─── Slack ────────────────────────────────────────────────────────────────────

def load_slack_token() -> str:
    if SLACK_CFG.exists():
        for line in SLACK_CFG.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def slack_dm(token: str, text: str):
    if not token:
        print(f"[content] No Slack token, would DM: {text[:80]}")
        return
    data = json.dumps({"channel": KAMAL_DM, "text": text}).encode()
    req  = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", data=data,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
            if not resp.get("ok"):
                print(f"[content] Slack DM failed: {resp.get('error')}")
    except Exception as e:
        print(f"[content] Slack DM error: {e}")

# ─── Notion ───────────────────────────────────────────────────────────────────

def notion_fetch(db_id: str, filter_body: dict = None) -> list[dict]:
    """Query a Notion DB, return list of pages."""
    url  = f"https://api.notion.com/v1/databases/{db_id}/query"
    body = json.dumps(filter_body or {}).encode()
    # Notion MCP is available but we need token for direct calls.
    # We use the MCP indirectly by shelling out — simpler: use internal API via env.
    # Token is pulled from the MCP config.
    token = _notion_token()
    if not token:
        print("[content] No Notion token found — cannot fetch topics")
        return []
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Authorization":    f"Bearer {token}",
            "Notion-Version":   "2022-06-28",
            "Content-Type":     "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        return data.get("results", [])
    except Exception as e:
        print(f"[content] Notion fetch error: {e}")
        return []


def notion_update_page(page_id: str, properties: dict):
    token = _notion_token()
    if not token:
        return
    url  = f"https://api.notion.com/v1/pages/{page_id}"
    body = json.dumps({"properties": properties}).encode()
    req  = urllib.request.Request(
        url, data=body, method="PATCH",
        headers={
            "Authorization":  f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type":   "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
    except Exception as e:
        print(f"[content] Notion update error: {e}")


def _notion_token() -> str:
    """Pull Notion token from MCP settings."""
    settings_paths = [
        KAMIL_DIR / ".claude" / "settings.json",
        Path.home() / ".claude" / "settings.json",
    ]
    for path in settings_paths:
        if path.exists():
            try:
                cfg = json.loads(path.read_text())
                # Look in mcpServers for notion token
                servers = cfg.get("mcpServers", {})
                for name, srv in servers.items():
                    if "notion" in name.lower():
                        env = srv.get("env", {})
                        for k, v in env.items():
                            if "token" in k.lower() or "key" in k.lower():
                                return v
                        args = srv.get("args", [])
                        for i, a in enumerate(args):
                            if "token" in a.lower() and i+1 < len(args):
                                return args[i+1]
            except Exception:
                pass
    # Fallback: env var
    return os.environ.get("NOTION_TOKEN", "")


def prop_text(page: dict, key: str) -> str:
    """Extract plain text from a Notion property."""
    props = page.get("properties", {})
    prop  = props.get(key, {})
    ptype = prop.get("type", "")
    if ptype == "title":
        return "".join(t["plain_text"] for t in prop.get("title", []))
    if ptype == "rich_text":
        return "".join(t["plain_text"] for t in prop.get("rich_text", []))
    if ptype == "select":
        sel = prop.get("select")
        return sel["name"] if sel else ""
    return ""

# ─── NotebookLM ───────────────────────────────────────────────────────────────

def run_nlm(args: list, timeout: int = 180) -> tuple[bool, str]:
    try:
        r = subprocess.run(["nlm"] + args, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout.strip() or r.stderr.strip())
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def nlm_create_and_research(topic: str) -> str | None:
    """Create notebook + research topic. Returns notebook ID or None."""
    ok, out = run_nlm(["notebook", "create", "--json", "--title", topic], timeout=60)
    nb_id = None
    if ok:
        try:
            nb_id = json.loads(out).get("id") or json.loads(out).get("notebook_id")
        except Exception:
            import re
            m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', out)
            nb_id = m.group(0) if m else None

    if not nb_id:
        print(f"[content] Could not create NLM notebook for '{topic}': {out[:100]}")
        return None

    # Research the topic (add sources)
    run_nlm(["research", "start", nb_id, "--query", topic, "--confirm"], timeout=240)
    return nb_id


def nlm_trigger_artifacts(nb_id: str, topic: str):
    """Trigger slides + mindmap generation (async — NLM generates in background)."""
    run_nlm(["slides", "create", nb_id, "--focus", topic, "--confirm"], timeout=60)
    run_nlm(["mindmap", "create", nb_id, "--focus", topic, "--confirm"], timeout=60)
    print(f"[content] NLM artifacts triggered for notebook {nb_id[:8]}")

# ─── Image generation ─────────────────────────────────────────────────────────

def generate_image(topic: str, category: str, post_type: str,
                   question: str = "", answer: str = "",
                   points_raw: str = "") -> str | None:
    """Generate local image via image_generator.py. Returns path or None."""
    outfile  = f"/tmp/kamil-content-{datetime.now().strftime('%Y%m%d-%H%M')}.png"
    palette  = "fitness" if category == "fitness" else "tech"
    handle   = HANDLES.get(category, "@oykamal")
    gen_path = str(HOOKS_DIR / "image_generator.py")

    points = [p.strip() for p in points_raw.split(",") if p.strip()]

    if post_type == "qa" and question and answer:
        cmd = ["python3", gen_path, "--type", "qa",
               "--question", question, "--answer", answer,
               "--handle", handle, "--palette", palette, "--output", outfile]

    elif post_type == "steps" and points:
        cmd = ["python3", gen_path, "--type", "steps",
               "--title", topic, "--steps", points_raw,
               "--handle", handle, "--palette", palette, "--output", outfile]

    elif post_type == "info" and points:
        cmd = ["python3", gen_path, "--type", "info",
               "--title", topic, "--points", points_raw,
               "--handle", handle, "--palette", palette, "--output", outfile]

    else:
        # Auto-generate a tip image from just the topic
        cmd = ["python3", gen_path, "--type", "tip",
               "--tip", topic.upper(), "--context", f"#{category} #growthmindset",
               "--handle", handle, "--palette", palette, "--output", outfile]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and Path(outfile).exists():
            print(f"[content] Image generated: {outfile}")
            return outfile
        else:
            print(f"[content] Image generation failed: {r.stderr[:100]}")
            return None
    except Exception as e:
        print(f"[content] Image error: {e}")
        return None

# ─── Caption generation ───────────────────────────────────────────────────────

def generate_caption(topic: str, category: str, points_raw: str = "") -> str:
    """Use Claude to write a LinkedIn caption for the topic."""
    points_line = f"\nKey points: {points_raw}" if points_raw else ""
    prompt = (
        f"Write a LinkedIn caption for a {category} post about: {topic}.{points_line}\n"
        f"Rules: under 150 words, punchy first line that stops the scroll, "
        f"3-5 bullet insights, end with a question to drive comments, "
        f"3-4 relevant hashtags. No emojis overload. Sound like a practitioner not a marketer."
    )
    try:
        r = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt],
            capture_output=True, text=True, timeout=60
        )
        caption = r.stdout.strip()
        if caption and len(caption) > 30:
            return caption
    except Exception as e:
        print(f"[content] Caption generation error: {e}")

    # Fallback caption
    hashtags = "#fitness #training #health" if category == "fitness" else "#tech #engineering #softwareengineering"
    return f"🔥 {topic}\n\n{hashtags}"

# ─── LinkedIn posting ─────────────────────────────────────────────────────────

def post_linkedin(caption: str, image_path: str | None) -> str:
    """Post to LinkedIn. Returns result string."""
    sys.path.insert(0, str(HOOKS_DIR))
    try:
        from linkedin_poster import post_to_linkedin
        return post_to_linkedin(caption, image_path)
    except Exception as e:
        return f"❌ LinkedIn post error: {e}"

# ─── Main pipeline ────────────────────────────────────────────────────────────

def run():
    slack_token = load_slack_token()
    print(f"[content] Starting content scheduler — {datetime.now().isoformat()}")

    # 1. Fetch next pending topic from Notion
    pages = notion_fetch(NOTION_CONTENT_DB, filter_body={
        "filter": {
            "property": "Status",
            "select":   {"equals": "Pending"}
        },
        "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
        "page_size": 1,
    })

    if not pages:
        print("[content] No pending topics in Notion Content Calendar.")
        slack_dm(slack_token,
            "📅 *Content scheduler ran* — no pending topics in Notion.\n"
            "Add topics to the Content Calendar DB with Status=Pending.\n🤖 Kamil")
        return

    page     = pages[0]
    page_id  = page["id"]
    topic    = prop_text(page, "Topic") or prop_text(page, "Name") or "Untitled"
    category = prop_text(page, "Category").lower() or "fitness"
    post_type= prop_text(page, "PostType").lower() or "tip"
    question = prop_text(page, "Question")
    answer   = prop_text(page, "Answer")
    points   = prop_text(page, "Points")

    print(f"[content] Topic: '{topic}' | Category: {category} | Type: {post_type}")

    # Mark as In Progress
    notion_update_page(page_id, {
        "Status": {"select": {"name": "In Progress"}}
    })

    # 2. NotebookLM — create notebook + research
    slack_dm(slack_token,
        f"🧠 *Content pipeline started* — *{topic}* ({category})\n"
        f"Researching in NotebookLM + generating image...\n🤖 Kamil")

    nb_id = nlm_create_and_research(topic)
    if nb_id:
        nlm_trigger_artifacts(nb_id, topic)
        klog("content_nlm", component="content-scheduler",
             action="nlm_research", topic=topic, notebook=nb_id)

    # 3. Generate local image
    image_path = generate_image(
        topic=topic, category=category, post_type=post_type,
        question=question, answer=answer, points_raw=points
    )

    # 4. Generate caption
    caption = generate_caption(topic, category, points)

    # 5. Post to LinkedIn
    li_result = post_linkedin(caption, image_path)
    print(f"[content] LinkedIn: {li_result}")

    # 6. Mark Done in Notion
    notion_update_page(page_id, {
        "Status": {"select": {"name": "Done"}}
    })

    klog("content_posted", component="content-scheduler",
         action="posted", topic=topic, category=category,
         linkedin=li_result, has_image=bool(image_path), has_nlm=bool(nb_id))

    # 7. DM Kamal
    nlm_note = f"\n📓 NLM notebook `{nb_id[:8]}...` — slides + mindmap generating in background" if nb_id else ""
    img_note  = f"\n🖼️ Image: `{image_path}`" if image_path else "\n⚠️ No image generated"
    slack_dm(slack_token,
        f"✅ *Content posted!* — *{topic}*\n"
        f"Category: {category} | Type: {post_type}\n"
        f"{li_result}"
        f"{nlm_note}"
        f"{img_note}\n"
        f"Caption preview: _{caption[:120]}..._\n🤖 Kamil")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        klog_error("content_scheduler", e)
        token = load_slack_token()
        slack_dm(token,
            f"⚠️ *Content scheduler crashed*: {e}\n"
            f"Check: `tail -50 /tmp/kamil-content.log`\n🤖 Kamil")
        raise
