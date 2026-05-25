#!/usr/bin/env python3
"""
notebooklm_handler.py — Kamil's NotebookLM integration.

Triggered when Kamal says:
  "nlm research [topic]"      → deep research + sources added to notebook
  "nlm podcast [topic]"       → audio overview (podcast) created
  "nlm slides [topic]"        → slide deck created
  "nlm mindmap [topic]"       → mindmap created
  "nlm quiz [topic]"          → quiz created
  "nlm ask [notebook] [q]"    → query existing notebook, get cited answer
  "nlm create [topic]"        → create new notebook on topic
  "nlm list"                  → list all notebooks

All results DMed back to Kamal on Slack.
Everything logged to Axiom.
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
from kamil_log import klog, klog_error

KAMIL_DIR  = Path(__file__).parent.parent.parent
KAMAL_DM   = "D0B415M06SK"
SLACK_CFG  = Path.home() / ".claude" / "hooks" / ".slack"

# Default notebook — Instagram one has content, use as fallback
DEFAULT_NOTEBOOK = "76624bf5-82ce-4f11-b379-e07f308c6c4a"

# Notebook aliases Kamil remembers
ALIASES = {
    "instagram": "76624bf5-82ce-4f11-b379-e07f308c6c4a",
    "work":      "a2e6473a-bc3c-4737-b1b9-3c67e1fb94ae",
    "taleemabad": "a03e5a92-d706-4ffb-9bd7-a3498dc7779d",
    "harness":    "a03e5a92-d706-4ffb-9bd7-a3498dc7779d",
    "reddit":     "1a76701b-9e16-411f-9c2e-ea73223a8695",
}


def load_token() -> str:
    if SLACK_CFG.exists():
        for line in SLACK_CFG.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def slack_dm(token: str, text: str) -> str:
    data = json.dumps({"channel": KAMAL_DM, "text": text}).encode()
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


def run_nlm(args: list[str], timeout: int = 180) -> tuple[bool, str]:
    """Run nlm CLI command. Returns (success, output)."""
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
    posts to Slack. This is how Kamil knows when it's done.
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
                                    f"_Open notebook to view/download_\n🤖 Kamil")
                            return
                        elif status == "failed":
                            slack_dm(token,
                                f"{icon} *{label}* ⚠️ generation failed\n🤖 Kamil")
                            return
            except Exception:
                pass

        time.sleep(poll_interval)
        waited += poll_interval

    slack_dm(token,
        f"{icon} *{label}* ⏱️ still generating after {max_wait//60}min — "
        f"check NotebookLM directly\n🤖 Kamil")


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
                    lines.append(f"_({len(data.get('cards',[]))-10} more — full file at {filepath})_\n🤖 Kamil")
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
                    lines.append("🤖 Kamil")
                    slack_dm(token, "\n".join(lines))
                    return
                else:
                    content = str(data)[:1000]
            except Exception:
                content = raw[:1000]

            slack_dm(token, f"{icon} *{label}* ✅\n```{content}```\n🤖 Kamil")

        except Exception as e:
            slack_dm(token, f"{icon} *{label}* ✅ (read error: {e})\n🤖 Kamil")

    else:
        # Binary file (audio, video, image, pdf) — try upload
        uploaded = upload_file_to_slack(
            token, channel, filepath,
            title=label,
            comment=f"{icon} *{label}* — generated by NotebookLM from Taleemabad harness data\n🤖 Kamil"
        )
        if not uploaded:
            # No files:write scope — post instructions
            slack_dm(token,
                f"{icon} *{label}* ✅ ready!\n"
                f"_File upload needs `files:write` scope on the Kamil Slack app._\n"
                f"Fix: api.slack.com/apps → Kamil → OAuth Scopes → add `files:write` → Reinstall\n"
                f"File saved at: `{filepath}`\n🤖 Kamil")


def resolve_notebook(name: str) -> str:
    """Resolve notebook name/alias to ID."""
    name_lower = name.lower().strip()
    if name_lower in ALIASES:
        return ALIASES[name_lower]
    # If it looks like a UUID already
    if re.match(r'^[0-9a-f-]{36}$', name_lower):
        return name_lower
    # Search by title
    ok, out = run_nlm(["list", "notebooks", "--json"])
    if ok:
        try:
            notebooks = json.loads(out)
            for nb in notebooks:
                if name_lower in nb.get("title", "").lower():
                    return nb["id"]
        except Exception:
            pass
    return DEFAULT_NOTEBOOK


def list_notebooks(token: str):
    ok, out = run_nlm(["list", "notebooks", "--json"])
    if not ok:
        slack_dm(token, f"⚠️ Could not list notebooks: {out[:200]}\n🤖 Kamil")
        return

    try:
        notebooks = json.loads(out)
        lines = ["📚 *Your NotebookLM notebooks:*\n"]
        for nb in notebooks:
            title   = nb.get("title") or "Untitled"
            sources = nb.get("source_count", 0)
            nid     = nb.get("id", "")[:8]
            lines.append(f"• *{title}* — {sources} sources `[{nid}...]`")
        lines.append("\n_Say \"nlm ask [notebook name] [question]\" to query one._\n🤖 Kamil")
        slack_dm(token, "\n".join(lines))
    except Exception:
        slack_dm(token, f"Notebooks:\n{out[:500]}\n🤖 Kamil")

    klog("notebooklm_list", component="notebooklm", action="list")


def ask_notebook(notebook_ref: str, question: str, token: str):
    """Query a notebook and get a cited answer."""
    nb_id = resolve_notebook(notebook_ref)
    slack_dm(token, f"🔍 Querying NotebookLM: _{question[:80]}_...\n🤖 Kamil")

    ok, out = run_nlm(["query", "notebook", nb_id, question, "--json"])

    if ok:
        try:
            data   = json.loads(out)
            answer = data.get("value", {}).get("answer", out)[:1500]
        except Exception:
            answer = out[:1500]
        slack_dm(token, f"🧠 *NotebookLM answer:*\n\n{answer}\n\n🤖 Kamil")
        klog("notebooklm_query", component="notebooklm",
             action="ask", notebook=nb_id, question=question[:100])
    else:
        slack_dm(token, f"⚠️ Query failed: {out[:300]}\n🤖 Kamil")


def create_notebook(topic: str, token: str) -> str | None:
    """Create a new notebook on a topic, do deep research, return notebook ID."""
    slack_dm(token, f"📓 Creating NotebookLM notebook: *{topic}*...\n🤖 Kamil")

    ok, out = run_nlm(["notebook", "create", "--json", "--title", topic], timeout=60)
    if not ok:
        slack_dm(token, f"⚠️ Could not create notebook: {out[:200]}\n🤖 Kamil")
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
    return nb_id


def deep_research(topic: str, token: str, notebook_id: str = None):
    """Run deep research on a topic, add sources to notebook, DM summary."""
    nb_id = notebook_id
    if not nb_id:
        nb_id = create_notebook(topic, token)
        if not nb_id:
            return

    slack_dm(token, f"🔬 Running deep research on *{topic}*... (this takes 1-3 min)\n🤖 Kamil")

    ok, out = run_nlm(["research", "start", nb_id,
                        "--query", topic, "--confirm"], timeout=240)

    if ok:
        slack_dm(token,
            f"✅ *Research complete:* {topic}\n\n"
            f"{out[:800]}\n\n"
            f"_Say \"nlm ask {nb_id[:8]} [question]\" to query the results._\n🤖 Kamil")
        klog("notebooklm_research", component="notebooklm",
             action="research", topic=topic, notebook=nb_id)
    else:
        slack_dm(token, f"⚠️ Research failed: {out[:300]}\n🤖 Kamil")


def create_podcast(topic: str, token: str, notebook_ref: str = None,
                   fmt: str = "deep_dive"):
    """Create audio overview (podcast) from notebook."""
    nb_id = resolve_notebook(notebook_ref) if notebook_ref else DEFAULT_NOTEBOOK
    if topic and not notebook_ref:
        new_id = create_notebook(topic, token)
        if new_id:
            nb_id = new_id

    slack_dm(token, f"🎙️ Generating podcast for *{topic or 'notebook'}*...\n_I'll post it here when it's ready (2-5 min)_\n🤖 Kamil")

    ok, out = run_nlm([
        "audio", "create", nb_id, "--format", fmt,
        "--focus", topic if topic else "", "--confirm",
    ], timeout=60)  # just trigger it, don't wait

    if ok or "started" in out.lower() or "creating" in out.lower():
        klog("notebooklm_podcast", component="notebooklm",
             action="podcast", topic=topic, notebook=nb_id, format=fmt)
        # Background poller — posts to Slack when done
        import threading
        threading.Thread(
            target=poll_and_post_artifact,
            args=(nb_id, "audio", token, KAMAL_DM, f"Podcast: {topic or 'notebook'}"),
            daemon=True,
        ).start()
    else:
        slack_dm(token, f"⚠️ Podcast failed to start: {out[:300]}\n🤖 Kamil")


def _create_artifact(artifact_cmd: list, artifact_type: str, label: str,
                      topic: str, token: str, nb_id: str):
    """Generic: trigger artifact creation then background-poll until done."""
    icon = ARTIFACT_ICONS.get(artifact_type, "✅")
    slack_dm(token,
        f"{icon} Generating *{label}*...\n"
        f"_I'll post it here when ready._\n🤖 Kamil")

    ok, out = run_nlm(artifact_cmd, timeout=60)
    if ok or True:  # NotebookLM often returns non-zero even when triggered
        klog(f"notebooklm_{artifact_type}", component="notebooklm",
             action=artifact_type, topic=topic, notebook=nb_id)
        import threading
        threading.Thread(
            target=poll_and_post_artifact,
            args=(nb_id, artifact_type, token, KAMAL_DM, f"{label}: {topic}"),
            daemon=True,
        ).start()


def create_slides(topic: str, token: str, notebook_ref: str = None):
    nb_id = resolve_notebook(notebook_ref) if notebook_ref else DEFAULT_NOTEBOOK
    if topic and not notebook_ref:
        new_id = create_notebook(topic, token)
        if new_id:
            nb_id = new_id
    _create_artifact(
        ["slides", "create", nb_id, "--focus", topic, "--confirm"],
        "slide_deck", "Slide Deck", topic, token, nb_id
    )


def create_mindmap(topic: str, token: str, notebook_ref: str = None):
    nb_id = resolve_notebook(notebook_ref) if notebook_ref else DEFAULT_NOTEBOOK
    if topic and not notebook_ref:
        new_id = create_notebook(topic, token)
        if new_id:
            nb_id = new_id
    _create_artifact(
        ["mindmap", "create", nb_id, "--focus", topic, "--confirm"],
        "mind_map", "Mind Map", topic, token, nb_id
    )


def create_quiz(topic: str, token: str, notebook_ref: str = None):
    nb_id = resolve_notebook(notebook_ref) if notebook_ref else DEFAULT_NOTEBOOK
    if topic and not notebook_ref:
        new_id = create_notebook(topic, token)
        if new_id:
            nb_id = new_id
    _create_artifact(
        ["quiz", "create", nb_id, "--focus", topic, "--confirm"],
        "quiz", "Quiz", topic, token, nb_id
    )


def handle(text: str, token: str):
    """
    Parse Kamal's message and route to the right NotebookLM action.

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
                f"_Say \"nlm research {topic}\" to populate it with sources._\n🤖 Kamil")

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
            "• `nlm mindmap [topic]` — create mindmap\n"
            "• `nlm quiz [topic]` — create quiz\n\n"
            "🤖 Kamil")


def is_notebooklm_command(text: str) -> bool:
    """True if message starts with 'nlm' trigger."""
    return bool(re.match(r'^\s*nlm\s+\w', text, re.IGNORECASE))


if __name__ == "__main__":
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
