"""
varys_people.py — Person profile intelligence layer.

After every conversation, Varys:
1. Looks up the person in the People Intelligence Notion DB
2. Updates their profile with signals from this interaction
3. Reads their profile before the next reply (so Varys knows WHO it's talking to)

This is what makes Varys remember:
- Fatima is stressed this week
- She responds to humor
- She cares about test coverage
- She gets frustrated with clarifying questions
- Last time she mentioned PR #5103 was blocking her

DB: People Intelligence (collection://c00daef1-c072-4263-b23d-e1b5e2ba596c)
"""

import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import sys as _sys_people
_sys_people.path.insert(0, str(Path(__file__).parent))
from agent_config import cfg as _cfg_people

VARYS_DIR      = Path(__file__).parent.parent.parent
PEOPLE_DB_ID   = "c976d58ea4e34b0585f245529cdc4528"
PEOPLE_DS_ID   = "c00daef1-c072-4263-b23d-e1b5e2ba596c"
PROFILE_CACHE  = Path("/tmp/varys-people-cache.json")


def _run_claude(prompt: str, timeout: int = 120) -> str:
    nvm = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'
    env = os.environ.copy()
    env["VARYS_PROMPT"] = prompt
    try:
        result = subprocess.run(
            ["bash", "-c", f'{nvm} && claude --dangerously-skip-permissions --print -p "$VARYS_PROMPT"'],
            capture_output=True, text=True,
            cwd=str(VARYS_DIR), timeout=timeout, env=env,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def load_profile_cache() -> dict:
    if PROFILE_CACHE.exists():
        try:
            return json.loads(PROFILE_CACHE.read_text())
        except Exception:
            return {}
    return {}


def save_profile_cache(cache: dict):
    try:
        PROFILE_CACHE.write_text(json.dumps(cache, indent=2))
    except Exception:
        pass


def get_profile(sender_name: str, sender_id: str) -> dict:
    """
    Return cached profile for a person.
    Cache is populated by update_profile_after_conversation.
    """
    cache = load_profile_cache()
    return cache.get(sender_id, {})


def update_profile_after_conversation(
    sender_name: str,
    sender_id: str,
    is_third_party: bool,
    request: str,
    reply: str,
    mode: str,
    thread_history: str = "",
):
    """
    Run after every conversation. Updates Notion People Intelligence profile.
    Runs in a background thread — never blocks the reply.
    """
    if not is_third_party and sender_id == _cfg_people("USER_SLACK_ID", ""):
        # Shoaib himself — skip (he has his own memory system)
        return

    threading.Thread(
        target=_do_update,
        args=(sender_name, sender_id, request, reply, mode, thread_history),
        daemon=True,
    ).start()


def _do_update(sender_name: str, sender_id: str, request: str,
               reply: str, mode: str, thread_history: str):
    today = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""You are Varys's intelligence layer. Your job is to maintain a rich profile of every person Varys interacts with.

## PERSON
Name: {sender_name}
Slack ID: {sender_id}
Today: {today}

## THIS CONVERSATION
Mode: {mode}
They said: "{request}"
Varys replied: "{reply[:300]}"

Thread history:
{thread_history[-800:] if thread_history else "(first interaction)"}

## YOUR JOB

1. **Search the People Intelligence DB** for this person:
   Use mcp__claude_ai_Notion__notion-search with query "{sender_name}"
   Look for a page in the People Intelligence database (ID: {PEOPLE_DB_ID})

2. **Analyze this conversation for signals:**
   - Communication style: are they direct? detailed? casual? formal?
   - Emotional signals: stressed keywords ("blocked", "urgent", "still broken"), relaxed (emojis, jokes, thanks)
   - Topics they raised: what are they talking about?
   - Humor response: did they engage with humor positively or neutrally?
   - Active needs: what are they waiting for or blocked on?
   - Relationship warmth: cold/professional/warm/close?

3a. **If profile EXISTS** → update it:
    Use mcp__claude_ai_Notion__notion-update-page with command "update_properties"
    Update: Current Mood, Last Seen, Active Needs, Recurring Topics, Interaction Count (+1)
    Only update What Works / What to Avoid / Communication Style if you have clear evidence.
    Also append a brief note to the page content:
    "[{today}] Said: '{request[:80]}' | Mood signal: [your assessment]"

3b. **If profile DOES NOT EXIST** → create it:
    Use mcp__claude_ai_Notion__notion-create-pages
    data_source_id: {PEOPLE_DS_ID}
    Set all fields you can infer. Leave unknown fields blank.
    Create page content with the first interaction note.

4. **Output a JSON summary** (for cache, no Slack output):
   {{"slack_id": "{sender_id}", "name": "{sender_name}", "mood": "...", "style": "...", "needs": "...", "topics": "...", "works": "...", "avoid": "..."}}

Do steps 1-4. Reply with ONLY the JSON summary on the last line."""

    result = _run_claude(prompt, timeout=90)

    # Extract JSON from last line
    if result:
        lines = [l.strip() for l in result.strip().splitlines() if l.strip()]
        for line in reversed(lines):
            if line.startswith("{") and line.endswith("}"):
                try:
                    profile = json.loads(line)
                    cache = load_profile_cache()
                    cache[sender_id] = {
                        **profile,
                        "name":      sender_name,
                        "slack_id":  sender_id,
                        "updated":   datetime.now().isoformat(),
                    }
                    save_profile_cache(cache)
                except Exception:
                    pass
                break


def build_person_context(sender_name: str, sender_id: str) -> str:
    """
    Returns a context block injected into Varys's prompt before replying.
    "You're about to talk to Fatima. Here's what you know about her."
    """
    profile = get_profile(sender_name, sender_id)
    if not profile:
        return f"(No profile yet for {sender_name} — first or early interaction)"

    parts = [f"*{sender_name}'s profile:*"]
    if profile.get("mood"):
        parts.append(f"Current mood: {profile['mood']}")
    if profile.get("style"):
        parts.append(f"Communication style: {profile['style']}")
    if profile.get("needs"):
        parts.append(f"Active needs: {profile['needs']}")
    if profile.get("topics"):
        parts.append(f"What she/he talks about: {profile['topics']}")
    if profile.get("works"):
        parts.append(f"What works: {profile['works']}")
    if profile.get("avoid"):
        parts.append(f"What to avoid: {profile['avoid']}")

    return "\n".join(parts)
