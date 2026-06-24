# VARYS TRAJECTORY

Last computed: 2026-06-24T16:26Z. Window: last 10 sessions / 14 days.

## Recent failures / lessons (last 28 days)
2026-06-01: Duplicate hook files with hyphen/underscore spellings coexist in .claude/hooks/
  → lesson: Before deleting any duplicate, grep crontab AND all .py imports for BOTH spellin
2026-06-01: Varys had no PreToolUse hooks — nothing mechanically blocked dangerous commands 
  → lesson: Guides without sensors = a style guide nobody enforces. Enforcement must be mech
2026-06-01: Self-healing loop became a noise/damage source: listener falsely reported down→r
  → lesson: A feedback/healing system needs idempotency and verification MORE than a feature
2026-06-01: CORRECTION to prior entry: the auto-fixer's edits to content-scheduler.py were N
  → lesson: Verify a claimed 'error' is CURRENT before acting (re-run/re-compile). Detection

## Recent commits (last 14 days, 20 total)
  - feat(friction-approval): implement DM approval loop for region-friction-coach
  - feat(region-friction-coach): refine messaging and enhance pending message handling
  - feat(region-friction-coach): add initial implementation for analyzing team friction in Slack channel
  - feat(slack): enhance channel listing and message sweeping with user token support
  - feat(slack): enhance message summarization by replacing user mentions with display names
  - feat(slack): add PR review fast-path handling in slack-worker
  - feat(meeting-notes): implement v0 manual recording pipeline
  - feat(slack): enhance slack-worker and listener for tool tracking and logging
  ... and 12 more

## Recent architecture decisions
  2026-06-01: Local .beads/*.jsonl is the source of truth for work tracking; Notion Harness DB is a best
  2026-06-01: Make Varys skill-aware via a skills-router.md rule + listener prompt injection
  2026-06-01: Observability = extend varys_log (OTel envelope) → Axiom firehose + Notion signal-sink (wi
