#!/bin/bash
# varys-learn.sh — Nightly self-improvement loop. Runs at 2am via cron.
#
# Closes the daily eval feedback loop:
#   1. Auto-judge: score every unjudged Eval Log row (empty Score) 0-100 (LLM judge),
#      set Pass = (score >= 70), append the judge note to Notes — all via Notion HTTP.
#   2. Confidence: passed / scored * 100 + avg score + per-agent breakdown.
#   3. DM Shoaib the confidence score + breakdown — computed and sent HERE (urllib,
#      SLACK_BOT_TOKEN), NOT inside the claude -p subprocess. The DM is the run's
#      user-facing output; we do not route it through an MCP that may be unwired (or
#      blocked by block-agent-slack-drift) inside a spawned subprocess.
#   4. Propose (do NOT auto-apply): a claude -p subprocess turns low-rated rows into
#      bd beads + a Notion Learning Log entry for Shoaib to approve. No code edits,
#      no git commit, NO Slack from the subprocess.
#
# ❌ Wrong rows are auto-minted into .beads/failures.jsonl (with a `ts`) by the
# judge step itself, which fuels varys-evolution-agent.py.
#
# NOTE: this script deliberately does NOT use `set -e`. The stages (judge / confidence
# / DM / propose) are independent best-effort steps — a nonzero from one must not abort
# the rest. Each stage is guarded individually.
#
# Cron (installed via cron-wrap.sh):
#   0 2 * * * cd ~/varys && .claude/hooks/cron-wrap.sh varys-learn ./varys-learn.sh >> /tmp/varys-learn.log 2>&1

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

VARYS_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$VARYS_DIR" || exit 1
TODAY="$(date +%Y-%m-%d)"

echo "[varys-learn] Starting at $(date)"

# ── 1. Auto-judge unjudged Eval Log rows (one claude -p pass over the batch) ──
echo "[varys-learn] Judging unjudged eval rows for $TODAY ..."
JUDGE_JSON="$(python3 .claude/hooks/varys_eval.py judge "$TODAY" 2>>/tmp/varys-learn.log)" || JUDGE_JSON="{}"
[ -n "$JUDGE_JSON" ] || JUDGE_JSON="{}"
echo "[varys-learn] judge result: $JUDGE_JSON"

# ── 2. Compute confidence + breakdown lines from the judged numbers ──
# Writes a tiny env file the DM stage sources. Guarded: any failure leaves defaults.
CONF=0 PASSED=0 FAILED=0 SCORED=0 AVG=0 MINTED=0
BY_AGENT="(no data)"
COMPUTED_ENV="$(mktemp)"
if VL_JUDGE_JSON="$JUDGE_JSON" python3 - <<'PY' > "$COMPUTED_ENV" 2>>/tmp/varys-learn.log
import json, os, shlex

try:
    d = json.loads(os.environ.get("VL_JUDGE_JSON") or "{}")
except Exception:
    d = {}

passed = int(d.get("passed", 0) or 0)
failed = int(d.get("failed", 0) or 0)
judged = int(d.get("judged", 0) or 0)
avg    = int(d.get("avg_score", 0) or 0)
minted = int(d.get("minted", 0) or 0)
conf   = round(passed / judged * 100) if judged else 0


def fmt(group: dict) -> str:
    # group: {"slack/dm": {"passed":4,"failed":1,"scored":5}, ...} -> "slack/dm 4✅/1❌ · ..."
    parts = []
    if isinstance(group, dict):
        for key, counts in group.items():
            if not isinstance(counts, dict):
                continue
            p = int(counts.get("passed", 0) or 0)
            f = int(counts.get("failed", 0) or 0)
            parts.append(f"{key} {p}✅/{f}❌")
    return " · ".join(parts) if parts else "(no data)"

by_agent = fmt(d.get("by_agent") or {})

# Emit shell-safe `KEY=value` assignments.
out = {
    "PASSED": passed, "FAILED": failed, "SCORED": judged, "AVG": avg,
    "MINTED": minted, "CONF": conf, "BY_AGENT": by_agent,
}
for k, v in out.items():
    print(f"{k}={shlex.quote(str(v))}")
PY
then
    # shellcheck disable=SC1090
    source "$COMPUTED_ENV"
