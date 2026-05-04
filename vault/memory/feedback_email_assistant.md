---
name: Email Assistant Behavior
description: How Claude should handle email reading and response drafting
type: feedback
---

# Email Assistant Workflow

## Rule: Read → Track → Draft → Approve → Send

**Why:** Email is asynchronous communication with people. Drafting without approval can commit Kamal to messages he didn't intend. Tracking everyone who emails builds long-term relationship context.

**How to apply:**

1. **Read Gmail** — Every session start, fetch emails from last 24 hours for `m.kamal@taleemabad.com`
2. **Track contacts** — Add every sender to `vault/domains/contacts/email-tracker.md` and person files
3. **Update work-log** — Extract action items or decisions from emails into `vault/domains/taleemabad/work-log.md`
4. **Flag for action** — Present emails needing responses with suggested replies
5. **Await approval** — Do NOT send emails without explicit approval
6. **Send only after approval** — Once approved, send and log the action

## Email Tracker Structure

`vault/domains/contacts/email-tracker.md`:
- Simple index of every person who emailed
- Columns: Name | Email | Subject | Date | Summary

`vault/domains/contacts/people/<Name>.md`:
- One file per person who emails
- Includes context: role, projects together, communication history, last contact date

## When Email Is Stale

If an email needs a response and Kamal hasn't approved after 48 hours:
- Flag it in `/morning-standup` as overdue
- Re-suggest the reply with updated context
- Don't send without approval, ever
