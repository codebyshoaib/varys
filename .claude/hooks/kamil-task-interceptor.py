#!/usr/bin/env python3
"""
UserPromptSubmit hook: Intercepts "Kamil, work on taleemabad-core" messages.

Does the mechanical steps automatically (Notion entry, git setup),
then tells Claude exactly where things stand and what to do next.
Claude only handles the thinking: /feature → /develop → /test → PR.
"""

import sys
import json
import os
import re
import subprocess
import urllib.request
import urllib.error
from datetime import date

TRIGGER = "kamil, work on taleemabad-core"
TALEEMABAD_CORE = "/home/oye/Documents/taleemabad-core"
HARNESS_DB = "https://www.notion.so/de10157da3e34ef58a74ea240f31fe98"
HARNESS_DATA_SOURCE = "a173fd5a-b953-4a53-a020-4545db41ccb5"
KAMAL_SLACK_ID = "U0AV1DX3WSE"

def get_notion_token():
    path = os.path.expanduser("~/.claude/hooks/.notion")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                if line.startswith("NOTION_API_KEY="):
                    return line.strip().split("=", 1)[1]
    return os.environ.get("NOTION_API_KEY")

def get_slack_token():
    path = os.path.expanduser("~/.claude/hooks/.slack")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                if line.startswith("SLACK_TOKEN=") or line.startswith("SLACK_BOT_TOKEN="):
                    return line.strip().split("=", 1)[1]
    return os.environ.get("SLACK_BOT_TOKEN") or os.environ.get("SLACK_TOKEN")

def slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text[:50]

def extract_task(prompt):
    """Extract task description after the trigger phrase."""
    lower = prompt.lower()
    idx = lower.find(TRIGGER)
    if idx == -1:
        return prompt.strip()
    after = prompt[idx + len(TRIGGER):].strip()
    after = after.lstrip('—-–:').strip()
    after = after.lstrip('[').rstrip(']').strip()
    return after if after else "unnamed-task"

def create_notion_entry(task_name, plan_summary, token):
    """Create a Harness DB entry in Notion."""
    if not token:
        return None
    url = "https://api.notion.com/v1/pages"
    today = date.today().isoformat()
    payload = {
        "parent": {"database_id": HARNESS_DATA_SOURCE},
        "properties": {
            "Feature": {"title": [{"text": {"content": task_name[:100]}}]},
            "Phase": {"select": {"name": "Research"}},
            "Plan Summary": {"rich_text": [{"text": {"content": plan_summary[:500]}}]},
            "Confidence": {"number": 0},
            "Last Activity": {"date": {"start": today}}
        }
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get("url")
    except Exception as e:
        return None

def send_slack_dm(message, token):
    """Send DM to Kamal on Slack."""
    if not token:
        return False
    url = "https://slack.com/api/chat.postMessage"
    payload = {"channel": KAMAL_SLACK_ID, "text": message}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return True
    except Exception:
        return False

def git_setup(branch_name):
    """Checkout develop, pull, create branch. Returns (success, message)."""
    try:
        subprocess.run(
            ["git", "checkout", "develop"],
            cwd=TALEEMABAD_CORE, capture_output=True, timeout=30
        )
        subprocess.run(
            ["git", "pull", "origin", "develop"],
            cwd=TALEEMABAD_CORE, capture_output=True, timeout=60
        )
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=TALEEMABAD_CORE, capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return True, f"Branch '{branch_name}' created from develop"
        else:
            # Branch may already exist
            subprocess.run(
                ["git", "checkout", branch_name],
                cwd=TALEEMABAD_CORE, capture_output=True, timeout=10
            )
            return True, f"Switched to existing branch '{branch_name}'"
    except Exception as e:
        return False, str(e)

def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    prompt = hook_input.get("prompt", "").strip()
    if TRIGGER not in prompt.lower():
        sys.exit(0)

    # Extract task
    task_description = extract_task(prompt)
    task_slug = slugify(task_description)[:40]
    branch_name = f"kamil/{task_slug}"
    today = date.today().isoformat()

    # Step 1: Create Notion entry
    notion_token = get_notion_token()
    notion_url = create_notion_entry(
        task_name=task_description[:100],
        plan_summary=f"Task assigned by Kamal: {task_description[:400]}",
        token=notion_token
    )
    notion_status = f"✅ Notion entry created: {notion_url}" if notion_url else "⚠️ Notion entry failed (no token?)"

    # Step 2: Git setup
    git_ok, git_msg = git_setup(branch_name)
    git_status = f"✅ {git_msg}" if git_ok else f"⚠️ Git: {git_msg}"

    # Step 3: Slack DM
    slack_token = get_slack_token()
    slack_msg = f"🔍 Kamil starting: *{task_description[:100]}*\nBranch: `{branch_name}` | Notion: {notion_url or 'pending'}"
    send_slack_dm(slack_msg, slack_token)

    # Now tell Claude exactly what was done and what to do next
    system_message = f"""
<system-reminder>
KAMIL PROTOCOL — MECHANICAL STEPS ALREADY DONE. Continue from Step 3.

✅ COMPLETED AUTOMATICALLY:
- Notion Harness entry: {notion_status}
- Git branch: {git_status}
- Slack DM sent to Kamal: research phase started

YOUR JOB NOW — FOLLOW IN ORDER, NO SKIPPING:

STEP 3: Run /feature via bash (DO THIS FIRST, DO NOT GREP OR EXPLORE MANUALLY)
  cd {TALEEMABAD_CORE} && claude --dangerously-skip-permissions -p "/feature {task_slug}"
  Wait for it to complete. It will create:
    {TALEEMABAD_CORE}/.claude/features/{today}-{task_slug}/research.md
    {TALEEMABAD_CORE}/.claude/features/{today}-{task_slug}/plan.md
  Then READ both files. Answer any open questions yourself from the code.
  Update Notion Phase=Planning. DM Kamal: "📋 Research done. [root cause]. Starting implementation."

STEP 4: Run /develop (NO APPROVAL NEEDED)
  cd {TALEEMABAD_CORE} && claude --dangerously-skip-permissions -p "/develop {task_slug}"
  Update Notion Phase=In Dev. DM Kamal: "⚙️ Implementation started."

STEP 5: Run /test → /fix loop
  cd {TALEEMABAD_CORE} && claude --dangerously-skip-permissions -p "/test {task_slug}"
  If confidence <86%: claude --dangerously-skip-permissions -p "/fix {task_slug}" → repeat
  Update Notion Phase=Testing + Confidence score. DM Kamal with score.

STEP 6: Create PR
  cd {TALEEMABAD_CORE} && git push origin {branch_name}
  gh pr create --base develop --title "feat/fix: {task_description[:60]}" --body "..."
  Update Notion Phase=Done + PR link. DM Kamal: "✅ Done. PR: [link] | Confidence: [score]%"

TASK: {task_description}
BRANCH: {branch_name}
NOTION: {notion_url or HARNESS_DB}

RULES:
- Start with Step 3 RIGHT NOW — run the bash command for /feature
- NEVER ask Kamal questions the code can answer
- NEVER claim done without confidence ≥86%
</system-reminder>
"""

    print(json.dumps({"systemMessage": system_message}))
    sys.exit(0)

if __name__ == "__main__":
    main()
