---
type: reference
last_verified: 2026-06-01
owner: kamil
paths:
  - ".claude/hooks/slack-poller.py"
  - ".claude/hooks/kamil-slack-listener.py"
  - ".claude/hooks/inbox-processor.py"
---

# Slack — Send & Lookup Patterns

Workspace: `{{config:SLACK_WORKSPACE}}`. {{USER_NAME}}'s Slack ID: `{{config:USER_SLACK_ID}}`. BOT_TOKEN lives in `~/.claude/hooks/.slack` (NEVER commit this file).

## Patterns
Person lookup and interaction write-back: see `.claude/hooks/kamil_context.py` — do not re-specify here.
- Send DM / message: `POST api/chat.postMessage` with BOT_TOKEN.
- Reply in a thread: include `thread_ts` in `chat.postMessage`.
- Find a user: `GET api/users.list` (filter by name) or `api/users.lookupByEmail`.
- Slack format only in responses: no `#` headers; use `*bold*`, bullets, emoji; concise. Sign off `🤖 {{AGENT_NAME}}`.

## Rules
- Never ask what these tools can answer — look it up.
- Read full thread history (passed into every prompt) before responding.
- Act, then confirm — not "I would need to…".
