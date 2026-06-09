# After /setup — What Happens Next

You've run `/setup` and your agent is configured. Here's what to expect.

---

## Starting Your First Session

Open Claude Code in this folder and start a new session. Your agent will:

1. **Greet you by name** — CLAUDE.md has been personalised with your name and agent name
2. **Load your Notion context** — You'll see "Loading Notion brain..." for a few seconds
3. **Tell you what's in your Harness** — Any tasks you've added to your Notion Harness database

This is normal. It happens every session.

---

## Talking to Your Agent

Just type naturally. Examples:

> "What do I have on my plate today?"

> "Help me write a LinkedIn post about [topic]"

> "Research the best tools for [topic]"

> "Remember that I prefer [X] when doing [Y]"

Your agent routes each request to the right specialist automatically.

---

## Your Notion Workspace

After `/setup`, your Notion workspace has a page called **"[AGENT_NAME] Brain"** with:

| Database | What it's for |
|----------|--------------|
| **[AGENT_NAME] Harness** | Task backlog — your agent tracks work here |
| **[AGENT_NAME] Work Log** | Automatic session logs — written at session end |
| **[AGENT_NAME] Inbox** | Slack messages (only if you enabled Slack) |

You can open these in Notion and see your agent's work in real time.

---

## Auto-Commits (What They Are)

At the end of every session, your agent automatically:
- Writes a summary to your Notion Work Log
- Commits any changes to `vault/logs/` with the message `log: session YYYY-MM-DD`

**This is intentional.** It keeps a history of your agent's activity in git.
If you don't want this, comment out the `Stop` hooks in `.claude/settings.json`.

---

## Customising Your Agent

| You want to change... | Edit this file |
|----------------------|---------------|
| Agent's name or your name | Run `/setup` again |
| How the agent talks | `vault/memory/agent_personality.md` |
| Who you are / your context | `vault/memory/user_profile.md` |
| Which tasks to delegate to agents | `.claude/rules/skills-router.md` |

---

## Adding Slack

If you skipped Slack during setup and want to add it later, run `/setup` again and say yes to Slack when asked.

You'll need to:
1. Create a Slack app at https://api.slack.com/apps
2. Add scopes: `chat:write`, `channels:history`, `channels:read`
3. Install it to your workspace and copy the Bot User OAuth Token

---

## Troubleshooting

**Agent doesn't know my name:** Run `/setup` again.

**Notion not loading:** Check `~/.claude/hooks/.notion` exists and contains `NOTION_API_KEY=secret_...`

**Integration errors:** Make sure your Notion integration has "Read content" and "Insert content" capabilities at https://www.notion.so/my-integrations

**Hooks failing:** Check `/tmp/agent-*.log` files for error messages.
