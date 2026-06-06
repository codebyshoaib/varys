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

import copy
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

# NLM fallback: Claude research + Canva infographic
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from claude_researcher import research as claude_research, ResearchResult
from canva_infographic import generate_infographic as canva_generate_infographic

# ─── Emotional Content Playbook ───────────────────────────────────────────────
# Loaded once at startup — injected into every caption/script/NLM prompt
_PLAYBOOK_PATH = Path(__file__).parent.parent.parent / "vault/memory/content_emotional_playbook.md"
EMOTIONAL_PLAYBOOK = _PLAYBOOK_PATH.read_text() if _PLAYBOOK_PATH.exists() else ""
_PLAYBOOK_SUMMARY = """
CONTENT RULES (Emotional Content Playbook):
- Pick ONE emotion per piece: awe, longing, nostalgia, or belonging. Never mix.
- Arousal beats valence: push "beautiful/calm" up into AWE (chill-down-the-spine), not contentment.
- Hook in first 3 seconds: most striking visual first, 4-7 word text overlay, pattern interrupt.
- Use delayed-answer technique: "this place" not "Trail 5" — open the loop, close it at payoff.
- Never end on sadness. Resolve upward into awe, hope, or warmth.
- No anger, no anxiety, no rage-bait. Kamal's lane: awe + amusement only.
- Specifics beat generalities: "naan so hot it burned my fingers" not "the food was amazing".
- Write like you talk. Read it out loud. One idea per line.
- Earn the emotion — don't announce it. Show the thing, don't say "this is emotional".
- CTA: save/comment/share — never force, always soft.
"""

# ─── Config ───────────────────────────────────────────────────────────────────

HOOKS_DIR         = Path(__file__).parent
KAMIL_DIR         = HOOKS_DIR.parent.parent
SLACK_CFG         = Path.home() / ".claude" / "hooks" / ".slack"
KAMAL_DM          = "D0B415M06SK"
NLM                  = "/home/oye/.local/bin/nlm"
NLM_PROFILE          = os.environ.get("NLM_PROFILE", "work")           # m.kamal@taleemabad.com
NLM_PROFILE_PERSONAL = os.environ.get("NLM_PROFILE_PERSONAL", "default")  # oyekamalkhan@gmail.com
NOTION_CONTENT_DB = "68792d2dfff84691a4f646f5a8126149"
NOTION_CONTENT_LOG = "630d86afb17746f9ad6f9bc78afefa02"  # Content Log DB
CANVA_BRAND_KIT_ID = os.environ.get("CANVA_BRAND_KIT_ID", "")
CANVA_AGENT        = KAMIL_DIR / "agents" / "kamil_canva_agent.py"

HANDLES = {"fitness": "@oykamal", "tech": "@oykamal", "vlog": "@oykamal", "painting": "@oykamal"}

# NLM artifact pollers run in non-daemon threads that outlive their track function.
# They register here so run() can join() them before the process exits — otherwise
# the process ends in ~20s and the pollers (which wait minutes for NLM to render)
# are killed before slides/infographic/mindmap are downloaded + posted to Slack.
ARTIFACT_POLLERS: list = []
_POLLERS_LOCK = threading.Lock()

TRACK_CHANNEL = {
    "fitness": "kamalkeexercies",
    "tech":    "kamalkecoding",
    "vlog":    "oykamal",
    "painting":"kamalkepainting",
}

