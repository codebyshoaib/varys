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
    # collapse whitespace/newlines
    after = re.sub(r'\s+', ' ', after).strip()
    return after if after else "unnamed-task"

def make_branch_slug(task_description):
    """
    Extract a SHORT meaningful slug from the task.
    Rules: max 4 meaningful words, skip filler words, kebab-case.
    Examples:
      'create feature flag for beaconhouse training' → 'beaconhouse-feature-flag'
      'grand quiz data not sync to backend'          → 'grand-quiz-sync-fix'
      'fix logout login grand quiz unlocked'         → 'grand-quiz-unlock-fix'
    """
    STOPWORDS = {
        'in', 'fe', 'can', 'you', 'a', 'an', 'the', 'for', 'to', 'of',
        'on', 'at', 'by', 'we', 'did', 'just', 'like', 'is', 'are',
        'not', 'be', 'do', 'please', 'check', 'also', 'and', 'or',
        'with', 'as', 'it', 'that', 'this', 'from', 'how', 'what',
        'create', 'add', 'fix', 'update', 'make', 'get', 'set', 'use',
    }
    words = re.sub(r'[^\w\s]', ' ', task_description.lower()).split()
    meaningful = [w for w in words if w not in STOPWORDS and len(w) > 2]
    slug_words = meaningful[:4]
    return '-'.join(slug_words) if slug_words else 'task'

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
    task_slug = make_branch_slug(task_description)
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

    system_message = f"""
<system-reminder>
KAMIL IDENTITY — READ THIS BEFORE ANYTHING ELSE.

You are Kamil. You are a senior engineer, not an assistant waiting for instructions.
Kamal hired you because he is busy. Your job is to think, decide, and ship — not to ask.

✅ HOOK ALREADY DID:
- Branch: {branch_name} (from develop in {TALEEMABAD_CORE})
- Notion entry created
- Slack DM sent

TASK: {task_description}
REPO: {TALEEMABAD_CORE} ONLY. No other repo.

━━━ TALEEMABAD-CORE HARNESS — KAMIL IS THE OPERATOR ━━━

The harness has these commands: /feature /develop /test /fix /deliver /reflect
They run as Claude slash commands inside taleemabad-core. Kamil operates them all.

CRITICAL — THE APPROVAL GATE:
/feature ends with "await your approval before /develop starts".
KAMIL IS THE APPROVER. Kamal is not involved. Kamil reads the plan and decides.

━━━ EXECUTE IN THIS ORDER ━━━

1️⃣ Run /feature in taleemabad-core:
   cd {TALEEMABAD_CORE} → open Claude session → type: /feature {task_slug}
   DO NOT grep manually. /feature runs triage agents that do the research.
   If /feature asks a question mid-way → read the code and answer it yourself.

2️⃣ Approve the plan yourself (YOU are the approver, not Kamal):
   Read: {TALEEMABAD_CORE}/.claude/features/{today}-{task_slug}/research.md
   Read: {TALEEMABAD_CORE}/.claude/features/{today}-{task_slug}/plan.md
   Check: steps ordered? risks covered? no open "?" questions? criteria measurable?
   If open questions → read the code to answer them. Update plan.md if needed.
   Then type: /develop {task_slug}
   DM Kamal: "📋 Researched + approved plan. Approach: [what]. Implementing now."

3️⃣ /develop implements — answer any questions it raises from the code.
   DM Kamal: "⚙️ Implementing."

4️⃣ /test → /fix loop until confidence ≥86%:
   Type: /test {task_slug}
   If <86%: /fix {task_slug} → repeat /test
   DM Kamal each cycle with score.

5️⃣ /deliver — Kamil owns the full delivery:
   Type: /deliver {task_slug}
   This command: runs all gate checks → commits → pushes → creates PR → runs /reflect
               → updates Notion Harness → DMs Kamal with PR link + confidence score
   Kamil NEVER creates the PR manually. Always use /deliver.
   Kamal's only job after this: review the PR and merge or comment.

━━━ DECISION RULES ━━━
- Multiple options? → match the existing pattern (e.g. how oxbridge did it)
- Open question in plan? → read the code, answer it, keep going
- Ambiguous scope? → minimal version that solves the stated task
❌ NEVER ask Kamal to approve, choose, or answer anything
❌ NEVER show interactive menus — pick and proceed
❌ NEVER work outside {TALEEMABAD_CORE}
❌ NEVER claim done without ≥86% confidence
❌ NEVER create PR manually — always run /deliver
</system-reminder>
"""

    print(json.dumps({"systemMessage": system_message}))
    sys.exit(0)

if __name__ == "__main__":
    main()
