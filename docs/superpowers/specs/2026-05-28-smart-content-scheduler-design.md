# Smart Content Scheduler v2 — Design Spec

**Created:** 2026-05-28  
**Status:** Approved

---

## Goal

Kamil runs a daily content pipeline at 11am PKT across 3 tracks (fitness, tech, vlog). Each run: scans trending topics, scores them, picks the best topic, creates content via NotebookLM + image_generator, posts tech to LinkedIn automatically, delivers everything else to Kamal on Slack ready to post.

---

## The 3 Content Tracks

| Track | Niche | NLM | Image | LinkedIn | Slack |
|---|---|---|---|---|---|
| `fitness` | Calisthenics, swimming, hiking, cycling | ✅ slides + infographic + mindmap (visual-first) | ✅ 3 images | ❌ manual | ✅ 3 images + caption |
| `tech` | Claude, coding, AI agents, Django | ✅ slides + infographic + mindmap (visual-first) | ✅ 3 images | ✅ auto-post | ✅ 3 images + caption |
| `vlog` | Daily Islamabad life (Casey Neistat style) | ❌ not needed | ❌ not needed | ❌ manual | ✅ script only |

---

## Notion Content Calendar DB

**DB ID:** to be created (new DB under Kamal's Agent Brain page `364d8747b3b1813d8ac8c248800f0a4d`)

**Properties:**

| Property | Type | Values |
|---|---|---|
| Topic | title | e.g. "Pull-up Progression" |
| Track | select | `fitness` \| `tech` \| `vlog` |
| Status | select | `Pending` \| `In Progress` \| `Done` |
| EngagementScore | number | 0–100 |
| EngagementReason | text | Why this score — trend/signal |
| Source | select | `queue` \| `trending` |
| NLMNotebookID | text | Notebook ID after creation |
| PostedDate | date | When it ran |
| PostType | select | `qa` \| `steps` \| `info` \| `tip` \| `script` |

**Seed data — 20 pre-planned topics from existing Notion page:**

Fitness (10): Calisthenics Pull-Up Progression, Swimming Freestyle Breathing, Hiking Essentials Pakistan, Cycling Training Zones, Calisthenics vs Gym, Weekly Calisthenics Split, Recovery & Overtraining, Swimming for Non-Swimmers, Pakistan Hiking Trails, 30-Day Calisthenics Challenge

Tech (10): Personal AI Agent Weekend Build, Claude Code vs ChatGPT, Django Multi-Tenant Architecture, API Latency 40% Reduction, 5 Claude Prompts Every Developer Needs, Building Kamil Agent, AWS ECS vs Traditional Servers, Zero-Downtime DB Migrations, NotebookLM for Research, AI Tools That Save Dev Time 2026

Vlog (5 starters): Morning routine Islamabad, F-7 Markaz street food day, Margalla Hills sunrise hike, Islamabad cafe culture, Weekend road trip from Islamabad

---

## Daily Pipeline — Full Flow

Runs daily at **11am PKT (6am UTC)** via cron. Alternates fitness/tech daily; vlog runs every day independently.

```
FOR EACH TRACK (fitness or tech — alternating) + vlog:

1. TREND SCAN
   → WebSearch: "[track niche] trending today site:reddit.com OR site:twitter.com"
   → WebSearch: "[track niche] viral content [current month] [year]"
   → Score each candidate topic 0–100 (see scoring below)
   → Score ≥ 75 → insert as Pending row (Source=trending, top of queue)
   → Score 50–74 → insert as Pending row (Source=trending, normal queue)
   → Score < 50 → discard

2. PICK TOPIC
   → Query Notion: Status=Pending, Track=[track], sort by EngagementScore DESC
   → Pick top result → mark In Progress

3a. IF fitness or tech:
   → nlm notebook create [topic]
   → nlm research [topic] → sources added (~40 sources)
   → nlm slides [topic]       → slide deck (visual-first, minimal text per slide)
   → nlm studio infographic [topic] → single visual summary image
   → nlm mindmap [topic]      → visual mindmap (great for carousels)
   → vertical_converter.py    → convert NLM infographic to 1080x1350 portrait
   → image_generator.py       → branded 1080x1350 image (fitness=lavender, tech=dark)
   
   VISUAL-FIRST RULES (applied to all NLM artifacts):
   - Slides: max 6 words per slide, large visuals, bold single stat or icon per frame
   - Infographic: diagram/chart/roadmap format — no paragraph text
   - Mindmap: branches not bullets — visual hierarchy over lists
   - Caption: hook line + 3 visual cues ("swipe to see", "save this roadmap") + CTA + 4 live hashtags
   - Images sent to Slack: infographic + mindmap + branded image (3 files per post)

3b. IF tech:
   → linkedin_poster.py → auto-post image + caption to LinkedIn

3c. IF vlog:
   → WebSearch: "Islamabad [current week] events OR trending OR things to do"
   → Claude writes 300-word Casey Neistat-style script (see format below)
   → No image, no NLM

4. SLACK DM TO KAMAL
   → fitness/tech: 3 image files (infographic + mindmap + branded image) + caption + score + reason
   → tech: also "✅ already posted to LinkedIn" (LinkedIn gets branded image)
   → vlog: script text + "film this today"
   → NOTE: NLM slides + mindmap sent as files when ready (async poll, posted when done)

5. NOTION UPDATE
   → Status = Done, PostedDate = today, NLMNotebookID = [id if applicable]
```

---

## Engagement Scoring

| Signal | Points |
|---|---|
| Currently trending on Reddit or Twitter | +35 |
| High search interest (recent articles/videos this week) | +25 |
| Tight match to account niche | +20 |
| Timely (seasonal, news event, viral moment) | +15 |
| Pre-planned queue baseline | +5 |

**Thresholds:**
- ≥ 75 → jump queue today
- 50–74 → add to Pending for later
- < 50 → discard

---

## Vlog Script Format (Casey Neistat style)

```
🎬 VLOG TOPIC: [topic] — [score]/100
WHY TODAY: [what's trending/timely]

HOOK (first 3 sec on camera):
"[exact line to open with]"

SCENES:
1. [location] — [what to film, how long]
2. [location] — [what to film, how long]
3. [location] — [what to film, how long]
4. [location] — [what to film, how long]
5. [location] — [what to film, how long]

B-ROLL IDEAS: [what to capture while walking/commuting]
TRENDING AUDIO: [specific song or sound suggestion]
CTA: "[exact closing line to say on camera]"

HASHTAGS: [10 tags]
CAPTION: [ready-to-paste post caption]
```

---

## Slack DM Format (fitness/tech)

```
📊 *[Track] content ready — [topic]*
Score: [N]/100 — [reason]
Source: [Trending/Queue]

Caption:
[full caption ready to paste]

✅ Posted to LinkedIn  ← tech only
📱 Post to Instagram + TikTok (image below)
📓 NLM notebook [id] — slides + infographic generating (~5 min)

Next up: [next topic] ([score]/100)
🤖 Kamil
```

---

## Files to Create/Modify

| File | Action | Purpose |
|---|---|---|
| `.claude/hooks/content-scheduler.py` | Rewrite | Full v2 pipeline |
| `.claude/hooks/trend-scanner.py` | Create | Isolated trend scan + scoring logic |
| `vault/notion-map.md` | Update | Add new Content Calendar DB ID |

---

## Cron

```
0 6 * * * python3 /home/oye/Documents/free_work/personal-agent-v2/.claude/hooks/content-scheduler.py >> /tmp/kamil-content.log 2>&1
```
(already in crontab — no change needed)

---

## What's NOT in scope (v2)

- Auto-posting to Instagram, TikTok, YouTube (manual for now — Kamal posts)
- Video generation for vlog
- Engagement analytics tracking (v3)
- Comment strategy automation (v3)