else
    echo "[varys-learn] WARN: confidence computation failed; using defaults" >&2
fi
rm -f "$COMPUTED_ENV"

echo "[varys-learn] confidence=${CONF}% (passed=$PASSED failed=$FAILED scored=$SCORED avg=$AVG minted_failures=$MINTED)"
echo "[varys-learn] by agent: $BY_AGENT"

# ── 3. DM Shoaib the confidence + breakdown (urllib, here — NOT in the subprocess) ──
# Mirrors slack-intel-digest.py::_dm_shoaib: conversations.open -> chat.postMessage.
echo "[varys-learn] DMing Shoaib the nightly summary ..."
EVAL_DB_ID="38390224-8f3d-81dc-894c-e17a94549101"
VL_TODAY="$TODAY" VL_CONF="$CONF" VL_PASSED="$PASSED" VL_FAILED="$FAILED" VL_AVG="$AVG" \
VL_SCORED="$SCORED" VL_BY_AGENT="$BY_AGENT" VL_DBID="$EVAL_DB_ID" \
python3 - <<'PY' 2>>/tmp/varys-learn.log || echo "[varys-learn] WARN: DM failed (see log)" >&2
import json, os, sys, urllib.request
from pathlib import Path

# Resolve bot token + user id the same way the other Slack hooks do.
def _load_kv(path: Path) -> dict:
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out

slack_cfg = _load_kv(Path.home() / ".claude" / "hooks" / ".slack")
token = (slack_cfg.get("SLACK_BOT_TOKEN") or slack_cfg.get("BOT_TOKEN")
         or os.environ.get("SLACK_BOT_TOKEN") or os.environ.get("BOT_TOKEN") or "")

user_id = ""
cfg_path = Path.home() / ".agent-config.json"
if cfg_path.exists():
    try:
        user_id = (json.loads(cfg_path.read_text()).get("USER_SLACK_ID") or "")
    except Exception:
        user_id = ""
user_id = user_id or os.environ.get("USER_SLACK_ID") or ""

if not token or not user_id:
    print("[varys-learn] DM skipped: missing SLACK_BOT_TOKEN or USER_SLACK_ID", file=sys.stderr)
    sys.exit(1)


def _post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


# conversations.open -> a 'D' channel against the user's id (never a public channel).
try:
    opened = _post("https://slack.com/api/conversations.open", {"users": user_id})
except Exception as e:
    print(f"[varys-learn] conversations.open failed: {e}", file=sys.stderr)
    sys.exit(1)

dm_ch = (opened.get("channel") or {}).get("id", "")
if not opened.get("ok") or not dm_ch.startswith("D"):
    print(f"[varys-learn] refusing to post: resolved channel {dm_ch!r} is not a DM",
          file=sys.stderr)
    sys.exit(1)

e = os.environ.get
# 0 scored = no interactions logged today, NOT 0% confidence. Don't cry wolf.
if int(e('VL_SCORED') or 0) == 0:
    summary = "No interactions logged today — nothing to score."
else:
    summary = (
        f"Confidence: {e('VL_CONF')}% ({e('VL_PASSED')} pass / {e('VL_FAILED')} fail "
        f"of {e('VL_SCORED')} scored, avg {e('VL_AVG')})\n"
        f"By agent: {e('VL_BY_AGENT')}"
    )
text = (
    f"\U0001f9e0 *Nightly eval — {e('VL_TODAY')}*\n"
    f"{summary}\n"
    f"Eval Log: https://www.notion.so/{e('VL_DBID')}\n"
    "\U0001f577️ Varys (nightly run, proposals only — your approval needed)"
)

try:
    res = _post("https://slack.com/api/chat.postMessage", {"channel": dm_ch, "text": text})
except Exception as ex:
    print(f"[varys-learn] chat.postMessage failed: {ex}", file=sys.stderr)
    sys.exit(1)

if not res.get("ok"):
    print(f"[varys-learn] chat.postMessage not ok: {res.get('error')}", file=sys.stderr)
    sys.exit(1)
print("[varys-learn] DM sent.")
PY

