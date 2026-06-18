---
type: router
last_verified: 2026-06-01
owner: varys
paths:
  - ".claude/hooks/content-scheduler.py"
  - ".claude/hooks/image_generator.py"
  - ".claude/hooks/*_generator.py"
  - ".claude/hooks/trend*scanner.py"
---

# Content Pipeline

Daily LinkedIn/social pipeline runs via `content-scheduler.py` (cron 8am, see crontab).

## Before picking ANY topic — read these memory files first
| File | What it gives |
|------|---------------|
| `vault/memory/project_shoaib_content.md` | content strategy, what works, topic rules |
| `vault/memory/feedback_content_creation.md` | 4-part viral structure, hook templates, cut markers, what NOT to do |

Pipeline: Notion topics → NotebookLM research → `image_generator.py` → `linkedin_poster.py`. Log: `/tmp/varys-content.log`.
