# PR Review

## Core Rules
- Read the ticket description before reviewing — understand the intent.
- Separate: blocking issues (must fix) vs suggestions (nice to have).
- Blocking: security holes, broken tests, wrong behaviour.
- Suggestion: style, naming, minor refactors.
- Frame feedback as questions when uncertain: "Did you consider X?"

## Front Door — a bare "review this PR" arrives (most common request)

Shoaib/Haroon drop a PR URL with little context ("this pr", "check now", "review this").
Don't free-solo the review — route by the repo in the URL to the dedicated reviewer skill:

| PR URL contains… | Invoke |
|---|---|
| `taleemabad-core` | `taleemabad-pr-review-lite <pr_url>` (default; add `--opus` only for high-stakes) |
| `compliancetracker` | `compliancetracker-pr-reviewer <pr_url>` |
| anything else | `gh-pr-review <pr_url>` (see `github-pr-review.md` skill for the gh-CLI flow) |

These skills already encode each repo's golden rules, post inline comments, and auto-approve —
running the generic flow instead loses that coverage.

## Idempotency — never re-review the same commit (the ack-spam bug, varys-lc7)

A PR-review job that re-fires on every re-poll spams the thread with duplicate reviews
(this actually happened — fixed via lease-based retries + idempotent ack, 2026-07-01):

- **Key the review by HEAD SHA, not the PR number.** If you already reviewed the PR's current
  `gh pr view <pr> --json headRefOid` SHA, it's a no-op — post nothing.
- **Only re-review when the SHA changed** (new commits pushed). A bare re-poll or a re-run of
  the same bead must not produce a second review of unchanged code.
- **Ack once.** Mark the bead/thread acked after the review posts; a lease guards against a
  concurrent worker picking up the same job. Re-running on an unchanged world = silence.

## What Works
<!-- append lessons -->

## What to Avoid
<!-- append mistakes -->

## Recurring Patterns in This Codebase
<!-- append patterns you keep catching, e.g.: -->
<!-- - Missing tenant filter in queryset — check every new view -->