# ─── Curated Topic Bank ───────────────────────────────────────────────────────
# Personal story seeds — Kamal's real life, Islamabad-specific, personal angle.
# These are seeded into Notion on first run; this dict is the source of truth.
# Trend scanner adds to Notion but these always take priority.
TOPIC_BANK = {
    "fitness": [
        "The first time I did a muscle-up — what nobody tells you about the transition",
        "Margalla Trail 5 at 5am — what the city looks like from up there",
        "Why I switched from gym to calisthenics (the real reason)",
        "Swimming in Rawal Lake in October — what it actually feels like",
        "30-day pull-up challenge: day 1 vs day 30, here's what changed",
        "The Islamabad cycling route I do every Sunday (F-7 to Saidpur, 22km)",
        "I tried running every morning for 2 weeks — this is what happened to my output",
        "Hiking alone vs hiking with someone — which one builds you more",
        "The calisthenics move that took me 6 months — here's the breakdown",
        "Why most people quit exercise after 3 weeks (I almost did too)",
        "Daman-e-Koh trail in rain — the best version of this city",
        "How I track fitness without an app (analog method that actually works)",
        "Cold water swimming: 3 months in, here's what changed in my brain",
        "The 5 bodyweight exercises I do every single day",
        "What I eat before a long trail run (real food, Islamabad edition)",
        "I got injured and couldn't train for a month — here's what I learned",
        "Margalla Hills vs Rawal Lake: which one is better for mental reset",
        "The moment I realised calisthenics is actually harder than the gym",
        "How I fit training into a life of building software products",
        "Cycling at golden hour in Islamabad — a visual",
    ],
    "tech": [
        "I built a Slack bot that runs my entire dev workflow — here's how",
        "Why I use Claude Code for every PR now (not just hard problems)",
        "The harness I built so I never write the same code twice",
        "How I automated my content pipeline with Claude agents",
        "Agentic workflows explained through the thing I actually built",
        "The biggest mistake I made building AI agents (and how I fixed it)",
        "How NotebookLM changed the way I research before building",
        "My PR review workflow: from Slack mention to merged in under an hour",
        "Building a job-finder that auto-applies — what I learned",
        "Why my Claude agent has hooks that block it from doing bad things",
        "How I built a Notion-backed memory system for my AI agent",
        "The self-healing observer that fixes my cron jobs at 3am",
        "From idea to shipped feature: my exact pipeline in a Django LMS",
        "What I wish I knew about Django multi-tenancy before starting",
        "How I use parallel agents to do 6 hours of work in 45 minutes",
        "The one hook that saves me from AI hallucinations every day",
        "Why I stopped writing tests manually (and what I do instead)",
        "Building a content scheduler that actually knows what to post",
        "Claude Sonnet vs Haiku: when I use each and why it matters",
        "The git worktree pattern that lets me work on 3 features at once",
    ],
    "vlog": [
        "A normal Sunday in Islamabad — F-7 chai, Margalla, back by noon",
        "The morning routine that changed how I think about my day",
        "Why I moved back to Islamabad (the real answer, not the polished one)",
        "Saidpur Village on a quiet Tuesday — what this city feels like when you slow down",
        "The project that almost broke me and what it taught me",
        "What building software products actually looks like from the inside",
        "A day where everything went wrong and I filmed it anyway",
        "The chai spot in F-6 I've been going to for 3 years",
        "Daman-e-Koh at dusk — the moment the city turns golden",
        "Why I started painting again after 5 years",
        "The conversation I had with a stranger on Trail 3 that I keep thinking about",
        "What Islamabad looks like in January fog — a visual",
        "I spent a week without my phone for an hour each morning — here's what happened",
        "The thing about building things in Pakistan that nobody talks about",
        "A birthday in Islamabad: what I did, where I went, what I felt",
        "How I balance deep work with being present in life (still figuring it out)",
        "The road from Islamabad to Murree — filmed it so you don't have to imagine",
        "Friday jummah in G-7 — belonging in your own city",
        "What I learned from shipping 3 products in one year",
        "The version of this city most people never see",
    ],
    "painting": [
        "Why I paint — and why I stopped for 5 years",
        "The painting that took me 3 weeks and what it taught me about patience",
        "Oil vs watercolour: what I switched and why",
        "Painting Margalla Hills from memory — the colour I always get wrong",
        "What happens to your mind when you paint for 2 hours without stopping",
        "The reference photo vs the finished painting — a before/after",
        "How painting made me a better software engineer",
        "The Islamabad street scene I've been wanting to paint for a year",
        "Studio setup: how I paint in a small apartment",
        "Learning from a master painter — what I tried to steal from Monet",
    ],
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


def notion_create_page(db_id: str, properties: dict) -> str:
    """Create a Notion page and return its page ID."""
    token = _notion_token()
    if not token:
        return ""
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
            data = json.loads(r.read())
            return data.get("id", "")
    except Exception as e:
        print(f"[scheduler] Notion create page error: {e}")
        return ""


def notion_write_page_body(page_id: str, content: str):
    """Append text as paragraph blocks to a Notion page body."""
    token = _notion_token()
    if not token or not page_id or not content:
        return
    body = json.dumps({
        "children": [{"object": "block", "type": "paragraph",
                      "paragraph": {"rich_text": [{"type": "text",
                                                   "text": {"content": content[:1800]}}]}}]
    }).encode()
    req = urllib.request.Request(
        f"https://api.notion.com/v1/blocks/{page_id}/children",
        data=body, method="PATCH",
        headers={"Authorization": f"Bearer {token}",
                 "Notion-Version": "2022-06-28",
                 "Content-Type":   "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
    except Exception as e:
        print(f"[scheduler] Notion write body error: {e}")


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
                        platforms: list[str], status: str = "Generated",
                        nlm_insights: str = "", nlm_artifacts: dict = None,
                        calendar_page_id: str = "") -> str:
    """Write a row to the Notion Content Log DB. Returns the created page ID."""
    channel = TRACK_CHANNEL.get(track, "oykamal")
    artifacts_json = json.dumps(nlm_artifacts) if nlm_artifacts else ""
    props = {
        "Topic":                  {"title":     [{"text": {"content": topic}}]},
        "Channel":                {"select":    {"name": channel}},
        "Track":                  {"select":    {"name": track}},
        "Status":                 {"select":    {"name": status}},
        "EngagementScore":        {"number":    score},
        "EngagementReason":       {"rich_text": [{"text": {"content": reason[:800]}}]},
        "Caption":                {"rich_text": [{"text": {"content": caption[:1800]}}]},
        "Hashtags":               {"rich_text": [{"text": {"content": hashtags[:400]}}]},
        "NLMNotebookID":          {"rich_text": [{"text": {"content": nb_id or ""}}]},
        "LinkedInPostID":         {"rich_text": [{"text": {"content": li_post_id or ""}}]},
        "VlogAngle":              {"rich_text": [{"text": {"content": vlog_angle or ""}}]},
        "NLMArtifacts":           {"rich_text": [{"text": {"content": artifacts_json}}]},
        "NLMInsights":            {"rich_text": [{"text": {"content": nlm_insights[:1800]}}]},
        "ContentCalendarPageID":  {"rich_text": [{"text": {"content": calendar_page_id or ""}}]},
        "Platforms":              {"multi_select": [{"name": p} for p in platforms]},
        "PostedDate":             {"date":      {"start": date.today().isoformat()}},
    }
    log_page_id = notion_create_page(NOTION_CONTENT_LOG, props)
    if log_page_id and nlm_insights:
        notion_write_page_body(log_page_id, nlm_insights)
    print(f"[scheduler] Logged to Content Log: {topic} (page={log_page_id[:8] if log_page_id else 'none'})")
    return log_page_id


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
    """Returns (page_id, topic, post_type, score, reason, existing_nb_id) or None.

    Priority order:
    1. Curated topics (Source=curated) — Kamal's personal story bank
    2. Any other Pending topic (trend scanner additions, manually queued)
    """
    # Try curated topics first
    for source_filter in [
        {"and": [
            {"property": "Status", "select": {"equals": "Pending"}},
            {"property": "Track",  "select": {"equals": track}},
            {"property": "Source", "select": {"equals": "curated"}},
        ]},
        {"and": [
            {"property": "Status", "select": {"equals": "Pending"}},
            {"property": "Track",  "select": {"equals": track}},
        ]},
    ]:
        pages = notion_query(NOTION_CONTENT_DB, {
            "filter": source_filter,
            "sorts":  [{"property": "EngagementScore", "direction": "descending"}],
            "page_size": 1,
        })
        if pages:
            break

    if not pages:
        return None
    page         = pages[0]
    page_id      = page["id"]
    topic        = prop_text(page, "Topic")
    post_type    = prop_text(page, "PostType") or "steps"
    score        = int(prop_text(page, "EngagementScore") or "60")
    reason       = prop_text(page, "EngagementReason") or "Curated personal story topic"
    existing_nb  = prop_text(page, "NLMNotebookID")
    notion_update_page(page_id, {"Status": {"select": {"name": "In Progress"}}})
    return page_id, topic, post_type, score, reason, existing_nb

# ─── NLM ─────────────────────────────────────────────────────────────────────

# nlm subcommands that do NOT accept --profile. They rely on the global default
# profile (set to "work" via `nlm login switch work`). Injecting --profile here
# makes nlm error with "No such option '--profile'" → download/status failures.
_NO_PROFILE_CMDS = {"download", "studio"}


def _inject_profile(args: list) -> list:
    """Insert --profile <NLM_PROFILE> after the leading subcommand verbs, before any
    positional values (IDs, free-text questions). nlm verbs are the leading non-flag
    tokens; we stop at the first arg that looks like a value (UUID, URL, or contains a space)."""
    if "--profile" in args or "-p" in args:
        return args
    if args and args[0] in _NO_PROFILE_CMDS:
        return args                       # these commands reject --profile; use global default
    i = 0
    while i < len(args):
        tok = args[i]
        if tok.startswith("-"):           # reached an option — insert before it
            break
        if i >= 1 and (" " in tok or "-" in tok or "/" in tok or "." in tok):
            break                          # positional value (id/question/url) — insert before it
        i += 1
    return args[:i] + ["--profile", NLM_PROFILE] + args[i:]


def run_nlm(args: list, timeout: int = 300) -> tuple[bool, str]:
    args = _inject_profile(args)
    try:
        r = subprocess.run([NLM] + args, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout.strip() or r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def nlm_find_existing_notebook(topic: str) -> tuple[str, int] | None:
    """Search existing notebooks for a title match. Returns (nb_id, source_count) or None."""
    import re as _re
    ok, out = run_nlm(["list", "notebooks"], timeout=30)
    if not ok:
        return None
    try:
        notebooks = json.loads(out)
    except Exception:
        return None
    topic_lower = topic.lower()
    # exact or near-match on title
    for nb in notebooks:
        title = nb.get("title", "").lower()
        if title and (title == topic_lower or topic_lower[:30] in title or title[:30] in topic_lower):
            nb_id = nb["id"]
            count = nb.get("source_count", 0)
            print(f"[scheduler] NLM found existing notebook: '{nb['title']}' ({count} sources) → {nb_id[:8]}")
            return nb_id, count
    return None


def nlm_get_source_count(nb_id: str, retries: int = 3) -> int:
    """Return current source count for a notebook. Retry up to 3 times on failure."""
    for attempt in range(retries):
        ok, out = run_nlm(["list", "notebooks"], timeout=30)
        if ok:
            try:
                for nb in json.loads(out):
                    if nb["id"] == nb_id:
                        count = nb.get("source_count", 0)
                        if count > 0 or attempt == retries - 1:
                            return count
                        time.sleep(5)  # Wait before retry if no sources yet
                        continue
            except Exception:
                pass
        if attempt < retries - 1:
            time.sleep(5)
    return 0


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


def nlm_get_or_create_notebook(topic: str) -> tuple[str, bool] | tuple[None, bool]:
    """
    Return (nb_id, had_sources). Reuses existing notebook if it has sources.
    If existing has 0 sources, deletes it and creates fresh.
    Returns (None, False) on failure.
    """
    existing = nlm_find_existing_notebook(topic)
    if existing:
        nb_id, count = existing
        if count > 0:
            print(f"[scheduler] Reusing existing notebook {nb_id[:8]} ({count} sources) — skipping research")
            return nb_id, True
        else:
            # Empty notebook — delete and recreate
            print(f"[scheduler] Existing notebook {nb_id[:8]} has 0 sources — deleting and recreating")
            run_nlm(["delete", "notebook", nb_id, "--confirm"], timeout=30)

    nb_id = nlm_create_notebook(topic)
    return nb_id, False


def nlm_research(nb_id: str, topic: str, retries: int = 2) -> bool:
    """Research + auto-import sources. Returns True if sources were added.
    Tries deep mode first; if Google API error code 8 (quota/expired), falls back to fast mode."""
    for mode in ["deep", "fast"]:
        for attempt in range(retries):
            ok, out = run_nlm([
                "research", "start", topic,
                "--notebook-id", nb_id,
                "--mode", mode,
                "--force",
                "--auto-import",
            ], timeout=420 if mode == "deep" else 120)
            print(f"[scheduler] NLM research ({mode}): {'ok' if ok else 'failed'} — {out[:80]} (attempt {attempt + 1}/{retries})")

            # Deep mode quota/expired → fall back to fast immediately
            if not ok and mode == "deep" and ("error code 8" in out.lower() or "quota" in out.lower() or "429" in out):
                print(f"[scheduler] NLM deep mode quota/expired — falling back to fast mode")
                break  # break inner retries loop, outer loop picks up fast mode

            # Fast mode quota → give up entirely
            if not ok and mode == "fast" and ("error code 8" in out.lower() or "quota" in out.lower() or "429" in out):
                print(f"[scheduler] NLM fast mode also quota-exhausted — giving up")
                return False

            if not ok:
                if attempt < retries - 1:
                    time.sleep(10)
                continue
            # Verify sources actually landed
            count = nlm_get_source_count(nb_id)
            print(f"[scheduler] NLM source count after research ({mode}): {count}")
            if count > 0:
                return True
            if attempt < retries - 1:
                time.sleep(10)
    return False


def nlm_query_for_content(nb_id: str, topic: str) -> str:
    """Query the notebook for key insights to use as caption basis."""
    query = (
        f"What are the 5 most surprising, specific, or contrarian insights about '{topic}' "
        f"that would trigger AWE or LONGING in someone scrolling Instagram at 11pm? "
        f"Focus on: concrete facts, unexpected angles, sensory details, or things that make someone say "
        f"'I had no idea' or 'I want to experience this'. Not generic advice — specific, vivid, emotional."
    )
    ok, out = run_nlm(["query", "notebook", nb_id, query], timeout=120)
    if ok and out:
        try:
            answer = json.loads(out).get("value", {}).get("answer", "")
            if len(answer) > 50:
                print(f"[scheduler] NLM query: got {len(answer)} chars of insights")
                return answer
        except Exception:
            if len(out) > 50:
                return out
    print(f"[scheduler] NLM query failed or empty")
    return ""


def nlm_trigger_visuals(nb_id: str, topic: str, profile: str = None) -> dict:
    """Trigger slides + infographic + mindmap on the SAME profile that owns the notebook.
    Returns state dict per artifact: 'triggered', 'rate_limited', or 'failed'.
    Artifacts are account-scoped — never cross profiles."""
    state = {}
    use_profile = profile or NLM_PROFILE
    cmds = {
        "slide_deck":  ["slides", "create", nb_id, "--focus", topic, "--confirm", "--profile", use_profile],
        "infographic": ["infographic", "create", nb_id, "--focus", topic, "--confirm", "--profile", use_profile],
        "mind_map":    ["mindmap", "create", nb_id, "--confirm", "--profile", use_profile],
    }
    for artifact, cmd in cmds.items():
        ok, out = run_nlm(cmd, timeout=60)
        if ok:
            state[artifact] = "triggered"
            print(f"[scheduler] NLM {artifact} triggered (profile={use_profile})")
        elif "error code 8" in out.lower() or "rate limited" in out.lower():
            state[artifact] = "rate_limited"
            print(f"[scheduler] NLM {artifact} rate-limited (code 8) — skipping poller")
        else:
            state[artifact] = "failed"
            print(f"[scheduler] NLM {artifact} failed: {out[:80]}")
    triggered = [k for k, v in state.items() if v == "triggered"]
    skipped   = [k for k, v in state.items() if v != "triggered"]
    print(f"[scheduler] NLM visuals: triggered={triggered} skipped={skipped}")
    return state


def _update_nlm_artifact_status(log_page_id: str, artifacts_state: dict):
    """Write the full NLMArtifacts JSON back to the Content Log entry."""
    if not log_page_id:
        return
    notion_update_page(log_page_id, {
        "NLMArtifacts": {"rich_text": [{"text": {"content": json.dumps(artifacts_state)}}]}
    })


def nlm_poll_and_send(nb_id: str, artifact_type: str, topic: str,
                       token: str, log_page_id: str = "",
                       artifacts_state: dict = None, max_wait: int = 900):
    """Background thread: poll until artifact ready, download, upload to Slack.
    Writes artifact outcome (completed/failed/timeout) back to Notion Content Log."""
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
    state   = artifacts_state or {}
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
                                state[artifact_type] = "completed"
                            else:
                                slack_dm(token, f"{icon} *{topic}* — {artifact_type} ready in NotebookLM (download failed)\n🤖 Kamil")
                                state[artifact_type] = "download_failed"
                            _update_nlm_artifact_status(log_page_id, state)
                            return
                        elif status == "failed":
                            print(f"[scheduler] NLM {artifact_type} failed")
                            state[artifact_type] = "failed"
                            _update_nlm_artifact_status(log_page_id, state)
                            return
            except Exception:
                pass
        time.sleep(20)
        waited += 20

    print(f"[scheduler] NLM {artifact_type} timed out after {max_wait}s")
    state[artifact_type] = "timeout"
    _update_nlm_artifact_status(log_page_id, state)

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

def generate_caption(topic: str, track: str, score: int, reason: str,
                      nlm_insights: str = "") -> str:
    """Instagram/TikTok/Reels caption — conversational, visual-first."""
    insights_block = (
        f"\n\nKey insights from research (use these as the substance):\n{nlm_insights[:800]}"
        if nlm_insights else ""
    )
    prompt = (
        f"{_PLAYBOOK_SUMMARY}\n\n"
        f"Write a social media caption for a {track} post about: {topic}\n"
        f"Engagement score: {score}/100. Why trending: {reason}"
        f"{insights_block}\n\n"
        f"Rules:\n"
        f"- Under 150 words\n"
        f"- First line = scroll-stopping hook using delayed-answer technique (no emoji at start)\n"
        f"- Pick the ONE emotion this delivers (awe/longing/nostalgia/belonging) and write toward it\n"
        f"- 3-4 bullet points — each is a specific visual cue or concrete insight (no generalities)\n"
        f"- Include 'Save this' or 'Swipe to see' CTA — audience are visual learners\n"
        f"- End with a question to drive comments\n"
        f"- 4 relevant trending hashtags for {track}\n"
        f"- Sound like a practitioner talking to a friend, not a marketer\n"
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


def generate_linkedin_caption(topic: str, score: int, reason: str,
                               nlm_insights: str = "") -> str:
    """LinkedIn-specific post — professional, first-person, no Instagram tropes."""
    insights_block = (
        f"\n\nResearch insights to draw from (pick the 2-3 most surprising):\n{nlm_insights[:800]}"
        if nlm_insights else ""
    )
    prompt = (
        f"Write a LinkedIn post for a software engineer / tech professional audience about: {topic}\n"
        f"Why this is relevant right now: {reason}"
        f"{insights_block}\n\n"
        f"Hard rules — any violation means the post fails:\n"
        f"- Write in first person, as if you just experienced or learned this\n"
        f"- NO: 'In today's fast-paced world', 'Game changer', 'Excited to share', 'Delighted', 'Thrilled'\n"
        f"- NO: 'Swipe to see', 'Save this', 'Drop a like' — this is not Instagram\n"
        f"- NO bullet point lists — write in short paragraphs or punchy single-line breaks\n"
        f"- NO emojis as decoration — one at most if it genuinely adds meaning\n"
        f"- Opening line: a specific observation or fact, NOT a question\n"
        f"- Under 200 words\n"
        f"- End with a genuine question that invites professional discussion\n"
        f"- 3-4 relevant hashtags at the very end, on their own line\n"
        f"- Sound like a senior engineer writing a note to a colleague, not a content creator\n"
        f"Return ONLY the post text."
    )
    try:
        r = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--model", "claude-sonnet-4-6",
             "--print", "-p", prompt],
            capture_output=True, text=True, timeout=90,
        )
        post = r.stdout.strip()
        if len(post) > 30:
            return post
    except Exception as e:
        print(f"[scheduler] LinkedIn caption error: {e}")

    return f"{topic}\n\nThoughts on this? Would love to hear from others working in this space.\n\n#tech #software #engineering #AI"


def wait_for_nlm_infographic(nb_id: str, max_wait: int = 300) -> str | None:
    """Poll NLM studio until infographic is ready. Download and return local path, or None on timeout."""
    outfile = f"/tmp/nlm-{nb_id[:8]}-infographic-li.png"
    waited = 0
    while waited < max_wait:
        ok, out = run_nlm(["studio", "status", nb_id], timeout=30)
        if ok:
            try:
                for a in json.loads(out):
                    if a.get("type") == "infographic" and a.get("status") == "completed":
                        dl_ok, _ = run_nlm(
                            ["download", "infographic", nb_id, "--output", outfile],
                            timeout=120,
                        )
                        if dl_ok and Path(outfile).exists():
                            print(f"[scheduler] NLM infographic ready for LinkedIn: {outfile}")
                            return outfile
            except Exception:
                pass
        time.sleep(20)
        waited += 20
    print(f"[scheduler] NLM infographic timed out after {max_wait}s — posting LinkedIn text-only")
    return None

# ─── Vlog script ──────────────────────────────────────────────────────────────

def generate_vlog_script(topic: str, score: int, reason: str) -> str:
    prompt = (
        f"{_PLAYBOOK_SUMMARY}\n\n"
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

def _try_nlm_research_and_visuals(topic: str, profile: str) -> tuple[str | None, str, dict]:
    """Try to create/reuse an NLM notebook and trigger visuals using the given profile.

    Returns (nb_id, insights, artifacts_state) or (None, "", {}) on quota/failure.
    Temporarily overrides NLM_PROFILE for this call via a local wrapper.
    """
    orig = os.environ.get("NLM_PROFILE")
    os.environ["NLM_PROFILE"] = profile
    try:
        nb_id, had_sources = nlm_get_or_create_notebook(topic)
        if not nb_id:
            return None, "", {}
        if not had_sources:
            ok = nlm_research(nb_id, topic)
            if not ok:
                run_nlm(["delete", "notebook", nb_id, "--confirm"], timeout=30)
                return None, "", {}
        insights = nlm_query_for_content(nb_id, topic)
        if not insights:
            run_nlm(["delete", "notebook", nb_id, "--confirm"], timeout=30)
            return None, "", {}
        artifacts_state = nlm_trigger_visuals(nb_id, topic, profile=profile)
        return nb_id, insights, artifacts_state
    finally:
        if orig is None:
            os.environ.pop("NLM_PROFILE", None)
        else:
            os.environ["NLM_PROFILE"] = orig


def run_nlm_with_profile_fallback(token: str, topic: str, track: str) -> tuple[str | None, str, dict]:
    """Try work NLM profile, then personal profile. Returns (nb_id, insights, artifacts_state).

    If both profiles are quota-exhausted: DMs Kamal, returns (None, "", {}).
    Canva is NOT used as fallback — if both NLM accounts are out, we skip visuals.
    """
    for profile, label in [(NLM_PROFILE, "work"), (NLM_PROFILE_PERSONAL, "personal")]:
        print(f"[scheduler] Trying NLM profile: {label} ({profile})")
        nb_id, insights, artifacts_state = _try_nlm_research_and_visuals(topic, profile)
        if nb_id and insights:
            print(f"[scheduler] NLM {label} profile succeeded: notebook {nb_id[:8]}")
            return nb_id, insights, artifacts_state
        print(f"[scheduler] NLM {label} profile exhausted or failed")

    # Both profiles exhausted
    print(f"[scheduler] Both NLM profiles exhausted for '{topic}' — skipping visuals")
    slack_dm(token,
        f"⚠️ *Both NLM accounts quota-exhausted for {track}*\n"
        f"Topic: *{topic}*\n"
        f"Caption will still go out — no infographic today for this track.\n🤖 Kamil")
    return None, "", {}


# ─── Canva ───────────────────────────────────────────────────────────────────

def run_canva_designs(topic: str, copy: str, content_db_ref: str = "") -> dict:
    """Run kamil-canva-agent for all formats. Returns results dict."""
    if not CANVA_BRAND_KIT_ID:
        klog("canva_skip", msg="CANVA_BRAND_KIT_ID not set — skipping Canva designs")
        return {}
    try:
        result = subprocess.run(
            [
                sys.executable, str(CANVA_AGENT),
                "--topic", topic,
                "--copy", copy,
                "--brand-kit-id", CANVA_BRAND_KIT_ID,
                "--content-db-ref", content_db_ref,
            ],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            klog("canva_error", msg=result.stderr[:200])
            return {}
        return json.loads(result.stdout)
    except Exception as e:
        klog("canva_error", msg=str(e))
        return {}

# ─── Canva fallback from NLM insights ────────────────────────────────────────

def canva_infographic_from_nlm_insights(topic: str, track: str,
                                         nlm_insights: str, token: str) -> str | None:
    """Parse NLM insights text → extract hook + bullet points → generate Canva infographic.
    Returns local PNG path on success, None on failure.
    This is the fallback when NLM slides/infographic are rate-limited — the research
    content is still used, just rendered via Canva instead of NotebookLM."""
    if not nlm_insights:
        return None

    # Ask Claude to parse the raw NLM insights into structured hook + bullets
    parse_prompt = (
        f"Given this research text about '{topic}', extract:\n"
        f"1. hook: one scroll-stopping line (max 12 words, no emoji, delayed-answer technique)\n"
        f"2. insights: exactly 5 specific concrete facts/tips (max 12 words each, real numbers/names)\n"
        f"3. angle: one of awe/longing/nostalgia/belonging\n\n"
        f"Research text:\n{nlm_insights[:2000]}\n\n"
        f"Output ONLY valid JSON: {{\"hook\": str, \"insights\": [str x5], \"angle\": str}}"
    )
    try:
        r = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", parse_prompt],
            capture_output=True, text=True, timeout=60,
        )
        raw = r.stdout.strip()
        start, end = raw.find("{"), raw.rfind("}") + 1
        parsed = json.loads(raw[start:end]) if start >= 0 and end > start else {}
    except Exception as e:
        print(f"[scheduler] Canva: failed to parse NLM insights: {e}")
        return None

    hook     = parsed.get("hook", topic[:50])
    insights = parsed.get("insights", [nlm_insights[:100]])
    angle    = parsed.get("angle", "awe")

    if not insights:
        return None

    print(f"[scheduler] Canva fallback: generating infographic for '{topic}' with {len(insights)} insights")

    outfile = f"/tmp/canva-infographic-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    try:
        result = canva_generate_infographic(
            topic=topic,
            track=track,
            hook=hook,
            insights=insights,
            angle=angle,
            output_path=outfile,
        )
        if result.get("error"):
            print(f"[scheduler] Canva infographic error: {result['error'][:100]}")
            return None
        local = result.get("local_path") or ""
        if local and Path(local).exists():
            print(f"[scheduler] Canva infographic ready: {local}")
            return local
        # No local file but have export_url — DM the URL instead
        if result.get("export_url"):
            slack_dm(token,
                f"🖼️ *Canva infographic (NLM fallback):* {topic}\n"
                f"View: {result['export_url']}\n🤖 Kamil")
        return None
    except Exception as e:
        print(f"[scheduler] Canva infographic exception: {e}")
        return None


def _canva_fallback_thread(topic: str, track: str, nlm_insights: str,
                            token: str, artifacts: list):
    """Background thread: generate Canva infographic from NLM insights and upload to Slack."""
    local_path = canva_infographic_from_nlm_insights(topic, track, nlm_insights, token)
    if local_path and Path(local_path).exists():
        slack_upload(
            token, local_path,
            title=f"{topic} — infographic (Canva/NLM)",
            comment=(
                f"🖼️ *{topic}* — infographic\n"
                f"_(NLM rate-limited → generated via Canva using NLM research insights)_\n"
                f"🤖 Kamil"
            ),
        )
        print(f"[scheduler] Canva fallback uploaded to Slack: {local_path}")
    else:
        print(f"[scheduler] Canva fallback produced no file — skipping Slack upload")


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

    page_id, topic, post_type, score, reason, existing_nb_id = result
    print(f"[scheduler] Topic: {topic} ({score}/100)")

    slack_dm(token,
        f"🚀 *{track} pipeline started* — *{topic}*\n"
        f"Score: {score}/100 | {reason}\n"
        f"Checking NLM notebooks + generating...\n🤖 Kamil")

    # NLM pipeline — try work profile first, personal profile second, skip visuals if both exhausted
    # If Notion has a stored notebook ID, try to reuse it on the work profile first
    nlm_insights = ""
    artifacts_state = {}
    nb_id = None

    if existing_nb_id:
        count = nlm_get_source_count(existing_nb_id)
        print(f"[scheduler] Notion-stored NLM notebook {existing_nb_id[:8]} has {count} sources")
        if count > 0:
            nlm_insights = nlm_query_for_content(existing_nb_id, topic)
            if nlm_insights:
                # Existing notebooks were created on work profile
                artifacts_state = nlm_trigger_visuals(existing_nb_id, topic, profile=NLM_PROFILE)
                nb_id = existing_nb_id

    if not nb_id:
        nb_id, nlm_insights, artifacts_state = run_nlm_with_profile_fallback(token, topic, track)
        if not nb_id:
            klog_error("nlm_both_profiles_exhausted",
                       component="content-scheduler",
                       topic=topic, track=track, severity="warning")

    # Store NLM notebook ID back on the Content Calendar page for future runs
    if nb_id:
        notion_update_page(page_id, {"NLMNotebookID": {"rich_text": [{"text": {"content": nb_id}}]}})

    # Captions
    caption = generate_caption(topic, track, score, reason, nlm_insights)
    linkedin_caption = generate_linkedin_caption(topic, score, reason, nlm_insights) if track == "tech" else ""

    # LinkedIn (tech only) — wait for NLM infographic, text-only if not available
    li_result = ""
    if track == "tech":
        li_image = None
        if nb_id and artifacts_state.get("infographic") == "triggered":
            li_image = wait_for_nlm_infographic(nb_id, max_wait=300)
        li_result = post_linkedin(linkedin_caption, li_image)
        print(f"[scheduler] LinkedIn: {li_result}")

    # Mark Done in Notion Content Calendar
    notion_update_page(page_id, {
        "Status":         {"select":    {"name": "Done"}},
        "PostedDate":     {"date":      {"start": date.today().isoformat()}},
        "NLMNotebookID":  {"rich_text": [{"text": {"content": nb_id or ""}}]},
    })

    li_line = f"\n✅ Auto-posted to LinkedIn: {li_result}" if track == "tech" else ""
    nb_line = f"\n📓 NLM `{nb_id[:8]}...` — infographic + slides + mindmap delivering shortly" if nb_id else "\n⚠️ No NLM visuals (both accounts quota-exhausted)"
    li_section = f"\n\n*LinkedIn post (already live):*\n{linkedin_caption}" if linkedin_caption else ""

    slack_dm(token,
        f"📊 *{track.upper()} content ready — {topic}*\n"
        f"Score: {score}/100 — {reason}"
        f"{li_line}{nb_line}"
        f"{li_section}\n\n"
        f"*Instagram/TikTok caption:*\n{caption}\n\n"
        f"📱 Post to Instagram + TikTok\n🤖 Kamil")

    # Extract hashtags from caption for logging
    hashtag_line = " ".join(w for w in caption.split() if w.startswith("#"))
    vlog_angle = f"Behind the build: '{topic}'"

    # Log everything to Notion Content Log
    platforms = ["TikTok", "Instagram", "YouTube Shorts", "Facebook"]
    if track == "tech" and li_result and "✅" in li_result:
        platforms.append("LinkedIn")

    log_page_id = log_to_content_log(
        topic=topic, track=track, score=score, reason=reason,
        caption=caption, hashtags=hashtag_line, nb_id=nb_id or "",
        li_post_id=li_result if li_result and "urn:" in li_result else "",
        vlog_angle=linkedin_caption or vlog_angle, platforms=platforms,
        status="Posted" if li_result else ("Generated" if nb_id else "No visuals"),
        nlm_insights=nlm_insights,
        nlm_artifacts=artifacts_state,
        calendar_page_id=page_id,
    )

    # Write backlink from Content Calendar → Content Log
    if log_page_id:
        notion_update_page(page_id, {
            "ContentLogPageID": {"rich_text": [{"text": {"content": log_page_id}}]}
        })

    # Now launch background artifact pollers — they'll update NLMArtifacts as each
    # completes. NOT daemon threads: NLM render takes minutes, so the process must
    # NOT exit before these finish downloading + uploading to Slack. We return them
    # so run() can join() them before the process exits.
    poller_threads = []
    if nb_id and artifacts_state:
        # Only poll for artifacts that were actually triggered — skip rate_limited/failed
        to_poll = [a for a in ["slide_deck", "infographic", "mind_map"]
                   if artifacts_state.get(a) == "triggered"]
        for artifact in to_poll:
            th = threading.Thread(
                target=nlm_poll_and_send,
                args=(nb_id, artifact, topic, token),
                kwargs={"log_page_id": log_page_id, "artifacts_state": copy.deepcopy(artifacts_state)},
                daemon=False,
            )
            th.start()
            poller_threads.append(th)
        if to_poll:
            print(f"[scheduler] Spawned {len(to_poll)} poller(s) for: {to_poll}")
        with _POLLERS_LOCK:
            ARTIFACT_POLLERS.extend(poller_threads)

        # Canva fallback for rate-limited visual artifacts — uses NLM research content
        rate_limited = [a for a in ["slide_deck", "infographic"]
                        if artifacts_state.get(a) == "rate_limited"]
        if rate_limited and nlm_insights:
            print(f"[scheduler] NLM {rate_limited} rate-limited — running Canva fallback with NLM insights")
            canva_th = threading.Thread(
                target=_canva_fallback_thread,
                args=(topic, track, nlm_insights, token, rate_limited),
                daemon=False,
            )
            canva_th.start()
            with _POLLERS_LOCK:
                ARTIFACT_POLLERS.append(canva_th)

    klog("content_posted", component="content-scheduler",
         topic=topic, track=track, score=score,
         linkedin=bool(li_result), nlm=bool(nb_id))

    # Seed brain.db — Kamil learns from his own research, not just posts it
    if nb_id and nlm_insights:
        try:
            from brain_seed_from_content import seed_from_nlm_insights
            seed_from_nlm_insights(topic, track, nb_id, nlm_insights)
        except Exception as e:
            print(f"[scheduler] brain seed failed (non-fatal): {e}")

    return poller_threads


def run_vlog(token: str):
    print(f"[scheduler] === VLOG ===")
    run_trend_scan("vlog")

    result = pick_topic("vlog")
    if not result:
        slack_dm(token,
            "📅 *Vlog* — no Pending topics in Notion Content Calendar.\n"
            "Add topics with Track=vlog, Status=Pending\n🤖 Kamil")
        return

    page_id, topic, _, score, reason, _ = result
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

    # Log vlog to Content Log — get back page ID for backlink
    log_page_id = log_to_content_log(
        topic=topic, track="vlog", score=score, reason=reason,
        caption=script[:1800], hashtags="", nb_id="",
        li_post_id="", vlog_angle=script[:400],
        platforms=["TikTok", "Instagram", "YouTube Shorts", "Facebook"],
        status="Generated",
        calendar_page_id=page_id,
    )

    # Write backlink from Content Calendar → Content Log
    if log_page_id:
        notion_update_page(page_id, {
            "ContentLogPageID": {"rich_text": [{"text": {"content": log_page_id}}]}
        })

    klog("vlog_script", component="content-scheduler", topic=topic, score=score)

# ─── Main ─────────────────────────────────────────────────────────────────────

def run():
    """Run ALL 4 tracks every day in parallel — NLM gives 3 daily slots (painting uses Canva fallback)."""
    token = load_slack_token()
    print(f"[scheduler] Starting {datetime.now().isoformat()} — running fitness + tech + vlog + painting in parallel")

    fitness_thread = threading.Thread(target=run_fitness_or_tech, args=("fitness", token))
    tech_thread    = threading.Thread(target=run_fitness_or_tech, args=("tech", token))
    vlog_thread    = threading.Thread(target=run_vlog, args=(token,))
    painting_thread = threading.Thread(target=run_fitness_or_tech, args=("painting", token))

    fitness_thread.start()
    tech_thread.start()
    vlog_thread.start()
    painting_thread.start()

    fitness_thread.join()
    tech_thread.join()
    vlog_thread.join()
    painting_thread.join()

    # Wait for NLM artifact pollers (slides/infographic/mindmap) to finish
    # downloading + posting to Slack. Without this the process would exit and
    # kill them mid-render. Each poller self-bounds at max_wait (900s).
    with _POLLERS_LOCK:
        pollers = list(ARTIFACT_POLLERS)
    if pollers:
        print(f"[scheduler] Waiting on {len(pollers)} NLM artifact poller(s) to deliver to Slack...")
        for th in pollers:
            th.join()
        print(f"[scheduler] All artifact pollers finished")

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
