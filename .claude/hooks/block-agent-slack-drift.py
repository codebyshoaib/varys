#!/usr/bin/env python3
"""
PreToolUse guard — Rumi principle: a spawned content/worker agent NEVER sends to Slack.
It returns text; the deterministic harness (slack-worker / varys-manager Python) delivers
to the origin channel (or Shoaib's DM). This removes the capability so the agent cannot
"drift" and pick its own channel (e.g. hardcoded #engineering-pr-review).

Only active when VARYS_CONTENT_AGENT=1 — set by the harness on every spawned `claude -p`.
Interactive sessions (Shoaib, the main loop) are untouched and may post normally.

Matcher: Bash | Skill | mcp__slack__.*   →   exit 2 blocks, exit 0 allows. Silent on allow.
"""
import json, os, re, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
try:
    import varys_log as _k
except Exception:
    _k = None

_DENY = (
    "I'm a spawned harness agent — I cannot post to Slack. "
    "Return ONLY the reply text as my final output; the harness delivers it to the "
    "originating thread (or Shoaib's DM). Do not curl chat.postMessage, do not call a "
    "Slack MCP tool, do not invoke slack-pr-notify."
)

# Slack-WRITE signatures in a Bash command (reads like history/list/users.info are fine).
# Catch-all on slack.com/api write verbs + named endpoints + the pr-notify token files.
# (conversations.history/.list and users.info contain none of these verbs → still allowed.)
_BASH_SLACK_SEND = re.compile(
    r"hooks\.slack\.com|slack-pr-notify/(bot-token|webhook)\.txt|"
    r"chat\.(postMessage|postEphemeral|update|scheduleMessage)|reactions\.add|"
    r"conversations\.(open|invite|create|kick)|"
    r"slack\.com/api/\S*(post|update|reaction|schedule|open|invite|create|kick)",
    re.I,
)
# mcp__slack__ write tools (reads allowed: history, users, profile, list, replies-read).
_MCP_SLACK_WRITE = re.compile(
    r"^mcp__slack__.*(post|reply|add_reaction|send|broadcast|update|schedule|open|invite|create|kick)",
    re.I,
)


def _blocked(tool: str, ti: dict) -> bool:
    if tool == "Bash":
        return bool(_BASH_SLACK_SEND.search(ti.get("command", "") or ""))
    if tool == "Skill":
        skill = (ti.get("skill") or ti.get("name") or "").lower()
        return skill == "slack-pr-notify"
    if tool.startswith("mcp__slack__"):
        return bool(_MCP_SLACK_WRITE.search(tool))
    return False


def main():
    if os.environ.get("VARYS_CONTENT_AGENT") != "1":
        sys.exit(0)  # only contain spawned agents
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # never block on malformed input
    tool = data.get("tool_name", "") or ""
    ti   = data.get("tool_input", {}) or {}
    if _blocked(tool, ti):
        print(_DENY, file=sys.stderr)
        if _k:
            _k.klog_policy_block("block-agent-slack-drift", rule=tool,
                                 reason="spawned agent attempted Slack send",
                                 command=str(ti)[:300])
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
