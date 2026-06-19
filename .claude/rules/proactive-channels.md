---
type: config
last_verified: 2026-06-19
owner: varys
paths:
  - ".claude/hooks/proactive-watch.py"
---

# Proactive Slack Channel Watch Config

Format per line: `#channel-name | mode | keywords`

Modes:
- `watch` — check channel for keyword matches; post if relevant
- `read-only` — monitor but never post back; for awareness only
- `banter` — human-mode channel; log all messages as awareness items

---

#engineering-general | watch | broken,failing,error,blocked,help,PR,deploy,issue
#engineering-backend  | watch | broken,failing,error,blocked,help,PR,deploy,issue
#engineering-frontend | watch | broken,failing,error,blocked,help,PR,deploy,issue
#standup              | read-only |
#random               | banter |
#announcements        | read-only |
