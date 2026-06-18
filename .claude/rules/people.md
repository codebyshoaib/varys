# People Intelligence — Auto-Save Rule

**Any time a person is mentioned in conversation with Shoaib, save or update their entry in the People Intelligence DB immediately.**

DB: `{{config:NOTION_PEOPLE_DB_ID}}` (👥 People Intelligence, under Varys Brain). Data source: fetch the DB to get its `collection://…` id.
Exact schema (no others exist): `Name`(title) · `Slack ID`(text) · `Role`(text) · `Team`(text) · `Recurring Topics`(text) · `Current Mood`(select: Unknown/Good/Stressed/Blocked) · `Interaction Count`(number) · `Last Seen`(date) · `Varys Notes`(text).

## When to trigger

- Shoaib mentions someone by name in any message
- A Slack mention (@name) appears in any context shared
- Someone sends a message that Varys replies to
- A PR review, ticket, or thread references a person

## What to save / update

Search People Intelligence DB for the person first. If found → update. If not → create.

Minimum fields to populate on first save:
- `Name` — full name
- `Slack ID` — if known
- `Team` / `Role` — infer from context (channel, mention, job title)
- `Current Mood` — default `Unknown` (one of Unknown/Good/Stressed/Blocked)
- `Interaction Count` — 1 on first save
- `Recurring Topics` — what they talked about / were mentioned for
- `Varys Notes` — one line: date, what happened, channel/context
- `date:Last Seen:start` — today's date

On subsequent saves (person already exists):
- Increment `Interaction Count`
- Update `Last Seen`, `Current Mood`, `Recurring Topics`; set `Team`/`Role` if newly known
- Append to `Varys Notes` (don't overwrite — add a new dated line)

The twice-daily `slack-intel-digest.py` is the primary writer here — it spawns a contained
`claude -p` (MCP) after each sweep to upsert everyone active. This rule also applies to the
interactive agent on any person mention.

## Do NOT block on this

Save in the background or after replying. Never delay a response to Shoaib
because of a people-save. If the save fails, log it but continue.
