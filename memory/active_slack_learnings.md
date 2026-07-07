# Active Slack Learnings

What Varys has learned about Shoaib and their working relationship from Slack interactions.

- **#skyline is dead** (2026-07-02) — Alert channel has tuned out. 17→32 repeated alerts Jun 24/26/28 with zero human response; several engineers left the channel. Don't rely on it to reach anyone; escalate important automation-queue issues via DM or staffed channel instead.

- **Zeest Qureshi owns lead triage** (2026-07-02) — Posts daily digest of stale leads/partnerships (#new-leads). Route any lead/pipeline question to her, but note: she flags staleness, doesn't unblock it — oldest lead aged 38→39 days still stuck on NDA despite daily flagging. Flagging ≠ resolution; blocker owner must be pinged directly.

- **Iqra Zanib is review-blocked on Shoaib** (2026-07-03) — Chronically queued on ComplianceTracker PRs (434, 436, 437, 438 across Jun 24) waiting on him as sole reviewer. He's a single point of failure for her throughput. Proactively run `compliancetracker-pr-reviewer` skill on her PRs for fast first-pass review — this is exactly the "realm gets self-serve tools" case; she should own an auto-reviewer rather than depend on his attention.

- **Muavia Qureshi & Haroon Ali: Punjab user-mgmt firefighters** (2026-07-04) — Coordinate in #regionpunjab-internal on orphaned roles, lost access, 'Unknown role' users, DB-vs-frontend visibility mismatches. Route any Punjab user-access/role-visibility issue there. Recurring blocker: accounts exist in DB but don't render on frontend. Assume bug is often stale-frontend/data-sync gap, not genuinely missing account. Note: fixes that only clear orphans without deleting underlying roles can miss the real prod bug.
