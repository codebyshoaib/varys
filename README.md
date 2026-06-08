# Personal AI Agent

Your own AI agent that remembers, learns, and works — powered by Claude Code.

## What it does

- **Remembers** your work across sessions via Notion (automatic session logs)
- **Learns** from its mistakes and improves its own rules over time
- **Orchestrates** specialist sub-agents for engineering, content, research, and more
- **Integrates** with Slack (optional) to respond when you @mention it

## Setup — 3 steps, 5 minutes

**1. Clone this repo**
```bash
git clone https://github.com/oyekamal/kamil-agent.git my-agent
cd my-agent
```

**2. Install Claude Code**

Download from [claude.ai/code](https://claude.ai/code) and open a terminal session in the repo folder.

**3. Run the setup wizard**
```
/setup
```

The wizard will ask you for your name, your agent's name, and your Notion API token.
It creates your Notion databases automatically — no manual setup required.

## What you need

- A [Notion account](https://notion.so) — free tier is fine
- A [Notion API token](https://www.notion.so/my-integrations) — takes 2 minutes to create
- [Claude Code](https://claude.ai/code)
- Slack (optional — for @mention triggers)

## After setup

Open a new Claude Code session in the repo folder and start talking to your agent.
Your agent will greet you by name and load your Notion context automatically.

## Customising your agent

| What | Where |
|------|-------|
| Agent personality & identity | `vault/memory/` files |
| How the agent handles specific tasks | `.claude/rules/` files |
| Specialist sub-agents | `.claude/agents/` files |
| Slash commands | `.claude/commands/` files |

## Reconfigure

Run `/setup` at any time to change your agent name, reconnect Notion, or add Slack.

## Architecture

```
Claude Code session
    ↓
CLAUDE.md (identity + routing)
    ↓
.claude/hooks/ (session start/stop, task interception)
    ↓
~/.agent-config.json (your personal config — never committed)
    ↓
Notion (memory) + Slack (optional feed)
```

## Troubleshooting

**Notion not connecting:** Check your token at https://www.notion.so/my-integrations.
Make sure the integration has "Read content" and "Insert content" capabilities.

**Agent doesn't know my name:** Run `/setup` — it personalises CLAUDE.md with your name.

**Session start errors:** Check that `~/.claude/hooks/.notion` exists and contains `NOTION_API_KEY=secret_...`
