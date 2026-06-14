---
type: reference
last_verified: 2026-06-01
owner: varys
---

# Beads — Work Tracking

Append-only JSONL. Source of truth for Varys's work; mirrored to Notion Harness DB best-effort.

| File | Purpose |
|------|---------|
| `status.jsonl` | All tasks (open, in_progress, closed, blocked) |
| `decisions.jsonl` | Architectural decisions + rationale |
| `failures.jsonl` | Incidents + root cause + lesson (drives the eval loop) |

## Rules
- Append only — never edit a previous line.
- Open a bead before non-trivial work; close it with a resolution (what was done + how to verify).
- Every failure logged here SHOULD get a matching eval task in `.claude/evals/tasks/`.

## Query
    grep '"status":"open"' status.jsonl
    grep '"category":"bug"' status.jsonl
