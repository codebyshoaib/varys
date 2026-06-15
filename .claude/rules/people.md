# People Intelligence — Auto-Save Rule

**Any time a person is mentioned in conversation with Shoaib, save or update their entry in the People Intelligence DB immediately.**

DB: `c976d58ea4e34b0585f245529cdc4528`  
Data source: `collection://c00daef1-c072-4263-b23d-e1b5e2ba596c`

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
- `Relationship` — default `Distant` unless context says otherwise
- `Current Mood` — default `Unknown`
- `Interaction Count` — 1 on first save
- `Recurring Topics` — what they talked about / were mentioned for
- `Kamil Notes` — one line: date, what happened, channel/context
- `date:Last Seen:start` — today's date

On subsequent saves (person already exists):
- Increment `Interaction Count`
- Update `Last Seen`, `Current Mood`, `Active Needs`, `Recurring Topics`
- Append to `Kamil Notes` (don't overwrite — add a new dated line)

## Do NOT block on this

Save in the background or after replying. Never delay a response to Shoaib
because of a people-save. If the save fails, log it but continue.
