---
name: Jira Auto-Hook
description: Automated Jira ticket creation from Claude sessions
type: reference
---

# Jira Auto-Hook — Ticket Creation

## Setup
- **Script**: `hooks/auto-jira.py` in personal-agent-v2
- **Token**: Stored at `~/.claude/hooks/.jira` (never commit this)
- **Project**: MC20 on `orendatrust.atlassian.net` (Taleemabad work)
- **Trigger**: When you ask Claude to create a Jira ticket

## How to Use

When you want to create a ticket in Jira, ask Claude:
```
Create a Jira ticket: [issue title and description]
```

Claude will:
1. Read the hook token from `~/.claude/hooks/.jira`
2. Call Jira API to create MC20 issue
3. Log the ticket URL in `vault/domains/taleemabad/work-log.md`
4. Return the ticket URL

## Ticket Metadata

Auto-created tickets include:
- **Project**: MC20 (Taleemabad)
- **Type**: Task (default; override with "Bug", "Story", etc. in request)
- **Summary**: From your request
- **Description**: Full context from your request
- **Assignee**: Kamal (can be changed in Jira UI)
- **Labels**: Auto-applied based on content (e.g., "backend", "testing")

## Token Management

The token in `~/.claude/hooks/.jira` is a Jira API token (not your password).
- **Create token**: Jira Settings → API Tokens → Generate
- **Keep secret**: Don't commit; never share
- **Rotate**: If exposed, regenerate from Jira UI immediately

## Troubleshooting

**Token not found**: Verify `~/.claude/hooks/.jira` exists and contains valid token
**Permission denied**: Token may lack MC20 project access; regenerate with full permissions
**API error**: Check Jira project name is MC20 and instance is orendatrust.atlassian.net
