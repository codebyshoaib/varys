<!-- Installed from SkillHound: ComeOnOliver/skillshub (CherryHQ/cherry-studio/gh-pr-review) -->
---
name: gh-pr-review
description: Handles PR review comments and feedback resolution. Fetches comments via GitHub CLI, classifies by severity, applies fixes with user confirmation, commits with proper format, replies to threads. Also supports automated code review for local branches, PRs, commits, and files with single-agent or multi-agent adversarial review modes.
---

# /gh-pr-review — Code Review

Automated code review for local branches, PRs, commits, and files. Detects
review mode from arguments and routes to the appropriate review flow — either
quick single-agent review with interactive fix selection, or multi-agent
deep review with risk-based auto-fix.

All user-facing text matches the user's language. All questions and option
selections MUST use your interactive dialog tool — never output options as
plain text. Do not proceed until the user replies.

## Route

Run pre-checks, then match the **first** applicable rule top-to-bottom:

1. `git branch --show-current` → record whether on main/master.
2. `git status --porcelain` → record whether uncommitted changes exist.
3. Check whether the current environment supports Agent tool with parallel subagents.

| # | Condition | Action |
|---|-----------|--------|
| 1 | `$ARGUMENTS` is `diag` | Run diagnostic: check gh CLI auth, list open PRs, show recent review activity |
| 2 | `$ARGUMENTS` is a PR number or URL containing `/pull/` | Fetch PR comments via `gh pr view --comments` + `gh api` review comments; classify and fix |
| 3 | Agent teams NOT supported | Single-agent local review |
| 4 | Uncommitted changes exist | Single-agent local review |
| 5 | On main/master branch | Single-agent local review |
| 6 | Everything else | Ask user which mode (see Question below) |

## Fetching PR Review Comments

```bash
# List review comments on a PR
gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews
gh api repos/{owner}/{repo}/pulls/{pr_number}/comments

# Reply to a review comment thread
gh api repos/{owner}/{repo}/pulls/{pr_number}/comments \
  --method POST \
  -f body="<reply text>" \
  -F in_reply_to=<comment_id>

# Request re-review after fixes
gh pr review <pr_number> --approve --body "Addressed all comments."
```

## Severity Classification

| Label | Meaning | Auto-fix? |
|-------|---------|-----------|
| 🔴 blocking | Must fix before merge; correctness/security | Confirm |
| 🟡 important | Should fix; quality/maintainability | Confirm |
| 🟢 nit | Nice to have; style/naming | Auto in full mode |
| 💡 suggestion | Optional alternative | Never auto |
| 📚 learning | Educational only | N/A |

## Commit Format for Review Fixes

```bash
git commit -m "fix(review): address PR #<number> comments

- <issue 1 summary>
- <issue 2 summary>

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>"
```

Always reply to each addressed comment thread after committing:
`"Fixed in <commit_sha> — <one-line explanation>."`

## Question (when route hits case 6)

Ask a single question:
"Agent Teams is available (multiple agents working in parallel). Enable multi-agent review with reviewer-verifier adversarial mechanism and auto-fix?"

Options:

| Option | Description |
|--------|-------------|
| Teams + auto-fix low & medium risk (recommended) | Multi-agent review; auto-fix most issues, only confirm high-risk ones (API changes, architecture). |
| Teams + auto-fix low risk | Multi-agent review; auto-fix only the safest issues (null checks, typos, naming). Confirm everything else. |
| Teams + auto-fix all | Multi-agent review; auto-fix everything. Only issues affecting test baselines are deferred. |
| Single-agent + manual fix | Single-agent review; interactively choose which issues to fix afterward. |

## Single-Agent Local Review Flow

1. Get diff: `git diff main...HEAD` (or `git diff --staged` if uncommitted changes).
2. For each file changed: run checklist (logic, security, performance, maintainability).
3. Present findings grouped by severity.
4. For each finding ask: Fix now / Skip / Add to TODO?
5. Apply chosen fixes, stage, and commit with review-fix format.

## Multi-Agent Review Flow

1. Spawn Reviewer agent: reads diff, produces findings JSON.
2. Spawn Verifier agent: adversarially challenges each finding (false positive? already handled?).
3. Merge validated findings, apply auto-fixes per FIX_MODE.
4. Present remaining findings to user for confirmation.
5. Commit all fixes in a single structured commit.

## Integration with Varys Harness

- For taleemabad-core PRs: always run `/gh-pr-review <pr_number>` before marking Notion ticket Done.
- After review fixes: update Notion ticket `Last Agent Update` field.
- If review uncovers blocking issues: set ticket Status=Blocked, DM Kamal on Slack.
