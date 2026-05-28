# Notion Map — Kamil's Brain

> Auto-updated: session end (stop hook) + 2am daily cron via `notion-map-updater.py`.
> To regenerate manually: `python3 .claude/hooks/notion-map-updater.py --mode daily`

Last full scan: 2026-05-28 12:21

---

## Databases

| Name | DB ID | Purpose |
|---|---|---|
| My PRs | `18017a67136a4561ada9818c239b8f33` | Kamal's PRs, CI state, review status |
| Work Log | `0b71db855f914d18ac6d97c0f77fc21e` | Daily session summaries |
| Slack Inbox | `6d14f1b6b8cd4ff68fd40efdfc3f304e` | Classified Slack messages needing action |
| Harness | `de10157da3e34ef58a74ea240f31fe98` | Kamil's task backlog + self-evolution |
| Job Tracker | `0d69c6ff83d844c794c2d341c4ded8d7` | Freelance job postings + applications |
| People Intelligence | `c976d58ea4e34b0585f245529cdc4528` | Team profiles, mood, communication style |
| Eval Log | `94017dd157b44f3ca96423ad2ad989da` | Conversation quality scores (Good/Partial/Wrong) |
| Health Log | `27e287b7a3d146c6b5e8eb0d862d746f` | Operational health, errors, self-heals |
| Content Calendar | `68792d2dfff84691a4f646f5a8126149` | Social media topics (Pending/In Progress/Done) |
| Content Log | `630d86afb17746f9ad6f9bc78afefa02` | Every post generated — topic, caption, hashtags, NLM ID, LinkedIn ID, score |

---

## Pages (non-database)

| Name | Page ID | Purpose |
|---|---|---|
| Kamal's Agent Brain | `364d8747b3b1813d8ac8c248800f0a4d` | Parent container for all Kamil Notion content |
| Kamil Self-Questions | `365d8747b3b181b281b8ef5820e15881` | Personality-building questions, read every 30min |
| Master Plan / Freelance | `369d8747b3b181d59775dcb4297d7dbd` | Freelance outreach strategy + portfolio updates |

---

## NotebookLM Notebooks (external — nlm CLI, auth: oyekamalkhan@gmail.com)

| Name | Notebook ID | Sources |
|---|---|---|
| Instagram Niches | `76624bf5-82ce-4f11-b379-e07f308c6c4a` | 10 |
| Work / Taleemabad | `a2e6473a-bc3c-4737-b1b9-3c67e1fb94ae` | — |
| Harness / Taleemabad | `a03e5a92-d706-4ffb-9bd7-a3498dc7779d` | — |
| Reddit Jobs & Startups | `1a76701b-9e16-411f-9c2e-ea73223a8695` | 298 |

---

## Data Source IDs (for MCP create-pages)

| DB | Data Source ID |
|---|---|
| Slack Inbox | `8749992f-6140-4e72-8b48-7362533cb792` |
| Eval Log | `2e46d119-159e-4634-9195-a7343e590dbe` |
| People Intelligence | `c00daef1-c072-4263-b23d-e1b5e2ba596c` |
| Harness | `a173fd5a-b953-4a53-a020-4545db41ccb5` |

---

## Script → Database Matrix

| Script | Reads | Writes |
|---|---|---|
| `session-start.py` | My PRs, Work Log, Harness, Slack Inbox | — |
| `stop-notion.py` | — | Work Log |
| `stop.py` | — | git commit, STANDUP.md, notion-map.md |
| `kamil-task-interceptor.py` | Harness | Harness (create) |
| `kamil-slack-listener.py` | My PRs, Harness, Slack Inbox, Job Tracker, People | Slack Inbox, Work Log, Job Tracker |
| `kamil_eval.py` | Eval Log | Eval Log (create) |
| `kamil_eval_tracker.py` | Health Log | Health Log (update) |
| `kamil_health.py` | — | Health Log (create) |
| `kamil_people.py` | People Intelligence | People Intelligence (create/update) |
| `job-finder.py` | Job Tracker | Job Tracker (create) |
| `auto-apply.py` | Job Tracker | Job Tracker (update) |
| `portfolio-updater.py` | Job Tracker, Brain Page | Plan Page (update) |
| `openoutreach-monitor.py` | Job Tracker | Job Tracker (create) |
| `content-scheduler.py` | Content Calendar | Content Calendar (update) |
| `slack-poller.py` | Self-Questions Page, Slack Inbox | Work Log, Slack Inbox |
| `inbox-processor.py` | Brain Page, Work Log, Slack Inbox | Work Log |
| `notion-map-updater.py` | — | vault/notion-map.md (this file) |

