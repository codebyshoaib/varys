#!/usr/bin/env python3
"""
notebooklm_handler.py — {AGENT_NAME}'s NotebookLM integration.

Triggered when {{USER_NAME}} says:
  "nlm research [topic]"      → deep research + sources added to notebook
  "nlm podcast [topic]"       → audio overview (podcast) created
  "nlm slides [topic]"        → slide deck created
  "nlm mindmap [topic]"       → mindmap created
  "nlm quiz [topic]"          → quiz created
  "nlm ask [notebook] [q]"    → query existing notebook, get cited answer
  "nlm create [topic]"        → create new notebook on topic
  "nlm list"                  → list all notebooks

All results DMed back to {{USER_NAME}} on Slack.
Everything logged to the local telemetry log.
"""

import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from varys_log import klog, klog_error
from agent_config import cfg

AGENT_NAME = cfg("AGENT_NAME", "Varys")

VARYS_DIR  = Path(__file__).parent.parent.parent
SHOAIB_DM   = os.environ.get("USER_SLACK_DM", "")  # set USER_SLACK_DM in ~/.agent-config.json
SLACK_CFG  = Path.home() / ".claude" / "hooks" / ".slack"

# Default notebook fallback
DEFAULT_NOTEBOOK = os.environ.get("NLM_DEFAULT_NOTEBOOK", "")  # set in ~/.agent-config.json

# Notion NLM Registry — single source of truth for all notebooks
# Replace with your own Notion NLM Registry database ID (created by /setup)
NLM_REGISTRY_DS = "383902248f3d811d8cade9015921dc5d"
NOTION_API       = "https://api.notion.com/v1"

# Hardcoded fallback aliases (used only if Notion registry unreachable)
# After running /setup and creating notebooks, add your aliases here.
# Format: "alias": "notebooklm-notebook-uuid"
ALIASES = {
    # Example entries — replace with your own:
    # "my-research":   "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    # "my-project":    "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
}


# ---------------------------------------------------------------------------
# Notion NLM Registry helpers
# ---------------------------------------------------------------------------

def _notion_token() -> str:
    """Read Notion MCP token from env or .slack file fallback."""
    return os.environ.get("NOTION_TOKEN", "")


def registry_search(keywords: list[str]) -> list[dict]:
    """
    Search NLM Registry in Notion by keyword overlap against Tags + When to Use.
    Returns list of matching notebooks sorted by score descending.
    Falls back to empty list if Notion unreachable.
    """
    try:
        ok, out = run_nlm(["notebook", "list", "--json"], timeout=15)
        if not ok:
            return []
        all_nbs = {nb["id"]: nb for nb in json.loads(out)}
    except Exception:
        return []

    # Build registry from hardcoded ALIASES + known metadata
    # This is fast path — real Notion fetch happens only when MCP available
    registry = [
        {"id": nb_id, "alias": alias, "title": "", "tags": [], "when_to_use": ""}
        for alias, nb_id in ALIASES.items()
    ]

    # Score each entry by keyword overlap
    kw_lower = [k.lower() for k in keywords]
    scored = []
    for entry in registry:
        text = " ".join([
            entry.get("alias", ""),
            entry.get("title", ""),
            entry.get("when_to_use", ""),
            " ".join(entry.get("tags", [])),
        ]).lower()
        score = sum(1 for k in kw_lower if k in text)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored]


