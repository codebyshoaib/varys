# Active Slack Learnings

What Varys has learned about Shoaib and their working relationship from Slack interactions.

## Dead channels
- **#skyline** (2026-07-02) — Dead alert channel. Bot fired 17→32 repeated alerts across Jun 24/26/28 with zero human response; multiple engineers (Usman Imtiaz, Mashhood Rastgar, Jalal Khan, Fahad Rao, Abdulrehman Siddiqi) left it. Do NOT rely on #skyline to reach anyone — escalate critical issues via DM or a staffed channel instead.

## Team-specific patterns

**Zeest Qureshi** (2026-07-02, #new-leads) — Owns lead triage & pipeline hygiene. Posts daily digests on unaddressed inbound leads (e.g., CEQUE India, Yemen/Core Insights). Route pipeline questions to her, but note: **flagging ≠ resolution**. Oldest lead aged 38→39 days despite daily flagging; if a lead needs to move, the blocker owner (not Zeest) must be pinged directly.

**Iqra Zanib** (2026-07-03, ComplianceTracker PRs) — Chronically review-blocked on Shoaib for CT PRs (434, 436, 437, 438 all queued waiting on him as sole reviewer). Shoaib is a single point of failure for her throughput. When an Iqra CT PR appears, proactively run `compliancetracker-pr-reviewer` skill to give fast first-pass review — she should own an auto-reviewer rather than depend on Shoaib's bandwidth.

**Muavia Qureshi & Haroon Ali** (2026-07-04, #regionpunjab-internal) — Punjab-region user-management firefighters handling orphaned roles, lost access, unknown roles, and PD accounts visible in DB but not on frontend. Muavia's recurring blocker: DB-vs-frontend visibility mismatches. Route any Punjab user-access / role-visibility / orphaned-account issue to them. Assume the bug is often stale-frontend/data-sync gap, not missing account. **Critical:** A fix that only clears an orphan without deleting the underlying role can miss the real prod bug (Shoaib's PR #438 note).