---

## Cron Schedule

| Job | Schedule | Log |
|---|---|---|
| slack-poller.py | every 30min | `/tmp/kamil-slack.log` |
| job-finder.py | every 30min | `/tmp/kamil-jobs.log` |
| kamil-self-healer.py | every 10min | `/tmp/kamil-self-healer.log` |
| content-scheduler.py | daily 6am UTC (11am PKT) | `/tmp/kamil-content.log` |
| kamil-daily.sh | daily 8am PKT | `/tmp/kamil-daily.log` |
| kamil-learn.sh | daily 2am | `/tmp/kamil-learn.log` |
| kamil-weekly-report.sh | Monday 9am PKT | `/tmp/kamil-weekly.log` |
| notion-map-updater.py --mode daily | daily 2:30am | `/tmp/kamil-notion-map.log` |

---

## Auth / Token Locations

| Token | File | Notes |
|---|---|---|
| Notion API Key | `~/.claude/hooks/.notion` → `NOTION_API_KEY=` | Internal integration token |
| Slack Bot Token | `~/.claude/hooks/.slack` → `BOT_TOKEN=` | Kamil bot |
| Slack Signing Secret | `~/.claude/hooks/.slack` → `SIGNING_SECRET=` | Socket Mode |
| LinkedIn Access Token | `~/.claude/hooks/.linkedin` → `LINKEDIN_ACCESS_TOKEN=` | Expires every 2 months |
| LinkedIn Client ID | `~/.claude/hooks/.linkedin` → `LINKEDIN_CLIENT_ID=` | `779njtif515e0l` |
| Axiom Token | `~/.claude/hooks/.axiom` → `AXIOM_TOKEN=` | Dataset: `kamil-logs` |

---

## Troubleshooting

**Notion writes failing?**
→ Check `~/.claude/hooks/.notion` has valid `NOTION_API_KEY`
→ Token from: Notion Settings → Integrations → Internal Integration

**Content not posting to LinkedIn?**
→ LinkedIn token expires every 2 months — re-run OAuth
→ `tail -50 /tmp/kamil-content.log`
→ Ensure Content Calendar has pages with `Status=Pending`

**Slack listener not responding?**
→ `tail -20 /tmp/kamil-slack-listener.log`
→ Self-healer auto-restarts every 10min

**Job finder not running?**
→ `tail -20 /tmp/kamil-jobs.log`
→ Cron: `*/30 * * * *` — check `crontab -l`

**NotebookLM commands not working?**
→ Auth: `oyekamalkhan@gmail.com`
→ Run: `nlm login --check`
→ Daily limit may be hit — retry next day

**This map looks stale?**
→ `python3 .claude/hooks/notion-map-updater.py --mode daily`

---

