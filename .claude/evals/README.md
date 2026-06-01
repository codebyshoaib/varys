---
type: reference
last_verified: 2026-06-01
owner: kamil
---

# Eval Harness

Measures whether Kamil's docs route correctly. Two tiers:

- **Tier-1 (deterministic, $0, ON):** `graders/run-tier1.sh` — route files exist, frontmatter present, line limits, freshness. Wire into a hook or run before doc changes.
- **Tier-2 (LLM judge, ~$0.10/run, OFF by default):** not built yet. To enable, add a runner that feeds each `tasks/*.yaml` input to `claude -p`, captures which docs it loaded, and scores against `expected`. Track cost in `.beads/decisions.jsonl`.

## Self-improving loop
When you log a failure in `.beads/failures.jsonl`, add a matching `tasks/eval-NNN-*.yaml` so that class of mistake is caught next session.
