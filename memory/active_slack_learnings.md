# Active Slack Learnings

What Varys has learned about Shoaib and their working relationship from Slack interactions.

**Recent interactions (past 2 weeks):**

- **#skyline is dead.** (2026-07-02) — 17→32 repeated alerts from Automation-Queue-stuck bot across Jun 24/26/28 with zero human response; engineers (Usman Imtiaz, Mashhood Rastgar, Jalal Khan, Fahad Rao, Abdulrehman Siddiqi) left the channel. Do NOT rely on #skyline to reach anyone; escalate critical alerts via DM or staffed channels.

- **Zeest Qureshi owns lead pipeline hygiene.** (2026-07-02) — Posts daily #new-leads digest flagging unaddressed inbound (CEQUE India, Yemen/Core Insights). Route any partnership/lead question to her, but note: she surfaces staleness, not resolution — don't expect her to unblock; the owner of the blocker (e.g., NDA holder) has to be pinged directly.

- **Iqra Zanib is chronically review-blocked on Shoaib.** (2026-07-03) — Jun 24 alone: ComplianceTracker PRs 434, 436, 437, 438 all queued waiting on him as sole reviewer. He's a single point of failure for her throughput. When her CT PRs appear, proactively run `compliancetracker-pr-reviewer` to give fast first-pass review — this is exactly the "realm gets self-serve tools" case; she should own an auto-reviewer.

- **Muavia & Haroon Ali: Punjab user-access firefighters.** (2026-07-04) — Deep in orphaned roles, lost access, 'Unknown role' users, DB-vs-frontend visibility mismatches. Route Punjab user-access / role-visibility issues to #regionpunjab-internal. Recurring blocker: account exists in DB but not visible on frontend; assume sync gap before assuming data loss. Note: Shoaib flagged on PR #438 that a fix clearing an orphan without deleting the underlying role can miss the real prod bug.
