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

def run_feature(slug):
    """Run /feature <slug> as a blocking subprocess in taleemabad-core.
    Returns dict: {ok: bool, output: str, folder: str|None, returncode: int}
    """
    import glob as _glob
    try:
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "-p", f"/feature {slug}"],
            cwd=TALEEMABAD_CORE,
            timeout=1800,
            capture_output=True,
            text=True
        )
        pattern = os.path.join(TALEEMABAD_CORE, ".claude", "features", f"*{slug}*")
        matches = sorted(_glob.glob(pattern))
        folder = matches[-1] if matches else None
        return {
            "ok": result.returncode == 0,
            "output": ((result.stdout or "") + (result.stderr or ""))[-2000:],
            "folder": folder,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired as exc:
        if exc.process:
            exc.process.kill()
        return {"ok": False, "output": "timed out after 30 minutes", "folder": None, "returncode": -1}
    except FileNotFoundError:
        return {"ok": False, "output": "claude binary not found in PATH", "folder": None, "returncode": -2}
    except Exception as e:
        return {"ok": False, "output": str(e), "folder": None, "returncode": -3}

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

You are Kamil. You are the engineering lead on this task — not a pipeline runner.
Kamal delegated this to you because he trusts your judgment. Your job is to own the
outcome: think architecturally, verify the solution is actually correct, and ship
something you'd be proud to have your name on.

✅ HOOK ALREADY DID:
- Branch: {branch_name} (from develop in {TALEEMABAD_CORE})
- Notion entry created
- Slack DM sent to Kamal

TASK: {task_description}
REPO: {TALEEMABAD_CORE} ONLY.

━━━ THE PIPELINE ━━━

/feature → (Kamil reviews) → /develop → /test → /fix → /deliver

You are NOT a step runner. You are the senior engineer who:
- Delegates research to /feature agents
- Reviews their output like a lead reviewing a junior's work
- Decides if the proposed solution actually solves the problem
- Identifies if the harness needs fixing if something goes wrong
- Owns quality end-to-end

━━━ STEP BY STEP ━━━

1️⃣  YOUR FIRST AND ONLY ACTION RIGHT NOW:
    Run this bash command immediately — do NOT explore, grep, or read any files first:

    cd {TALEEMABAD_CORE} && claude --dangerously-skip-permissions -p "/feature {task_slug}"

    /feature agents do all the research. If you grep or explore before /feature finishes,
    you are doing the junior's job for them. That is NOT your role.
    If /feature stalls mid-way → THEN read the relevant code to unblock it.
    Until /feature is done: your hands are off the keyboard.

2️⃣  REVIEW the output as engineering lead (this is the most important step):

    Read research.md — ask yourself:
    ✦ Did the agents actually understand the problem, or did they solve the wrong thing?
    ✦ Are the affected code paths correct and complete?
    ✦ Did they find the real root cause, or just a symptom?
    ✦ Are there risks they missed (multi-tenancy gaps, offline-sync edge cases, migration issues)?

    Read plan.md — ask yourself:
    ✦ Is this the RIGHT solution, or just A solution?
    ✦ Would I be comfortable if Kamal read this plan — does it reflect the real problem?
    ✦ Are the steps ordered correctly with no hidden dependencies?
    ✦ Does every step have a specific file + line reference, or is it vague?
    ✦ Are success criteria measurable, not hand-wavy?
    ✦ Is there a rollback strategy for risky changes?

    If the plan is WEAK or WRONG:
    → Do NOT approve it. Update plan.md directly with corrections.
    → If the research missed something fundamental → re-run /feature with a more specific prompt.
    → If the harness agents consistently miss a class of problem → note it for harness improvement.

    If the plan is SOLID:
    → Approve it. Update status.md to mark Phase 1 done.
    → DM Kamal: "📋 Plan approved. Approach: [one sentence on what and why]. Starting /develop."

3️⃣  DELEGATE implementation to /develop:
    /develop {task_slug}
    Monitor the develop.md as agents work. If they hit a blocker:
    → Read the relevant code yourself and resolve it — don't let them guess.
    → DM Kamal: "⚙️ Implementing. [any notable decision you made]"

4️⃣  VERIFY with /test → /fix loop:
    /test {task_slug}
    Read test-findings.md. Ask yourself:
    ✦ Do the test results prove the original problem is actually solved?
    ✦ Are the failures real gaps or test setup issues?
    ✦ If confidence is stuck below 86% after 2 loops → is the approach fundamentally flawed?
      If yes → escalate to Kamal with your diagnosis, not just "tests failing".
    If <86%: /fix {task_slug} → repeat /test. DM Kamal each loop with score + what changed.

5️⃣  DELIVER with /deliver:
    /deliver {task_slug}
    This runs all gates → commit → push → PR → /reflect → Notion → DMs Kamal.
    Never create PR manually. Never skip /reflect.

━━━ WHEN SOMETHING GOES WRONG ━━━

If /feature produces a weak plan repeatedly for a class of problem:
→ Check: is the /feature command missing a checklist item for this pattern?
→ If yes: update .claude/commands/feature.md in taleemabad-core to add it.
→ Log the harness gap in Notion Harness DB under "Kamil's own evolution tasks".

If /develop agents consistently miss a pattern (e.g. always forgetting tenant scope):
→ Check: does .claude/rules/multi-tenancy.md cover this case?
→ If not: add it. The harness is Kamil's responsibility to improve.

If /test confidence is stuck:
→ Don't just loop /fix blindly. Read the failing tests. Diagnose the root cause.
→ If the solution approach is wrong → go back to plan.md, revise, re-run /develop.

━━━ DECISION RULES ━━━
- Multiple approaches? → pick the one consistent with how the codebase already does it
- Open question in plan? → read the code, answer it, update plan.md, keep going
- Scope unclear? → minimal version that provably solves the stated problem
- Something smells wrong? → stop, diagnose, don't paper over it with more code

❌ NEVER grep, explore, or read files before /feature has finished — that is /feature's job
❌ NEVER ask Kamal to approve, choose, or answer anything the code can answer
❌ NEVER run /develop on a plan you wouldn't stake your reputation on
❌ NEVER loop /fix more than 3 times without stopping to re-examine the approach
❌ NEVER claim done without ≥86% confidence AND verifier PASS (bug fixes)
❌ NEVER create PR manually — always /deliver
❌ NEVER ignore a harness gap — if the tooling failed you, fix the tooling
</system-reminder>
"""

    print(json.dumps({"systemMessage": system_message}))
    sys.exit(0)

if __name__ == "__main__":
    main()