def registry_register(nb_id: str, title: str, domain: str, tags: list[str],
                      when_to_use: str, summary: str, source_count: int) -> bool:
    """
    Register a newly created notebook in the Notion NLM Registry.
    Called automatically after create_notebook() and deep_research().
    """
    try:
        notion_token = _notion_token()
        if not notion_token:
            # Log but don't fail — registry is best-effort
            klog("nlm_registry_skip", component="notebooklm",
                 action="register_skip", reason="no_notion_token", notebook_id=nb_id)
            return False

        page = {
            "parent": {"type": "database_id", "database_id": NLM_REGISTRY_DS.replace("-", "")},
            "properties": {
                "Title": {"title": [{"text": {"content": title}}]},
                "Notebook ID": {"rich_text": [{"text": {"content": nb_id}}]},
                "Alias": {"rich_text": [{"text": {"content": title.lower().replace(" ", "-")[:40]}}]},
                "Domain": {"select": {"name": domain}},
                "Tags": {"multi_select": [{"name": t} for t in tags[:10]]},
                "When to Use": {"rich_text": [{"text": {"content": when_to_use[:500]}}]},
                "Summary": {"rich_text": [{"text": {"content": summary[:500]}}]},
                "Source Count": {"number": source_count},
                "Active": {"checkbox": True},
                "Last Updated": {"date": {"start": datetime.now().strftime("%Y-%m-%d")}},
            },
        }

        data = json.dumps(page).encode()
        req = urllib.request.Request(
            f"{NOTION_API}/pages", data=data,
            headers={
                "Authorization": f"Bearer {notion_token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())
            klog("nlm_registry_register", component="notebooklm",
                 action="register", notebook_id=nb_id, title=title)
            return result.get("id") is not None
    except Exception as e:
        klog_error("nlm_registry_register_fail", component="notebooklm",
                   error=str(e), notebook_id=nb_id)
        return False


def registry_touch(nb_id: str) -> None:
    """Update Last Queried date for a notebook in the registry (best-effort)."""
    # Best-effort — no hard failure if this doesn't work
    try:
        klog("nlm_registry_touch", component="notebooklm",
             action="touch", notebook_id=nb_id)
    except Exception:
        pass


def load_token() -> str:
    if SLACK_CFG.exists():
        for line in SLACK_CFG.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def slack_dm(token: str, text: str) -> str:
    data = json.dumps({"channel": SHOAIB_DM, "text": text}).encode()
    req  = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", data=data,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("ts", "")
    except Exception:
        return ""


ARTIFACT_ICONS = {
    "audio":      "🎙️",
    "slide_deck": "📊",
    "video":      "🎬",
    "mind_map":   "🗺️",
    "report":     "📋",
    "flashcards": "🃏",
    "quiz":       "📝",
    "infographic":"🖼️",
    "data_table": "📈",
}

ARTIFACT_EXTS = {
    "audio":      ".m4a",
    "slide_deck": ".pdf",
    "video":      ".mp4",
    "mind_map":   ".json",
    "report":     ".md",
    "flashcards": ".txt",
    "quiz":       ".txt",
    "infographic":".png",
    "data_table": ".csv",
}

# Text artifacts we can post inline to Slack
TEXT_ARTIFACTS = {"flashcards", "quiz", "report", "mind_map", "data_table"}


NLM_PROFILE = os.environ.get("NLM_PROFILE", "work")  # set NLM_PROFILE env var to your NotebookLM profile name


# Commands that reject --profile; they use the global default profile.
_NO_PROFILE_CMDS = {"download", "studio"}


def _inject_profile(args: list[str]) -> list[str]:
    """Insert --profile <NLM_PROFILE> after the leading subcommand verbs, before
    positional values. Mirrors content-scheduler.py."""
    if "--profile" in args or "-p" in args:
        return args
    if args and args[0] in _NO_PROFILE_CMDS:
        return args
    i = 0
    while i < len(args):
        tok = args[i]
        if tok.startswith("-"):
            break
        if i >= 1 and (" " in tok or "-" in tok or "/" in tok or "." in tok):
            break
        i += 1
    return args[:i] + ["--profile", NLM_PROFILE] + args[i:]


def run_nlm(args: list[str], timeout: int = 180) -> tuple[bool, str]:
    """Run nlm CLI command. Returns (success, output)."""
    args = _inject_profile(args)
    try:
        result = subprocess.run(
            ["nlm"] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        out = result.stdout.strip() or result.stderr.strip()
        return result.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "Timed out — NotebookLM is taking too long. Try again."
    except Exception as e:
        return False, str(e)


def upload_file_to_slack(token: str, channel: str, filepath: str,
                          title: str, comment: str) -> bool:
    """Upload a file to Slack using files:write scope."""
    import urllib.parse
    try:
        with open(filepath, "rb") as f:
            file_data = f.read()

        # Step 1: get upload URL
        params = urllib.parse.urlencode({
            "filename": os.path.basename(filepath),
            "length": len(file_data),
        })
        req = urllib.request.Request(
            f"https://slack.com/api/files.getUploadURLExternal?{params}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())

        if not resp.get("ok"):
            return False

        upload_url = resp["upload_url"]
        file_id    = resp["file_id"]

        # Step 2: upload file bytes
        req2 = urllib.request.Request(upload_url, data=file_data, method="POST")
        req2.add_header("Content-Type", "application/octet-stream")
        with urllib.request.urlopen(req2, timeout=30) as r:
            pass

        # Step 3: complete upload + share to channel
        payload = json.dumps({
            "files":           [{"id": file_id, "title": title}],
            "channel_id":      channel,
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
        return result.get("ok", False)

    except Exception as e:
        print(f"[nlm] file upload error: {e}", file=sys.stderr)
        return False


def poll_and_post_artifact(nb_id: str, artifact_type: str,
                            token: str, channel: str,
                            label: str, max_wait: int = 600):
    """
    Background thread: polls until artifact is complete, downloads it,
    posts to Slack. This is how {AGENT_NAME} knows when it's done.
    """
    import time
    icon    = ARTIFACT_ICONS.get(artifact_type, "✅")
    ext     = ARTIFACT_EXTS.get(artifact_type, ".bin")
    outfile = f"/tmp/nlm_{nb_id[:8]}_{artifact_type}{ext}"
    waited  = 0
    poll_interval = 15  # seconds

    while waited < max_wait:
        # Check status
        ok, out = run_nlm(["status", "artifacts", nb_id, "--json"], timeout=30)
        if ok:
            try:
                artifacts = json.loads(out)
                for a in artifacts:
                    if a.get("type") == artifact_type:
                        status = a.get("status", "")
                        if status == "completed":
                            # Download it
                            dl_ok, dl_out = run_nlm(
                                ["download", artifact_type.replace("_", "-"),
                                 nb_id, "--output", outfile, "--no-progress"],
                                timeout=120
                            )
                            if dl_ok and os.path.exists(outfile):
                                _post_artifact_to_slack(
                                    token, channel, artifact_type,
                                    outfile, icon, label, nb_id
                                )
                            else:
                                # Download failed — post link instead
                                slack_dm(token,
                                    f"{icon} *{label}* ✅ ready in NotebookLM\n"
                                    f"_Open notebook to view/download_\n🕷️ {AGENT_NAME}")
                            return
                        elif status == "failed":
                            slack_dm(token,
                                f"{icon} *{label}* ⚠️ generation failed\n🕷️ {AGENT_NAME}")
                            return
            except Exception:
                pass

        time.sleep(poll_interval)
        waited += poll_interval

    klog_error("notebooklm_poll_timeout", component="notebooklm",
               action="poll_timeout", notebook_id=nb_id,
               artifact_type=artifact_type, waited_seconds=max_wait)
    slack_dm(token,
        f"{icon} *{label}* ⏱️ still generating after {max_wait//60}min — "
        f"check NotebookLM directly\n🕷️ {AGENT_NAME}")


def _post_artifact_to_slack(token: str, channel: str, artifact_type: str,
                              filepath: str, icon: str, label: str, nb_id: str):
    """Post a downloaded artifact to Slack — text inline, files as upload."""
    if artifact_type in TEXT_ARTIFACTS:
        # Read and format for Slack
        try:
            raw = open(filepath).read()
            try:
                data = json.loads(raw)
                # Format flashcards
                if artifact_type == "flashcards":
                    cards = data.get("cards", [])[:10]  # first 10
                    lines = [f"{icon} *{label}* ✅ ({len(data.get('cards',[]))} cards)\n"]
                    for i, c in enumerate(cards, 1):
                        lines.append(f"*Q{i}:* {c['front']}")
                        lines.append(f"*A:* {c['back']}\n")
                    lines.append(f"_({len(data.get('cards',[]))-10} more — full file at {filepath})_\n🕷️ {AGENT_NAME}")
                    slack_dm(token, "\n".join(lines))
                    return
                # Format quiz
                elif artifact_type == "quiz":
                    qs = data.get("questions", [])[:5]
                    lines = [f"{icon} *{label}* ✅\n"]
                    for i, q in enumerate(qs, 1):
                        lines.append(f"*Q{i}:* {q.get('question','')}")
                        opts = q.get("options", [])
                        for opt in opts:
                            lines.append(f"  • {opt}")
                        lines.append("")
                    lines.append(f"🕷️ {AGENT_NAME}")
                    slack_dm(token, "\n".join(lines))
                    return
                else:
                    content = str(data)[:1000]
            except Exception:
                content = raw[:1000]

            slack_dm(token, f"{icon} *{label}* ✅\n```{content}```\n🕷️ {AGENT_NAME}")

        except Exception as e:
            slack_dm(token, f"{icon} *{label}* ✅ (read error: {e})\n🕷️ {AGENT_NAME}")

    else:
        # Binary file (audio, video, image, pdf) — try upload
        uploaded = upload_file_to_slack(
            token, channel, filepath,
            title=label,
            comment=f"{icon} *{label}* — generated by NotebookLM from Taleemabad harness data\n🕷️ {AGENT_NAME}"
        )
        if not uploaded:
            # No files:write scope — post instructions
            slack_dm(token,
                f"{icon} *{label}* ✅ ready!\n"
                f"_File upload needs `files:write` scope on the Varys Slack app._\n"
                f"Fix: api.slack.com/apps → Varys → OAuth Scopes → add `files:write` → Reinstall\n"
                f"File saved at: `{filepath}`\n🕷️ {AGENT_NAME}")


def resolve_notebook(name: str) -> str:
    """Resolve notebook name/alias to ID. Checks registry first, then nlm list."""
    name_lower = name.lower().strip()
    # Direct alias match
    if name_lower in ALIASES:
        return ALIASES[name_lower]
    # UUID passthrough
    if re.match(r'^[0-9a-f-]{36}$', name_lower):
        return name_lower
    # UUID prefix (first 8 chars)
    if re.match(r'^[0-9a-f]{8}$', name_lower):
        ok, out = run_nlm(["notebook", "list", "--json"], timeout=15)
        if ok:
            try:
                for nb in json.loads(out):
                    if nb["id"].startswith(name_lower):
                        return nb["id"]
            except Exception:
                pass
    # Registry keyword search (tags + when_to_use)
    hits = registry_search([name_lower])
    if hits:
        return hits[0]["id"]
    # Title substring search via nlm list
    ok, out = run_nlm(["notebook", "list", "--json"], timeout=15)
    if ok:
        try:
            for nb in json.loads(out):
                if name_lower in nb.get("title", "").lower():
                    return nb["id"]
        except Exception:
            pass
    return DEFAULT_NOTEBOOK


def list_notebooks(token: str):
    ok, out = run_nlm(["list", "notebooks", "--json"])
    if not ok:
        slack_dm(token, f"⚠️ Could not list notebooks: {out[:200]}\n🕷️ {AGENT_NAME}")
        return

    try:
        notebooks = json.loads(out)
        lines = ["📚 *Your NotebookLM notebooks:*\n"]
        for nb in notebooks:
            title   = nb.get("title") or "Untitled"
            sources = nb.get("source_count", 0)
            nid     = nb.get("id", "")[:8]
            lines.append(f"• *{title}* — {sources} sources `[{nid}...]`")
        lines.append(f"\n_Say \"nlm ask [notebook name] [question]\" to query one._\n🕷️ {AGENT_NAME}")
        slack_dm(token, "\n".join(lines))
    except Exception:
        slack_dm(token, f"Notebooks:\n{out[:500]}\n🕷️ {AGENT_NAME}")

    klog("notebooklm_list", component="notebooklm", action="list")


def ask_notebook(notebook_ref: str, question: str, token: str):
    """Query a notebook and get a cited answer. Updates Last Queried in registry."""
    nb_id = resolve_notebook(notebook_ref)
    slack_dm(token, f"🔍 Querying NotebookLM: _{question[:80]}_...\n🕷️ {AGENT_NAME}")

    ok, out = run_nlm(["notebook", "query", nb_id, question, "--json",
                       "--profile", "default"], timeout=120)

    if ok:
        try:
            data   = json.loads(out)
            answer = data.get("value", {}).get("answer", out)[:1500]
        except Exception:
            answer = out[:1500]
        slack_dm(token, f"🧠 *NotebookLM answer:*\n\n{answer}\n\n🕷️ {AGENT_NAME}")
        registry_touch(nb_id)
        klog("notebooklm_query", component="notebooklm",
             action="ask", notebook=nb_id, question=question[:100])
    else:
        slack_dm(token, f"⚠️ Query failed: {out[:300]}\n🕷️ {AGENT_NAME}")


def create_notebook(topic: str, token: str) -> str | None:
    """Create a new notebook on a topic, do deep research, return notebook ID."""
    slack_dm(token, f"📓 Creating NotebookLM notebook: *{topic}*...\n🕷️ {AGENT_NAME}")

    ok, out = run_nlm(["notebook", "create", topic, "--json"], timeout=60)
    if not ok:
        slack_dm(token, f"⚠️ Could not create notebook: {out[:200]}\n🕷️ {AGENT_NAME}")
        return None

    try:
        nb_id = json.loads(out).get("id") or json.loads(out).get("notebook_id")
    except Exception:
        # Try to extract UUID from output
        m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', out)
        nb_id = m.group(0) if m else None

    if nb_id:
        klog("notebooklm_create", component="notebooklm",
             action="create", topic=topic, notebook_id=nb_id)
        # Auto-register in Notion NLM Registry
        registry_register(
            nb_id=nb_id,
            title=topic,
            domain="research",
            tags=[],
            when_to_use=f"Ask when: questions about {topic}",
            summary=f"Notebook created for research on: {topic}",
            source_count=0,
        )
    return nb_id


def _extract_notebook_id(text: str) -> str | None:
    """Pull the notebook UUID out of `nlm research start` text output.

    `research start` has no --json; it prints a human-readable block with a
    `Notebook ID: <uuid>` line when creating a new notebook. Prefer that line,
    then fall back to the first UUID anywhere in the output.
    """
    m = re.search(
        r'Notebook ID:\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
        text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        text, re.IGNORECASE)
    return m.group(0) if m else None


def research_and_populate(topic: str, token: str, notebook_id: str = None,
                          mode: str = "deep") -> str | None:
    """Create-or-reuse a notebook AND populate it with web sources in one call.

    This is the correct prerequisite for any artifact: an empty notebook has no
    sources and generates nothing. Uses `nlm research start` with --auto-import,
    which waits for research to finish AND imports the discovered sources.

    - No notebook_id  → research into a NEW notebook (--title), returns its id.
    - notebook_id set → add sources to that EXISTING notebook (--notebook-id).

    Returns the populated notebook id, or None on failure.
    """
    # deep ≈ 5min + import; give generous headroom. fast ≈ 30s.
    timeout = 600 if mode == "deep" else 180

    args = ["research", "start", topic, "--mode", mode, "--auto-import"]
    if notebook_id:
        args += ["--notebook-id", notebook_id]
    else:
        args += ["--title", topic]

    ok, out = run_nlm(args, timeout=timeout)
    if not ok:
        klog_error("notebooklm_research_fail", component="notebooklm",
                   topic=topic, error=out[:300])
        return None

    nb_id = notebook_id or _extract_notebook_id(out)
    if nb_id:
        klog("notebooklm_research", component="notebooklm",
             action="research", topic=topic, notebook=nb_id, mode=mode)
        registry_register(
            nb_id=nb_id,
            title=topic,
            domain="research",
            tags=[],
            when_to_use=f"Ask when: questions about {topic}",
            summary=f"Notebook researched on: {topic}",
            source_count=0,
        )
    else:
        klog_error("notebooklm_research_no_id", component="notebooklm",
                   topic=topic, output=out[:300])
    return nb_id


def deep_research(topic: str, token: str, notebook_id: str = None):
    """Run deep research on a topic, populate the notebook, DM summary."""
    slack_dm(token,
        f"🔬 Running deep research on *{topic}*... (this takes ~5 min)\n🕷️ {AGENT_NAME}")

    nb_id = research_and_populate(topic, token, notebook_id=notebook_id, mode="deep")

    if nb_id:
        slack_dm(token,
            f"✅ *Research complete:* {topic}\n\n"
            f"_Say \"nlm ask {nb_id[:8]} [question]\" to query the results._\n🕷️ {AGENT_NAME}")
    else:
        slack_dm(token,
            f"⚠️ Research failed for *{topic}* — couldn't populate a notebook.\n🕷️ {AGENT_NAME}")


def _resolve_populated_notebook(topic: str, token: str,
                                notebook_ref: str = None) -> str | None:
    """Return a notebook id that actually has sources to generate from.

    - notebook_ref given → resolve it (existing notebook, assumed populated).
    - topic given, no ref → research-and-populate a NEW notebook (deep mode),
      because an empty notebook generates nothing.
    - neither → fall back to DEFAULT_NOTEBOOK if configured.
    """
    if notebook_ref:
        return resolve_notebook(notebook_ref)
    if topic:
        slack_dm(token,
            f"🔬 No notebook given — researching *{topic}* first to gather "
            f"sources (~5 min), then generating...\n🕷️ {AGENT_NAME}")
        nb_id = research_and_populate(topic, token, mode="deep")
        if nb_id:
            return nb_id
        # Research failed — fall through to default if any.
    return DEFAULT_NOTEBOOK or None


def _create_artifact(artifact_cmd: list, artifact_type: str, label: str,
                      topic: str, token: str, nb_id: str):
    """Generic: trigger artifact creation then background-poll until done."""
    icon = ARTIFACT_ICONS.get(artifact_type, "✅")
    slack_dm(token,
        f"{icon} Generating *{label}*...\n"
        f"_I'll post it here when ready._\n🕷️ {AGENT_NAME}")

    ok, out = run_nlm(artifact_cmd, timeout=60)
    if ok or True:  # NotebookLM often returns non-zero even when triggered
        klog(f"notebooklm_{artifact_type}", component="notebooklm",
             action=artifact_type, topic=topic, notebook=nb_id)
        import threading
        # Deep-research + artifact generation can exceed the 10min default;
        # give the poller 15min so it doesn't time out before the artifact lands.
        threading.Thread(
            target=poll_and_post_artifact,
            args=(nb_id, artifact_type, token, SHOAIB_DM, f"{label}: {topic}"),
            kwargs={"max_wait": 900},
            daemon=True,
        ).start()


def create_podcast(topic: str, token: str, notebook_ref: str = None,
                   fmt: str = "deep_dive"):
    """Create audio overview (podcast) from a populated notebook."""
    nb_id = _resolve_populated_notebook(topic, token, notebook_ref)
    if not nb_id:
        slack_dm(token,
            f"⚠️ Couldn't get a populated notebook for the podcast.\n🕷️ {AGENT_NAME}")
        return

    cmd = ["audio", "create", nb_id, "--format", fmt, "--confirm"]
    if topic:
        cmd += ["--focus", topic]
    _create_artifact(cmd, "audio", "Podcast", topic or "notebook", token, nb_id)


def create_slides(topic: str, token: str, notebook_ref: str = None):
    nb_id = _resolve_populated_notebook(topic, token, notebook_ref)
    if not nb_id:
        slack_dm(token,
            f"⚠️ Couldn't get a populated notebook for the slide deck.\n🕷️ {AGENT_NAME}")
        return
    cmd = ["slides", "create", nb_id, "--confirm"]
    if topic:
        cmd += ["--focus", topic]
    _create_artifact(cmd, "slide_deck", "Slide Deck", topic, token, nb_id)


def create_infographic(topic: str, token: str, notebook_ref: str = None):
    nb_id = _resolve_populated_notebook(topic, token, notebook_ref)
    if not nb_id:
        slack_dm(token,
            f"⚠️ Couldn't get a populated notebook for the infographic.\n🕷️ {AGENT_NAME}")
        return
    cmd = ["infographic", "create", nb_id,
           "--detail", "standard", "--orientation", "landscape", "--confirm"]
    if topic:
        cmd += ["--focus", topic]
    _create_artifact(cmd, "infographic", "Infographic", topic, token, nb_id)


def create_mindmap(topic: str, token: str, notebook_ref: str = None):
    nb_id = _resolve_populated_notebook(topic, token, notebook_ref)
    if not nb_id:
        slack_dm(token,
            f"⚠️ Couldn't get a populated notebook for the mind map.\n🕷️ {AGENT_NAME}")
        return
    # mindmap has NO --focus option; --title is its only topic-ish flag.
    cmd = ["mindmap", "create", nb_id, "--confirm"]
    if topic:
        cmd += ["--title", topic]
    _create_artifact(cmd, "mind_map", "Mind Map", topic, token, nb_id)


def create_quiz(topic: str, token: str, notebook_ref: str = None):
    nb_id = _resolve_populated_notebook(topic, token, notebook_ref)
    if not nb_id:
        slack_dm(token,
            f"⚠️ Couldn't get a populated notebook for the quiz.\n🕷️ {AGENT_NAME}")
        return
    cmd = ["quiz", "create", nb_id, "--confirm"]
    if topic:
        cmd += ["--focus", topic]
    _create_artifact(cmd, "quiz", "Quiz", topic, token, nb_id)


def handle(text: str, token: str):
    """
    Parse Shoaib's message and route to the right NotebookLM action.

    Trigger patterns (case-insensitive):
      nlm list
      nlm ask [notebook] [question]
      nlm research [topic]
      nlm create [topic]
      nlm podcast [topic]
      nlm slides [topic]
      nlm mindmap [topic]
      nlm quiz [topic]
      nlm brief [topic]        → short podcast
      nlm debate [topic]       → debate format podcast
    """
    text_lower = text.lower().strip()

    # Strip "nlm" prefix
    body = re.sub(r'^nlm\s*', '', text_lower, flags=re.IGNORECASE).strip()
    body_orig = re.sub(r'^nlm\s*', '', text, flags=re.IGNORECASE).strip()

    if body.startswith("list"):
        list_notebooks(token)

    elif body.startswith("ask"):
        # "ask [notebook_ref] [question]" or "ask [question]"
        rest  = body_orig[3:].strip()
        parts = rest.split(" ", 2)
        if len(parts) >= 2:
            # Check if first word is a notebook ref (alias or short UUID)
            first = parts[0].lower()
            if first in ALIASES or re.match(r'^[0-9a-f]{8}', first):
                notebook_ref = parts[0]
                question     = " ".join(parts[1:])
            else:
                notebook_ref = DEFAULT_NOTEBOOK
                question     = rest
        else:
            notebook_ref = DEFAULT_NOTEBOOK
            question     = rest
        ask_notebook(notebook_ref, question, token)

    elif body.startswith("research"):
        topic = body_orig[8:].strip()
        deep_research(topic, token)

    elif body.startswith("create"):
        topic = body_orig[6:].strip()
        nb_id = create_notebook(topic, token)
        if nb_id:
            slack_dm(token,
                f"✅ *Notebook created:* {topic}\n"
                f"ID: `{nb_id}`\n"
                f"_Say \"nlm research {topic}\" to populate it with sources._\n🕷️ {AGENT_NAME}")

    elif body.startswith("podcast") or body.startswith("audio"):
        topic = re.sub(r'^(?:podcast|audio)\s*', '', body_orig, flags=re.IGNORECASE).strip()
        create_podcast(topic, token, fmt="deep_dive")

    elif body.startswith("brief"):
        topic = body_orig[5:].strip()
        create_podcast(topic, token, fmt="brief")

    elif body.startswith("debate"):
        topic = body_orig[6:].strip()
        create_podcast(topic, token, fmt="debate")

    elif body.startswith("slides"):
        topic = body_orig[6:].strip()
        create_slides(topic, token)

    elif body.startswith("infographic") or body.startswith("visual"):
        topic = re.sub(r'^(?:infographic|visual)\s*', '', body_orig,
                       flags=re.IGNORECASE).strip()
        create_infographic(topic, token)

    elif body.startswith("mindmap"):
        topic = body_orig[7:].strip()
        create_mindmap(topic, token)

    elif body.startswith("quiz"):
        topic = body_orig[4:].strip()
        create_quiz(topic, token)

    else:
        # Unknown — show help
        slack_dm(token,
            "🧠 *NotebookLM commands:*\n\n"
            "• `nlm list` — show your notebooks\n"
            "• `nlm ask [topic] [question]` — query a notebook\n"
            "• `nlm research [topic]` — deep research, add sources\n"
            "• `nlm create [topic]` — create new notebook\n"
            "• `nlm podcast [topic]` — generate audio podcast\n"
            "• `nlm brief [topic]` — short podcast\n"
            "• `nlm debate [topic]` — debate format podcast\n"
            "• `nlm slides [topic]` — create slide deck\n"
            "• `nlm infographic [topic]` — create infographic\n"
            "• `nlm mindmap [topic]` — create mindmap\n"
            "• `nlm quiz [topic]` — create quiz\n\n"
            f"🕷️ {AGENT_NAME}")


def is_notebooklm_command(text: str) -> bool:
    """True if message starts with 'nlm' trigger."""
    return bool(re.match(r'^\s*nlm\s+\w', text, re.IGNORECASE))


def _resolve_post_channel(token: str) -> str:
    """Where NLM artifacts post: explicit NLM_POST_CHANNEL env, else SHOAIB_DM, else open user's DM."""
    ch = os.environ.get("NLM_POST_CHANNEL", "") or SHOAIB_DM
    if ch:
        return ch
    uid = os.environ.get("USER_SLACK_ID", "")
    if not uid:
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from agent_config import cfg as _cfg
            uid = _cfg("USER_SLACK_ID", "")
        except Exception:
            uid = ""
    if uid and token:
        try:
            data = json.dumps({"users": uid}).encode()
            req  = urllib.request.Request(
                "https://slack.com/api/conversations.open", data=data,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read()).get("channel", {}).get("id", "")
        except Exception:
            return ""
    return ""


if __name__ == "__main__":
    # Detached-process entry: `notebooklm_handler.py --handle "nlm slides <topic>"`
    # Used by slack-worker.py so natural-language NLM requests actually generate.
    if len(sys.argv) >= 3 and sys.argv[1] == "--handle":
        import threading
        token = load_token()
        SHOAIB_DM = _resolve_post_channel(token)  # rebind global used by slack_dm + pollers
        handle(sys.argv[2], token)
        # handle() spawns daemon poller threads (2–5 min). Keep this process alive
        # until they finish — otherwise sys.exit kills them before the artifact posts.
        _mt = threading.main_thread()
        for _t in threading.enumerate():
            if _t is not _mt:
                _t.join()
        sys.exit(0)

    token = load_token()
    # Quick smoke test
    print("Testing NotebookLM connection...")
    ok, out = run_nlm(["login", "--check"])
    print(f"Auth: {'✅' if ok else '❌'} {out[:100]}")

    ok, out = run_nlm(["list", "notebooks", "--json"])
    if ok:
        notebooks = json.loads(out)
        print(f"Notebooks: {len(notebooks)}")
        for nb in notebooks:
            print(f"  - {nb.get('title','Untitled')} ({nb.get('source_count',0)} sources)")
