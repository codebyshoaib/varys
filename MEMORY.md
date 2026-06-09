# {{AGENT_NAME}} Memory Index

> This file is your agent's memory index. It is loaded at every session start.
> After running `/setup`, your agent's name will replace `{{AGENT_NAME}}` here.

## Quick Reference

| Memory | File | What it stores |
|--------|------|---------------|
| Your profile | `vault/memory/user_profile.md` | Who you are, your role, how you work |
| Agent personality | `vault/memory/agent_personality.md` | How your agent communicates |
| Notion Brain | `~/.agent-config.json` | Your Notion DB IDs (created by /setup) |

## How Memory Works

1. You run `/setup` once — this creates your Notion databases and writes `~/.agent-config.json`
2. Every Claude session reads these memory files at start
3. Session logs are written to `vault/logs/YYYY-MM-DD.md` automatically
4. Your agent learns from its mistakes via the evolution agent

## Customising Your Agent

Edit any file in `vault/memory/` to change how your agent understands you.
Add new files with `type: user` frontmatter and they'll be picked up automatically.
