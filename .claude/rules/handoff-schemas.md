---
type: reference
owner: varys
last_verified: 2026-06-08
---

# Handoff Schemas — Typed JSON Contracts Between Agents

Every agent that feeds another agent MUST return one of these schemas.
The dispatcher validates before routing. Malformed output → escalation-broker fires.

## Manager Phase 1 Output (varys-manager.py → dispatcher)

```json
{
  "real_intent": "string — one sentence: what is {{USER_NAME}}/team actually trying to achieve?",
  "chosen_agent": "string — must match a filename in .claude/agents/ (without .md)",
  "delegation_brief": "string — full brief: task, context, definition of done, constraints",
  "slack_plan_message": "string — message to post in Slack thread: plan + who handles it",
  "confidence": "number — 0–100, how confident in this routing",
  "capability_gap": "string | null — if no agent fits, describe what's missing"
}
```

Required: real_intent, delegation_brief, slack_plan_message, confidence
Either chosen_agent OR capability_gap must be non-null (not both null).

## Any Agent Final Output (worker → manager)

```json
{
  "status": "done | blocked | partial",
  "summary": "string — 1–2 sentences of what happened",
  "deliverable": "string | null — PR URL, Notion URL, Slack message ts, etc.",
  "partial_work": "string | null — what was completed if status=partial",
  "blocker": "string | null — specific blocker if status=blocked or partial"
}
```

Required: status, summary
If status=blocked or partial: blocker must be non-null.

## taleemabad-bug-agent Plan Output (bug-agent → Slack + manager)

```json
{
  "root_cause": "string — specific root cause identified in the code",
  "plan_steps": ["string", "string"],
  "e2e_test_cases": ["string", "string"],
  "confidence": "number — 0–100",
  "files_to_touch": ["string — relative paths from repo root"]
}
```

Required: all fields.

## Validation Rules

1. Parse output as JSON. If parse fails → log to failures.jsonl, fire escalation-broker.
2. Check required fields present and non-empty. If missing → same as parse failure.
3. If chosen_agent is set, verify it matches a file in .claude/agents/. If not → capability_gap.
4. If confidence < 40 and status != "done" → escalation-broker fires regardless of status.
