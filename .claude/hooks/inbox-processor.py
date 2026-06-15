#!/usr/bin/env python3
"""
inbox-processor.py — Process queued messages for Varys.

Reads ~/varys-inbox/*.json, spins a claude session per message,
posts response to Shoaib via Slack DM, marks message as done.

Run manually:
  python3 .claude/hooks/inbox-processor.py

Called automatically by varys-daily.sh at the start of each loop.

Config files (same as slack-poller.py):
  ~/.claude/hooks/.notion   →  NOTION_API_KEY=secret_...
  ~/.claude/hooks/.slack    →  SLACK_TOKEN=xoxp-...
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import sys as _sys, time as _time
_sys.path.insert(0, str(Path(__file__).parent))
from agent_config import cfg
try:
    import varys_log as _k
except Exception:
    _k = None

INBOX_DIR = Path.home() / "varys-inbox"
VARYS_DIR = Path(__file__).parent.parent.parent  # personal-agent-v2/
LOG_FILE = Path("/tmp/varys-inbox-processor.log")

NOTION_BRAIN_PAGE_ID = "364d8747b3b1813d8ac8c248800f0a4d"
KAMAL_SLACK_ID = cfg("USER_SLACK_ID", "")
SLACK_BOT_TOKEN = cfg("SLACK_BOT_TOKEN", "")

# Known project paths → project name
PROJECT_PATHS = {
    cfg("TALEEMABAD_CORE_PATH", "/home/oye/Documents/taleemabad-core"): "taleemabad-core",
    str(Path.home() / "personal-agent" / "repos" / "taleemabad-cms"): "taleemabad-cms",
    str(Path.home() / "personal-agent" / "repos" / "taleemabad-auth"): "taleemabad-auth",
    str(Path.home() / "personal-agent" / "repos" / "portfolio-website"): "portfolio-website",
}


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, file=sys.stderr)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def detect_project(cwd: str) -> str:
    """Return project name from cwd, or empty string."""
    for path_prefix, project in PROJECT_PATHS.items():
        if cwd and cwd.startswith(path_prefix):
            return project
    return ""


def get_unprocessed_messages() -> list[Path]:
    """Return list of unprocessed inbox files, sorted oldest first."""
    if not INBOX_DIR.exists():
        return []
    files = sorted(INBOX_DIR.glob("*.json"))
    return files


def mark_done(inbox_file: Path):
    inbox_file.rename(inbox_file.with_suffix(".json.done"))


def mark_error(inbox_file: Path):
    inbox_file.rename(inbox_file.with_suffix(".json.error"))


def build_prompt(message: dict) -> str:
    text = message.get("text", "")
    cwd = message.get("cwd", "")
    project = message.get("project", "") or detect_project(cwd)
    source = message.get("source", "cli")

    project_context = ""
    if project:
        project_context = f"\nContext: Shoaib was working in project '{project}' (path: {cwd}) when he sent this."

    return f"""You are Varys, Shoaib's autonomous personal agent.

Shoaib has a question or message for you (sent via {source}):

\"{text}\"
{project_context}

Your job:
1. Answer using your Notion brain (page ID: {NOTION_BRAIN_PAGE_ID}).
   Read the relevant Notion databases: Work Log, Slack Inbox, Team People, My PRs.
   If the question is about a specific project ({project or 'check the context'}), read that project's harness too.
2. Send your response as a Slack DM to Shoaib (Slack user ID: {KAMAL_SLACK_ID}).
   Keep the response direct and specific — show you actually checked Notion data, not just guessing.
   Sign off as: Varys 🤖
3. Log this conversation to Notion Work Log with title: "Shoaib asked: {text[:60]}"

Rules:
- Never send Slack messages to anyone other than Shoaib without his explicit approval
- Never push code without Shoaib's approval
- If you can't find the answer in Notion/Slack, say so clearly rather than guessing
- Be direct, no fluff
"""


MAX_RETRIES = 3


def get_retry_count(inbox_file: Path) -> int:
    retry_file = inbox_file.with_suffix(".retries")
    if not retry_file.exists():
        return 0
    try:
        return int(retry_file.read_text().strip())
    except Exception:
        return 0


def increment_retry(inbox_file: Path):
    retry_file = inbox_file.with_suffix(".retries")
    count = get_retry_count(inbox_file) + 1
    retry_file.write_text(str(count))
    return count


def process_message(inbox_file: Path) -> bool:
    """Process one inbox message. Returns True on success."""
    try:
        data = json.loads(inbox_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log(f"ERROR: malformed JSON in {inbox_file.name}: {e}")
        mark_error(inbox_file)
        return False

    text = data.get("text", "").strip()
    if not text:
        log(f"SKIP: empty message in {inbox_file.name}")
        mark_done(inbox_file)
        return True

    log(f"Processing: {inbox_file.name} — '{text[:60]}'")

    retries = get_retry_count(inbox_file)
    if retries >= MAX_RETRIES:
        log(f"ERROR: max retries ({MAX_RETRIES}) exceeded for {inbox_file.name}, marking error")
        mark_error(inbox_file)
        return False

    prompt = build_prompt(data)

    # Load NVM so claude is available
    nvm_source = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'

    cmd = f'{nvm_source} && claude --dangerously-skip-permissions --print -p "$VARYS_PROMPT"'

    env = os.environ.copy()
    env["VARYS_PROMPT"] = prompt

    try:
        result = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            text=True,
            cwd=str(VARYS_DIR),
            timeout=300,
            env=env,
        )
    except subprocess.TimeoutExpired:
        log(f"ERROR: claude timed out for {inbox_file.name}")
        mark_error(inbox_file)
        return False

    if result.returncode != 0:
        log(f"ERROR: claude exited {result.returncode} for {inbox_file.name}")
        log(f"stderr: {result.stderr[:200]}")
        retries = increment_retry(inbox_file)
        log(f"Retry {retries}/{MAX_RETRIES} for {inbox_file.name}")
        return False

    log(f"OK: processed {inbox_file.name}")
    mark_done(inbox_file)
    return True


def main():
    messages = get_unprocessed_messages()
    if not messages:
        log("No unprocessed messages in inbox.")
        return

    log(f"Found {len(messages)} unprocessed message(s).")
    for inbox_file in messages:
        process_message(inbox_file)


if __name__ == "__main__":
    _t0 = _time.time()
    try:
        main()
        if _k: _k.klog_cron("inbox-processor", status="ok", duration_ms=(_time.time()-_t0)*1000)
    except Exception as _e:
        if _k: _k.klog_error("inbox-processor-main", _e, component="inbox-processor", severity="ERROR")
        raise
