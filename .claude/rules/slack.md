---
type: reference
last_verified: 2026-06-01
owner: varys
paths:
  - ".claude/hooks/slack-poller.py"
  - ".claude/hooks/varys-slack-listener.py"
  - ".claude/hooks/inbox-processor.py"
---

# Slack — Send & Lookup Patterns

Workspace: `{{config:SLACK_WORKSPACE}}`. {{USER_NAME}}'s Slack ID: `{{config:USER_SLACK_ID}}`. BOT_TOKEN lives in `~/.claude/hooks/.slack` (NEVER commit this file).

## Patterns
Person lookup and interaction write-back: see `.claude/hooks/varys_context.py` — do not re-specify here.
- Send DM / message: `mcp__slack__slack_post_message` (channel_id, text).
- Reply in a thread: `mcp__slack__slack_reply_to_thread` (channel_id, thread_ts, text).
- Find a user: `mcp__slack__slack_get_users` or `mcp__slack__slack_get_user_profile`.
- Read channel history: `mcp__slack__slack_get_channel_history`.
- List channels: `mcp__slack__slack_list_channels`.
- Slack format only in responses: no `#` headers; use `*bold*`, bullets, emoji; concise. Sign off `🕷️ {{AGENT_NAME}}`.

## Rules
- **ALWAYS use `mcp__slack__*` MCP tools for ALL Slack operations** — never raw `api/chat.postMessage`, never Python scripts, never CLI utilities.
- Load tool schemas via `ToolSearch` before first use if not already in context.
- Never ask what these tools can answer — look it up.
- Read full thread history (passed into every prompt) before responding.
- Act, then confirm — not "I would need to…".
