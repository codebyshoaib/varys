# Memory Index

This folder contains your agent's persistent memory files.
They are loaded at session start and help your agent understand who you are and how you work.

## Files in This Folder

| File | What it stores |
|------|---------------|
| `user_profile.md` | Your name, role, preferences — edit after /setup |
| `agent_personality.md` | How your agent talks and acts — customise freely |
| `kamil_humor_profile.md` | Humor style — edit to your preference |
| `kamil_face.md` | Visual identity — optional |

## How to Add Your Own Memory

Create a new `.md` file here with this header:
```
---
type: user
description: one-line description of what this file stores
---
```

Your agent will pick it up automatically at the next session start.
