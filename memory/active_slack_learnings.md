# Active Slack Learnings

What Varys has learned about Shoaib and their working relationship from Slack interactions.

## Recent (last 2 weeks)

- **#skyline is dead** (2026-07-02, team/#skyline): Alert channel with 17→32 repeated automation-queue-stuck alerts (Jun 24–28) went unaddressed. Multiple engineers (Usman Imtiaz, Mashhood Rastgar, Jalal Khan, Fahad Rao, Abdulrehman Siddiqi) left. People have tuned out. Do NOT assume posts to #skyline reach anyone; escalate critical items via DM or staffed channels.

- **Zeest Qureshi** (2026-07-02, #new-leads): Owns lead triage & pipeline hygiene. Posts daily digest of unaddressed leads + partnership opportunities (CEQUE India, Yemen/Core Insights). Route lead/partnership questions to her. Pattern: she flags staleness but doesn't own unblocking—oldest lead aged 38→39 days blocked on NDA despite daily flags. Flagging ≠ resolution.

- **Iqra Zanib** (2026-07-03, ComplianceTracker): Chronically review-blocked on Shoaib for CT PRs (434, 436–438 queued Jun 24). Shoaib is her single point of failure for throughput. Proactively run `compliancetracker-pr-reviewer` skill on Iqra PRs for fast first-pass review; she should own an auto-reviewer rather than depend on Shoaib's attention.

- **Muavia Qureshi & Haroon Ali** (2026-07-04, #regionpunjab-internal): Punjab-region user-management firefighters coordinating in #regionpunjab-internal (not #region-punjab). Dealing with orphaned roles, lost access, 'Unknown role' users, PD accounts visible in DB but not frontend. Muavia's blocker: DB-vs-frontend visibility mismatches. Route Punjab user-access/role/orphan issues to them; assume bugs are often stale-frontend/data-sync gaps, not missing accounts. Fixes that only clear orphans without deleting underlying roles can miss the real prod bug (Shoaib called this on PR #438).
