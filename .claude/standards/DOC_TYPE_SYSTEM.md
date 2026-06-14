---
type: reference
last_verified: 2026-06-01
owner: varys
---

# Document Type System

| Type | Purpose | Line limit | Load behavior |
|------|---------|-----------|---------------|
| router | Navigation only — links, no content | 100 | Always safe |
| runbook | Step-by-step procedures | 200 | When executing it |
| reference | Stable lookup info | 300 | When that domain is active |
| investigation | Active analysis, time-bound | 300 | When debugging |
| plan | Proposed approach + decisions | none | When planning |
| changelog | Version history | none | By section only |

Enforcement: every markdown file (except CLAUDE.md) needs YAML frontmatter with `type:` and `last_verified:`.