# ── 4. Propose fixes as beads + Learning Log (claude -p subprocess; NO Slack) ──
# IMPORTANT: this run PROPOSES only. It must NOT edit code, must NOT commit, and
# must NOT post to Slack (the DM already went out above). Shoaib approves the beads;
# the evolution agent (separately, behind an eval gate) is the only path that edits
# .claude/rules and .claude/agents.
echo "[varys-learn] Spawning proposal subprocess (beads + Learning Log only) ..."
LEARNING_LOG_PARENT="37f902248f3d81b6bf51f67744d7b485"

# Fetch today's low rows HERE (real-schema Notion HTTP query) so the subprocess
# does NOT re-query the DB. We embed the rows as JSON straight into the prompt.
LOW_ROWS_JSON="$(python3 .claude/hooks/varys_eval.py low "$TODAY" 2>>/tmp/varys-learn.log)" || LOW_ROWS_JSON="[]"
[ -n "$LOW_ROWS_JSON" ] || LOW_ROWS_JSON="[]"
echo "[varys-learn] low rows for $TODAY: $LOW_ROWS_JSON"

export VL_TODAY="$TODAY" VL_CONF="$CONF" VL_PASSED="$PASSED" VL_FAILED="$FAILED" \
       VL_SCORED="$SCORED" VL_AVG="$AVG" VL_DBID="$EVAL_DB_ID" \
       VL_BY_AGENT="$BY_AGENT" VL_PARENT="$LEARNING_LOG_PARENT" VL_LOW_ROWS="$LOW_ROWS_JSON"

# Heredoc is UNQUOTED (<<PROMPT) on purpose: the $VL_* run values MUST expand into
# the prompt string before claude -p receives it (claude -p does NOT read the env).
# Everything that must stay literal in the rendered prompt is backslash-escaped:
# the bd-create \-continuations (\\), the <...> backtick-free placeholders, and any
# stray $ are written as \$ / \\ so only the VL_* values interpolate.
claude --dangerously-skip-permissions --print -p "$(cat <<PROMPT
You are Varys on your nightly self-improvement run. The Eval Log has already been
auto-rated for today by the judge step, and Shoaib has ALREADY been DMed the
confidence + breakdown by the calling script. Your job now is to PROPOSE
improvements and record them. Hard rules:
  - DO NOT edit any code file.
  - DO NOT run git add / git commit / git push.
  - DO NOT post to Slack. Do NOT use any Slack tool. The DM already went out.
  - DO NOT auto-apply anything. Everything is a PROPOSAL for Shoaib to approve.
  - DO NOT re-query the Eval Log DB — the failing rows are already given below.

Today: $VL_TODAY
Confidence already computed: $VL_CONF% ($VL_PASSED pass / $VL_FAILED fail of $VL_SCORED scored, avg $VL_AVG)
By agent: $VL_BY_AGENT
Eval Log DB: $VL_DBID

## Step A — the low-scoring (Pass=false, score < 70) rows for today
These were already fetched for you (real Eval Log schema: page_id, name, task,
agent, notes, score). Do NOT query Notion to re-read them:
$VL_LOW_ROWS

## Step B — propose fixes as bd beads (NOT code edits)
Group the rows by the failure pattern you infer from their notes/agent. For each
DISTINCT pattern, create ONE bead:
  bd create "fix: <pattern> in Varys (<N> evals)" \\
    --description "<root cause + the rows it came from (cite page_id/name) + a proposed fix direction>" \\
    --acceptance "<how we'd know it's fixed>"
Run bd via Bash. If a near-identical open bead already exists (bd list), skip — do not duplicate.
If the rows array is empty, create no beads.

## Step C — write a Learning Log entry to Notion
Use mcp__claude_ai_Notion__notion-create-pages with parent page id $VL_PARENT:
  Title: "Varys Learn — $VL_TODAY"
  Body: the confidence score, the per-agent breakdown shown above, the failure
        patterns found, and the beads you proposed. State plainly that nothing was
        auto-applied and that Shoaib was already DMed the summary.

Do NOT DM or post anything. End by printing a one-line summary of beads created.
(Self-reflection / learnings are NOT this run's job — varys-reflect.py owns that loop.)
PROMPT
)" 2>&1 || echo "[varys-learn] WARN: proposal subprocess returned nonzero" >&2

echo "[varys-learn] Done at $(date)"
