#!/usr/bin/env python3
"""
content-scheduler.py — Smart Content Scheduler v2.

Daily pipeline at 11am PKT (6am UTC via cron):
  1. Trend scan (fitness or tech alternating) + vlog always
  2. Insert trending topics >= 50 score into Notion Content Calendar DB
  3. Pick highest-scored Pending topic per track
  4. NLM: research + slides + infographic + mindmap (visual-first, sent as-is)
  5. image_generator: branded 1080x1350 portrait image
  6. LinkedIn auto-post (tech track only)
  7. Slack DM: images + caption (fitness/tech) or script (vlog)
  8. Mark Done in Notion

Cron: 0 6 * * * python3 .claude/hooks/content-scheduler.py >> /tmp/kamil-content.log 2>&1
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_log import klog, klog_error

# ─── Config ───────────────────────────────────────────────────────────────────

HOOKS_DIR         = Path(__file__).parent
KAMIL_DIR         = HOOKS_DIR.parent.parent
SLACK_CFG         = Path.home() / ".claude" / "hooks" / ".slack"
KAMAL_DM          = "D0B415M06SK"
NLM               = "/home/oye/.local/bin/nlm"
NOTION_CONTENT_DB = "68792d2dfff84691a4f646f5a8126149"
NOTION_CONTENT_LOG = "630d86afb17746f9ad6f9bc78afefa02"  # Content Log DB

HANDLES = {"fitness": "@oykamal", "tech": "@oykamal", "vlog": "@oykamal"}

TRACK_CHANNEL = {
    "fitness": "kamalkeexercies",
    "tech":    "kamalkecoding",
    "vlog":    "oykamal",
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
        print(f"[scheduler] No token, would DM: {text[:80]}")
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
                print(f"[scheduler] Slack DM failed: {resp.get('error')}")
    except Exception as e:
        print(f"[scheduler] Slack DM error: {e}")


def slack_upload(token: str, filepath: str, title: str, comment: str = ""):
    """Upload a file to Kamal's DM channel."""
    try:
        with open(filepath, "rb") as f:
            file_data = f.read()

        fname  = Path(filepath).name
        params = f"filename={fname}&length={len(file_data)}"
        req = urllib.request.Request(
            f"https://slack.com/api/files.getUploadURLExternal?{params}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
        if not resp.get("ok"):
            print(f"[scheduler] Upload URL failed: {resp.get('error')}")
            return

        upload_url = resp["upload_url"]
        file_id    = resp["file_id"]

        req2 = urllib.request.Request(upload_url, data=file_data, method="POST")
        req2.add_header("Content-Type", "application/octet-stream")
        with urllib.request.urlopen(req2, timeout=60):
            pass

        payload = json.dumps({
            "files":           [{"id": file_id, "title": title}],
            "channel_id":      KAMAL_DM,
            "initial_comment": comment,
        }).encode()
        req3 = urllib.request.Request(
            "https://slack.com/api/files.completeUploadExternal",
            data=payload,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req3, timeout=10) as r:
            result = json.loads(r.read())
        if not result.get("ok"):
            print(f"[scheduler] Upload complete failed: {result.get('error')}")
    except Exception as e:
        print(f"[scheduler] File upload error {filepath}: {e}")

# ─── Notion ───────────────────────────────────────────────────────────────────

def _notion_token() -> str:
    # 1. Check ~/.claude/hooks/.notion (primary — set by oauth/manual)
    notion_cfg = Path.home() / ".claude" / "hooks" / ".notion"
    if notion_cfg.exists():
        for line in notion_cfg.read_text().splitlines():
            if line.startswith("NOTION_API_KEY="):
                return line.split("=", 1)[1].strip()
    # 2. Check MCP settings
    for path in [KAMIL_DIR / ".claude" / "settings.json",
                 Path.home() / ".claude" / "settings.json"]:
        if not path.exists():
            continue
        try:
            cfg = json.loads(path.read_text())
            for name, srv in cfg.get("mcpServers", {}).items():
                if "notion" in name.lower():
                    for k, v in srv.get("env", {}).items():
                        if "token" in k.lower() or "key" in k.lower():
                            return v
        except Exception:
            pass
    # 3. Env var fallback
    return os.environ.get("NOTION_TOKEN", "")


def notion_query(db_id: str, filter_body: dict) -> list[dict]:
    token = _notion_token()
    if not token:
        return []
    body = json.dumps(filter_body).encode()
    req  = urllib.request.Request(
        f"https://api.notion.com/v1/databases/{db_id}/query",
        data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Notion-Version": "2022-06-28",
                 "Content-Type":   "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()).get("results", [])
    except Exception as e:
        print(f"[scheduler] Notion query error: {e}")
        return []


def notion_create_page(db_id: str, properties: dict):
    token = _notion_token()
    if not token:
        return
    body = json.dumps({"parent": {"database_id": db_id},
                       "properties": properties}).encode()
    req  = urllib.request.Request(
        "https://api.notion.com/v1/pages", data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Notion-Version": "2022-06-28",
                 "Content-Type":   "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
    except Exception as e:
        print(f"[scheduler] Notion create page error: {e}")


def notion_update_page(page_id: str, properties: dict):
    token = _notion_token()
    if not token:
        return
    body = json.dumps({"properties": properties}).encode()
    req  = urllib.request.Request(
        f"https://api.notion.com/v1/pages/{page_id}",
        data=body, method="PATCH",
        headers={"Authorization": f"Bearer {token}",
                 "Notion-Version": "2022-06-28",
                 "Content-Type":   "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
    except Exception as e:
        print(f"[scheduler] Notion update error: {e}")


def log_to_content_log(topic: str, track: str, score: int, reason: str,
                        caption: str, hashtags: str, nb_id: str,
                        li_post_id: str, vlog_angle: str,
                        platforms: list[str], status: str = "Generated"):
    """Write a row to the Notion Content Log DB after every run."""
    channel = TRACK_CHANNEL.get(track, "oykamal")
    props = {
        "Topic":           {"title":        [{"text": {"content": topic}}]},
        "Channel":         {"select":       {"name": channel}},
        "Track":           {"select":       {"name": track}},
        "Status":          {"select":       {"name": status}},
        "EngagementScore": {"number":       score},
        "EngagementReason":{"rich_text":    [{"text": {"content": reason[:800]}}]},
        "Caption":         {"rich_text":    [{"text": {"content": caption[:1800]}}]},
        "Hashtags":        {"rich_text":    [{"text": {"content": hashtags[:400]}}]},
        "NLMNotebookID":   {"rich_text":    [{"text": {"content": nb_id or ""}}]},
        "LinkedInPostID":  {"rich_text":    [{"text": {"content": li_post_id or ""}}]},
        "VlogAngle":       {"rich_text":    [{"text": {"content": vlog_angle or ""}}]},
        "Platforms":       {"multi_select": [{"name": p} for p in platforms]},
        "PostedDate":      {"date":         {"start": date.today().isoformat()}},
    }
    notion_create_page(NOTION_CONTENT_LOG, props)
    print(f"[scheduler] Logged to Content Log: {topic}")


def prop_text(page: dict, key: str) -> str:
    prop  = page.get("properties", {}).get(key, {})
    ptype = prop.get("type", "")
    if ptype == "title":
        return "".join(t["plain_text"] for t in prop.get("title", []))
    if ptype == "rich_text":
        return "".join(t["plain_text"] for t in prop.get("rich_text", []))
    if ptype == "select":
        sel = prop.get("select")
        return sel["name"] if sel else ""
    if ptype == "number":
        return str(prop.get("number") or "")
    return ""

# ─── Trend scan ───────────────────────────────────────────────────────────────

def run_trend_scan(track: str):
    """Scan trends, insert scoring >= 50 into Notion as Pending topics."""
    print(f"[scheduler] Trend scan: {track}")
    try:
        from trend_scanner import scan_trends
        results = scan_trends(track)
    except Exception as e:
        print(f"[scheduler] Trend scan error: {e}")
        return

    for r in results:
        notion_create_page(NOTION_CONTENT_DB, {
            "Topic":            {"title":     [{"text": {"content": r["topic"]}}]},
            "Track":            {"select":    {"name": track}},
            "Status":           {"select":    {"name": "Pending"}},
            "EngagementScore":  {"number":    r["score"]},
            "EngagementReason": {"rich_text": [{"text": {"content": r["reason"]}}]},
            "Source":           {"select":    {"name": "trending"}},
        })
        print(f"[scheduler]   +{r['score']} {r['topic']}")
    print(f"[scheduler] Trend scan done: {len(results)} topics added")

# ─── Topic pick ───────────────────────────────────────────────────────────────

def pick_topic(track: str) -> tuple | None:
    """Returns (page_id, topic, post_type, score, reason) or None."""
    pages = notion_query(NOTION_CONTENT_DB, {
        "filter": {"and": [
            {"property": "Status", "select": {"equals": "Pending"}},
            {"property": "Track",  "select": {"equals": track}},
        ]},
        "sorts":     [{"property": "EngagementScore", "direction": "descending"}],
        "page_size": 1,
    })
    if not pages:
        return None
    page      = pages[0]
    page_id   = page["id"]
    topic     = prop_text(page, "Topic")
    post_type = prop_text(page, "PostType") or "steps"
    score     = int(prop_text(page, "EngagementScore") or "60")
    reason    = prop_text(page, "EngagementReason") or "pre-planned queue topic"
    notion_update_page(page_id, {"Status": {"select": {"name": "In Progress"}}})
    return page_id, topic, post_type, score, reason

# ─── NLM ─────────────────────────────────────────────────────────────────────

def run_nlm(args: list, timeout: int = 300) -> tuple[bool, str]:
    try:
        r = subprocess.run([NLM] + args, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout.strip() or r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def nlm_create_notebook(topic: str) -> str | None:
    """Create NLM notebook. Correct syntax: nlm notebook create "Title" """
    import re as _re
    ok, out = run_nlm(["notebook", "create", topic], timeout=60)
    if ok:
        m = _re.search(r'ID:\s*([0-9a-f-]{36})', out)
        if m:
            return m.group(1)
        m = _re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', out)
        return m.group(0) if m else None
    print(f"[scheduler] NLM notebook create failed: {out[:100]}")
    return None


def nlm_research(nb_id: str, topic: str):
    """Research + auto-import sources. Correct syntax: nlm research start QUERY --notebook-id ID --mode deep --auto-import"""
    ok, out = run_nlm([
        "research", "start", topic,
        "--notebook-id", nb_id,
        "--mode", "deep",
        "--auto-import",
    ], timeout=420)
    print(f"[scheduler] NLM research: {'ok' if ok else 'failed'} — {out[:80]}")


def nlm_trigger_visuals(nb_id: str, topic: str):
    """Trigger slides + infographic + mindmap. Correct syntax verified from nlm --help."""
    # slides: nlm slides create NOTEBOOK_ID --focus TOPIC --confirm
    run_nlm(["slides", "create", nb_id, "--focus", topic, "--confirm"], timeout=60)
    # infographic: nlm infographic create NOTEBOOK_ID --focus TOPIC --confirm
    run_nlm(["infographic", "create", nb_id, "--focus", topic, "--confirm"], timeout=60)
    # mindmap: nlm mindmap create NOTEBOOK_ID --confirm (no --focus option)
    run_nlm(["mindmap", "create", nb_id, "--confirm"], timeout=60)
    print(f"[scheduler] NLM visuals triggered (slides+infographic+mindmap)")


def nlm_poll_and_send(nb_id: str, artifact_type: str, topic: str,
                       token: str, max_wait: int = 900):
    """Background thread: poll until artifact ready, download, upload to Slack as-is."""
    # Download commands verified: nlm download slide-deck|infographic|mind-map NB_ID --output FILE
    dl_cmd_map = {
        "slide_deck":  "slide-deck",
        "infographic": "infographic",
        "mind_map":    "mind-map",
    }
    ext_map = {"slide_deck": ".pdf", "infographic": ".png", "mind_map": ".json"}
    ext     = ext_map.get(artifact_type, ".bin")
    outfile = f"/tmp/nlm-{nb_id[:8]}-{artifact_type}{ext}"
    icons   = {"slide_deck": "📊", "infographic": "🖼️", "mind_map": "🗺️"}
    icon    = icons.get(artifact_type, "✅")
    waited  = 0

    while waited < max_wait:
        ok, out = run_nlm(["studio", "status", nb_id], timeout=30)
        if ok:
            try:
                for a in json.loads(out):
                    if a.get("type") == artifact_type:
                        status = a.get("status", "")
                        if status == "completed":
                            dl_cmd = dl_cmd_map.get(artifact_type, artifact_type)
                            dl_ok, _ = run_nlm(
                                ["download", dl_cmd, nb_id, "--output", outfile],
                                timeout=120,
                            )
                            if dl_ok and Path(outfile).exists():
                                slack_upload(
                                    token, outfile,
                                    title=f"{topic} — {artifact_type.replace('_', ' ')}",
                                    comment=f"{icon} *{topic}* — {artifact_type.replace('_', ' ')}\n🤖 Kamil",
                                )
                            else:
                                slack_dm(token, f"{icon} *{topic}* — {artifact_type} ready in NotebookLM (download failed)\n🤖 Kamil")
                            return
                        elif status == "failed":
                            print(f"[scheduler] NLM {artifact_type} failed")
                            return
            except Exception:
                pass
        time.sleep(20)
        waited += 20

    print(f"[scheduler] NLM {artifact_type} timed out after {max_wait}s")

# ─── Image generation ─────────────────────────────────────────────────────────

def generate_image(topic: str, track: str) -> str | None:
    outfile = f"/tmp/kamil-content-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    palette = "fitness" if track == "fitness" else "tech"
    handle  = HANDLES.get(track, "@oykamal")
    gen     = str(HOOKS_DIR / "image_generator.py")
    cmd     = ["python3", gen, "--type", "tip",
               "--tip", topic.upper()[:40], "--context", f"#{track}",
               "--handle", handle, "--palette", palette, "--output", outfile]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and Path(outfile).exists():
            print(f"[scheduler] Image generated: {outfile}")
            return outfile
        print(f"[scheduler] Image gen failed: {r.stderr[:80]}")
    except Exception as e:
        print(f"[scheduler] Image error: {e}")
    return None

# ─── Caption ─────────────────────────────────────────────────────────────────

def generate_caption(topic: str, track: str, score: int, reason: str) -> str:
    prompt = (
        f"Write a social media caption for a {track} post about: {topic}\n"
        f"Engagement score: {score}/100. Why trending: {reason}\n\n"
        f"Rules:\n"
        f"- Under 150 words\n"
        f"- First line = scroll-stopping hook (no emoji at start)\n"
        f"- 3-4 bullet points — each is a visual cue or quick insight\n"
        f"- Include 'Save this' or 'Swipe to see' CTA — audience are visual learners\n"
        f"- End with a question to drive comments\n"
        f"- 4 relevant trending hashtags for {track}\n"
        f"- Sound like a practitioner, not a marketer\n"
        f"Return ONLY the caption text."
    )
    try:
        r = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt],
            capture_output=True, text=True, timeout=90,
        )
        caption = r.stdout.strip()
        if len(caption) > 30:
            return caption
    except Exception as e:
        print(f"[scheduler] Caption error: {e}")

    tags = "#calisthenics #fitness #workout #health" if track == "fitness" else "#coding #AI #developer #tech"
    return f"{topic}\n\nSave this for later.\n\n{tags}"

# ─── Vlog script ──────────────────────────────────────────────────────────────

def generate_vlog_script(topic: str, score: int, reason: str) -> str:
    prompt = (
        f"Write a Casey Neistat-style vlog script for a daily Islamabad life video about: {topic}\n"
        f"Trending signal: {reason}\n\n"
        f"Use this exact format:\n"
        f"🎬 VLOG TOPIC: {topic} — {score}/100\n"
        f"WHY TODAY: [what's trending/timely]\n\n"
        f"HOOK (first 3 sec on camera):\n"
        f'"[punchy opening line — no intro, straight to action]"\n\n'
        f"SCENES:\n"
        f"1. [specific Islamabad location] — [what to film, duration, angle]\n"
        f"2. [location] — [action]\n"
        f"3. [location] — [action]\n"
        f"4. [location] — [action]\n"
        f"5. [location] — [action]\n\n"
        f"B-ROLL: [3 specific shots to grab while moving]\n"
        f"TRENDING AUDIO: [specific song or sound]\n"
        f'CTA: "[closing line that drives follows/comments]"\n\n'
        f"HASHTAGS: [10 tags for Pakistan/Islamabad/travel/vlog]\n"
        f"CAPTION: [ready-to-paste caption for YouTube/TikTok/Reels/Shorts]\n\n"
        f"Use real Islamabad locations: F-7, F-6, Blue Area, Margalla Hills, F-10, Jinnah Super, etc.\n"
        f"Return ONLY the script."
    )
    try:
        r = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", prompt],
            capture_output=True, text=True, timeout=90,
        )
        script = r.stdout.strip()
        if len(script) > 100:
            return script
    except Exception as e:
        print(f"[scheduler] Vlog script error: {e}")

    return (
        f"🎬 VLOG TOPIC: {topic} — {score}/100\n"
        f"WHY TODAY: {reason}\n\n"
        f"Script generation failed — write this one manually."
    )

# ─── LinkedIn ─────────────────────────────────────────────────────────────────

def post_linkedin(caption: str, image_path: str | None) -> str:
    try:
        from linkedin_poster import post_to_linkedin
        return post_to_linkedin(caption, image_path)
    except Exception as e:
        return f"❌ LinkedIn error: {e}"

# ─── Track runners ────────────────────────────────────────────────────────────

def run_fitness_or_tech(track: str, token: str):
    print(f"[scheduler] === {track.upper()} ===")

    run_trend_scan(track)

    result = pick_topic(track)
    if not result:
        slack_dm(token,
            f"📅 *{track} content* — no Pending topics in Notion Content Calendar.\n"
            f"Add topics with Status=Pending, Track={track}\n🤖 Kamil")
        return

    page_id, topic, post_type, score, reason = result
    print(f"[scheduler] Topic: {topic} ({score}/100)")

    slack_dm(token,
        f"🚀 *{track} pipeline started* — *{topic}*\n"
        f"Score: {score}/100 | {reason}\n"
        f"Researching + generating visuals...\n🤖 Kamil")

    # NLM pipeline
    nb_id = nlm_create_notebook(topic)
    if nb_id:
        nlm_research(nb_id, topic)
        nlm_trigger_visuals(nb_id, topic)
        for artifact in ["slide_deck", "infographic", "mind_map"]:
            threading.Thread(
                target=nlm_poll_and_send,
                args=(nb_id, artifact, topic, token),
                daemon=True,
            ).start()

    # Branded image
    image_path = generate_image(topic, track)

    # Caption
    caption = generate_caption(topic, track, score, reason)

    # LinkedIn (tech only)
    li_result = ""
    if track == "tech":
        li_result = post_linkedin(caption, image_path)
        print(f"[scheduler] LinkedIn: {li_result}")

    # Mark Done in Notion
    notion_update_page(page_id, {
        "Status":         {"select":    {"name": "Done"}},
        "PostedDate":     {"date":      {"start": date.today().isoformat()}},
        "NLMNotebookID":  {"rich_text": [{"text": {"content": nb_id or ""}}]},
    })

    li_line  = f"\n✅ Auto-posted to LinkedIn: {li_result}" if track == "tech" else ""
    nb_line  = f"\n📓 NLM `{nb_id[:8]}...` — slides + infographic + mindmap delivering shortly" if nb_id else ""

    slack_dm(token,
        f"📊 *{track.upper()} content ready — {topic}*\n"
        f"Score: {score}/100 — {reason}"
        f"{li_line}{nb_line}\n\n"
        f"*Caption (paste this):*\n{caption}\n\n"
        f"📱 Post to Instagram + TikTok (images coming)\n🤖 Kamil")

    if image_path:
        slack_upload(token, image_path,
                     title=f"{topic} — branded",
                     comment=f"🎨 Branded image for *{topic}*")

    # Extract hashtags from caption for logging
    hashtag_line = " ".join(w for w in caption.split() if w.startswith("#"))

    # Vlog cross-link angle for @oykamal
    vlog_angle = f"Behind the build: the moment that made '{topic}' worth posting — what was happening in Islamabad when this was created."

    # Log everything to Notion Content Log
    platforms = ["TikTok", "Instagram", "YouTube Shorts", "Facebook"]
    if track == "tech" and li_result and "✅" in li_result:
        platforms.append("LinkedIn")

    log_to_content_log(
        topic=topic, track=track, score=score, reason=reason,
        caption=caption, hashtags=hashtag_line, nb_id=nb_id or "",
        li_post_id=li_result if li_result and "urn:" in li_result else "",
        vlog_angle=vlog_angle, platforms=platforms,
        status="Posted" if (image_path or li_result) else "Generated",
    )

    klog("content_posted", component="content-scheduler",
         topic=topic, track=track, score=score,
         linkedin=bool(li_result), nlm=bool(nb_id))


def run_vlog(token: str):
    print(f"[scheduler] === VLOG ===")
    run_trend_scan("vlog")

    result = pick_topic("vlog")
    if not result:
        slack_dm(token,
            "📅 *Vlog* — no Pending topics in Notion Content Calendar.\n"
            "Add topics with Track=vlog, Status=Pending\n🤖 Kamil")
        return

    page_id, topic, _, score, reason = result
    script = generate_vlog_script(topic, score, reason)

    notion_update_page(page_id, {
        "Status":     {"select": {"name": "Done"}},
        "PostedDate": {"date":   {"start": date.today().isoformat()}},
    })

    slack_dm(token,
        f"🎬 *Vlog script ready — {topic}*\n"
        f"Score: {score}/100 — {reason}\n\n"
        f"{script}\n\n"
        f"📱 Film today → post to YouTube/TikTok/Reels/Shorts\n🤖 Kamil")

    # Log vlog to Content Log
    log_to_content_log(
        topic=topic, track="vlog", score=score, reason=reason,
        caption=script[:1800], hashtags="", nb_id="",
        li_post_id="", vlog_angle=script[:400],
        platforms=["TikTok", "Instagram", "YouTube Shorts", "Facebook"],
        status="Generated",
    )

    klog("vlog_script", component="content-scheduler", topic=topic, score=score)

# ─── Main ─────────────────────────────────────────────────────────────────────

def run():
    """Run ALL 3 tracks every day in parallel — NLM gives 3 daily slots."""
    token = load_slack_token()
    print(f"[scheduler] Starting {datetime.now().isoformat()} — running fitness + tech + vlog in parallel")

    fitness_thread = threading.Thread(target=run_fitness_or_tech, args=("fitness", token))
    tech_thread    = threading.Thread(target=run_fitness_or_tech, args=("tech", token))
    vlog_thread    = threading.Thread(target=run_vlog, args=(token,))

    fitness_thread.start()
    tech_thread.start()
    vlog_thread.start()

    fitness_thread.join()
    tech_thread.join()
    vlog_thread.join()

    print(f"[scheduler] Done {datetime.now().isoformat()}")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        klog_error("content_scheduler", e)
        token = load_slack_token()
        slack_dm(token,
            f"⚠️ *Content scheduler crashed*: {e}\n"
            f"Check: tail -50 /tmp/kamil-content.log\n🤖 Kamil")
        raise