## Activity Log
<!-- ACTIVITY_LOG_START -->
- 2026-05-28 12:20 — smoke test
- 2026-05-28 12:20 — Daily scan: 21 IDs across hooks | ⚠️ UNKNOWN `2e46d119159e46349195a7343e590dbe` in kamil_eval.py | ⚠️ UNKNOWN `2e46d119159e463491954a7343e590db` in notion-map-updater.py | ⚠️ UNKNOWN `76624bf582ce4f11b379e07f308c6c4a` in notebooklm_handler.py | ⚠️ UNKNOWN `a2e6473abc3c4737b1b93c67e1fb94ae` in notebooklm_handler.py | ⚠️ UNKNOWN `a03e5a92d7064ffb9bd7a3498dc7779d` in notebooklm_handler.py | ⚠️ UNKNOWN `1a76701b9e16411f9c2eea73223a8695` in notebooklm_handler.py
- 2026-05-28 12:21 — Daily scan: 21 IDs across hooks | all IDs accounted for ✅
- 2026-05-28 12:21 — session ended
- 2026-05-28 12:22 — session ended
- 2026-05-28 12:23 — session ended
- 2026-05-28 12:26 — session ended
- 2026-05-28 12:29 — session ended
- 2026-05-28 12:30 — session ended
- 2026-05-28 12:30 — session ended
- 2026-05-28 12:37 — session ended
- 2026-05-28 12:42 — session ended
- 2026-05-28 12:43 — session ended
- 2026-05-28 12:46 — session ended
- 2026-05-28 12:50 — session ended
- 2026-05-28 12:53 — session ended
- 2026-05-28 12:57 — session ended
- 2026-05-28 12:59 — session ended
- 2026-05-28 13:00 — session ended
- 2026-05-28 13:00 — session ended
- 2026-05-28 13:00 — session ended
- 2026-05-28 13:00 — session ended
- 2026-05-28 13:01 — session ended
- 2026-05-28 13:01 — session ended
- 2026-05-28 13:01 — session ended
- 2026-05-28 13:01 — session ended
- 2026-05-28 13:02 — session ended
- 2026-05-28 13:03 — session ended
- 2026-05-28 13:03 — session ended
- 2026-05-28 13:03 — session ended
- 2026-05-28 13:03 — session ended
- 2026-05-28 13:04 — session ended
- 2026-05-28 13:04 — session ended
- 2026-05-28 13:05 — session ended
- 2026-05-28 13:06 — session ended
- 2026-05-28 13:08 — session ended
- 2026-05-28 13:23 — session ended
- 2026-05-28 13:26 — session ended
- 2026-05-28 13:29 — session ended
- 2026-05-28 13:29 — session ended
- 2026-05-28 13:30 — session ended
- 2026-05-28 13:31 — session ended
- 2026-05-28 13:31 — session ended
- 2026-05-28 13:31 — session ended
- 2026-05-28 13:45 — session ended
- 2026-05-28 13:51 — session ended
- 2026-05-28 13:55 — session ended
- 2026-05-28 13:57 — session ended
- 2026-05-28 14:00 — session ended
- 2026-05-28 14:01 — session ended
- 2026-05-28 14:02 — session ended
- 2026-05-28 14:03 — session ended
- 2026-05-28 14:18 — session ended
- 2026-05-28 14:32 — session ended
- 2026-05-28 14:32 — session ended
- 2026-05-28 16:51 — session ended
- 2026-05-28 17:00 — session ended
- 2026-05-28 17:04 — session ended
- 2026-05-28 17:30 — session ended
- 2026-05-28 17:49 — session ended
- 2026-05-28 17:54 — session ended
- 2026-05-28 17:56 — session ended
- 2026-05-28 18:00 — session ended
- 2026-05-28 18:29 — session ended
- 2026-05-28 18:29 — session ended
- 2026-05-28 18:30 — session ended
- 2026-05-28 18:33 — session ended
- 2026-05-28 18:37 — session ended
- 2026-05-28 18:38 — session ended
- 2026-05-28 18:38 — session ended
- 2026-05-28 18:38 — session ended
- 2026-05-28 18:38 — session ended
- 2026-05-28 18:38 — session ended
- 2026-05-28 18:38 — session ended
- 2026-05-28 18:38 — session ended
- 2026-05-28 18:38 — session ended
- 2026-05-28 18:42 — session ended
- 2026-05-28 18:45 — session ended
- 2026-05-28 18:48 — session ended
- 2026-05-28 18:51 — session ended
- 2026-05-28 19:01 — session ended
- 2026-05-28 19:02 — session ended
- 2026-05-28 19:03 — session ended
- 2026-05-28 19:04 — session ended
- 2026-05-28 19:05 — session ended
- 2026-05-28 19:07 — session ended
- 2026-05-28 19:09 — session ended
- 2026-05-28 19:10 — session ended
- 2026-05-28 19:12 — session ended
- 2026-05-28 19:12 — session ended
- 2026-05-28 19:12 — session ended
- 2026-05-28 19:12 — session ended
- 2026-05-28 19:12 — session ended
- 2026-05-28 19:12 — session ended
- 2026-05-28 19:12 — session ended
- 2026-05-28 19:12 — session ended
- 2026-05-28 19:12 — session ended
- 2026-05-28 19:13 — session ended
- 2026-05-28 19:13 — session ended
- 2026-05-28 19:13 — session ended
- 2026-05-28 19:13 — session ended
<!-- ACTIVITY_LOG_END -->
