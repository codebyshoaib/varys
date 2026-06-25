# Analyze Trajectory

> Diagnose a recurring failure (STUCK bead, clustered gate failure, frequent reverts)
> using sub-agent dispatch instead of bloating the main context.
> Read when the trajectory block flags a pattern; skip if the codebase looks healthy.

## When to use

Trigger this skill when ANY of these hold in `memory/trajectory.md`:
- A bead has been `blocked` or `cancelled` for 2+ ticks with the same error
- An evolution gate failure fingerprint appeared ≥2× (from `.beads/failures.jsonl`)
- Multiple revert entries appeared across recent sessions
- A specific hook/rule keeps being mentioned in failures without a fix landing

## When NOT to use
- Trajectory looks healthy — don't spelunk for problems that aren't there
- Failure is already understood (cause known from learnings) — fix it directly
- You're mid-implementation — finish the task, don't recurse

## Procedure

### 1. Frame the question (single sentence)

Good questions name a specific artifact and what you want to know:
- "Why does the evolve gate fail with `test_{stem}.py not found` on 4 of the last 6 runs?"
- "What's blocking bead `beads-142` — it's been `blocked` since 2026-06-20?"
- "What common pattern explains the 3 fence violations in failures.jsonl this week?"

Vague questions waste a sub-agent call.

### 2. Pick ONE artifact to fetch

| Symptom | Artifact to fetch |
|---|---|
| Evolve gate failure | `.beads/failures.jsonl` — last N entries for this gate |
| Stuck bead | `bd show <id>` + linked Slack thread if any |
| Revert pattern | `git log --oneline --grep="revert" -10` |
| Session-level wreckage | `vault/logs/YYYY-MM-DD.md` for that date |
| Hook test failure | Run `python3 .claude/hooks/test_<module>.py` and read stderr |

### 3. Dispatch a sub-agent (if log is large/noisy)

Use `claude --print -p "<focused question>"` with a narrow prompt scoped to the artifact.
Sub-agent reads the raw artifact and returns a 1–3 sentence summary.
Recurse only if the summary surfaces a deeper question that needs another artifact.

Pattern:
```bash
# Read the artifact in isolation, cap the sub-agent's context
FINDING=$(claude --print -p "$(cat <<'EOF'
Read .beads/failures.jsonl and find the 3 most recent 'evolve-gate-test' failures.
For each: what file was missing, what test was expected, what did the agent change?
Return 1–3 sentences per entry, no preamble.
EOF
)")
echo "$FINDING"
```

### 4. Produce a single root-cause diagnosis

Output format:
```
ROOT CAUSE: <one sentence>
EVIDENCE: <what you found, with file:line refs>
FIX: <smallest concrete change that resolves it>
CONFIDENCE: <high/medium/low>
```

### 5. Act or escalate

- **High confidence** → open a bead for the fix, or implement directly if it's inside the fence
- **Low confidence** → `bd human <id> --message "need input: <root cause hypothesis>"`
- **Already a bead** → add a `--notes` update so the next evolution run has context

## Key signal sources for Varys

| Source | What it tells you |
|---|---|
| `.beads/failures.jsonl` | Evolution gate failures with gate name + reason |
| `.beads/evolution.jsonl` | Successful evolutions — titles + files touched |
| `memory/trajectory.md` | Pre-computed summary of recent patterns |
| `vault/logs/YYYY-MM-DD.md` | Session narrative for a specific day |
| `~/.varys-harness/telemetry.jsonl` | All events with severity — grep for ERROR/FATAL |
| `crontab -l` | What's actually wired; silent failures start here |
