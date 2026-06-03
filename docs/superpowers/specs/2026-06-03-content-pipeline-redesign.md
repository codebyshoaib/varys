# Content Pipeline Redesign — Plan
**Date:** 2026-06-03  
**Owner:** Kamil

---

## What's Wrong With the Current Pipeline

1. **Topics are Reddit titles, not Kamal's stories.** The trend scanner scrapes Reddit post titles like "Didn't expect build asteroids to turn into a performance problem lol" and posts them directly. These have nothing to do with Kamal's life, channels, or audience connection.

2. **No personal angle.** Every post is generic. Nothing says "this is Kamal in Islamabad who runs Margalla trails and builds AI agents." The audience can't connect because there's no person in the content.

3. **Wrong image on LinkedIn.** Was posting the locally generated branded PNG (a simple text card), not the NLM infographic which is rich and professional.

4. **LinkedIn caption sounds like Instagram.** Bullet points, "Swipe to see", hashtag stacks — wrong format for LinkedIn's professional feed.

5. **NLM fallback (Claude research + Canva carousel) produces weak output.** The `canva_carousel.py` creates multi-slide carousels but the quality of what's inside depends entirely on the Claude research prompt, which currently has no depth or personality.

6. **4 channels exist, pipeline only handles 3.** `@kamalkepainting` is missing entirely.

---

## The New Design

### Core Principle
Every post must answer: **"What did Kamal actually do, see, build, or feel this week?"** If it doesn't have Kamal in it, it doesn't go out.

---

## Part 1 — Topic Bank (Curated, Permanent)

Replace the Reddit trend scanner as the primary topic source with a curated bank of 60 topic seeds — 20 per channel — rooted in Kamal's real life. Trend scanner becomes secondary signal only (supplements the bank, doesn't replace it).

### Exercise Channel (`@kamalkeexercies`)
Topics are personal training stories + Islamabad-specific locations:

1. The first time I did a muscle-up — what nobody tells you about the transition
2. Margalla Trail 5 at 5am — what the city looks like from up there
3. Why I switched from gym to calisthenics (the real reason)
4. Swimming in Rawal Lake in October — what it actually feels like
5. 30-day pull-up challenge: day 1 vs day 30, here's what changed
6. The Islamabad cycling route I do every Sunday (F-7 to Saidpur, 22km)
7. I tried running every morning for 2 weeks — this is what happened to my output
8. Hiking alone vs hiking with someone — which one builds you more
9. The calisthenics move that took me 6 months — here's the breakdown
10. Why most people quit exercise after 3 weeks (I almost did too)
11. Daman-e-Koh trail in rain — the best version of this city
12. How I track fitness without an app (analog method that actually works)
13. Cold water swimming: 3 months in, here's what changed in my brain
14. The 5 bodyweight exercises I do every single day
15. What I eat before a long trail run (real food, Islamabad edition)
16. I got injured and couldn't train for a month — here's what I learned
17. Margalla Hills vs Rawal Lake: which one is better for mental reset
18. The moment I realised calisthenics is actually harder than the gym
19. How I fit training into a life of building software products
20. Cycling at golden hour in Islamabad — a visual

### Tech Channel (`@kamalkecoding`)
Topics are real builds, real lessons from Kamal's agentic workflow work:

1. I built a Slack bot that runs my entire dev workflow — here's how
2. Why I use Claude Code for every PR now (not just hard problems)
3. The harness I built so I never write the same code twice
4. How I automated my content pipeline with Claude agents (meta: this post)
5. Agentic workflows explained through the thing I actually built
6. The biggest mistake I made building AI agents (and how I fixed it)
7. How NotebookLM changed the way I research before building
8. My PR review workflow: from Slack mention to merged in under an hour
9. Building a job-finder that auto-applies — what I learned
10. Why my Claude agent has hooks that block it from doing bad things
11. How I built a Notion-backed memory system for my AI agent
12. The self-healing observer that fixes my cron jobs at 3am
13. From idea to shipped feature: my exact pipeline in taleemabad-core
14. What I wish I knew about Django multi-tenancy before starting
15. How I use parallel agents to do 6 hours of work in 45 minutes
16. The one hook that saves me from AI hallucinations every day
17. Why I stopped writing tests manually (and what I do instead)
18. Building a content scheduler that actually knows what to post
19. Claude Sonnet vs Haiku: when I use each and why it matters
20. The git worktree pattern that lets me work on 3 features at once

### Personal Vlog (`@oykamal`)
Topics are storytelling — real moments, real Islamabad, real emotion:

1. A normal Sunday in Islamabad — F-7 chai, Margalla, back by noon
2. The morning routine that changed how I think about my day
3. Why I moved back to Islamabad (the real answer, not the polished one)
4. Saidpur Village on a quiet Tuesday — what this city feels like when you slow down
5. The project that almost broke me and what it taught me
6. What building software products actually looks like from the inside
7. A day where everything went wrong and I filmed it anyway
8. The chai spot in F-6 I've been going to for 3 years
9. Daman-e-Koh at dusk — the moment the city turns golden
10. Why I started painting again after 5 years
11. The conversation I had with a stranger on Trail 3 that I keep thinking about
12. What Islamabad looks like in January fog — a visual
13. I spent a week without my phone for an hour each morning — here's what happened
14. The thing about building things in Pakistan that nobody talks about
15. A birthday in Islamabad: what I did, where I went, what I felt
16. How I balance deep work with being present in life (still figuring it out)
17. The road from Islamabad to Murree — filmed it so you don't have to imagine
18. Friday jummah in G-7 — belonging in your own city
19. What I learned from shipping 3 products in one year
20. The version of this city most people never see

---

## Part 2 — Visual-First Strategy

### Primary: NotebookLM Infographic + Slides
When NLM quota is available:
1. Run `nlm research start` on the topic
2. Run `nlm infographic create` + `nlm slides create`
3. **Download infographic immediately** when ready (poll every 20s, up to 15min)
4. Post infographic to Slack for all channels
5. Use infographic as LinkedIn image (tech channel)
6. Post slides PDF to Slack separately

The infographic is the hero asset — it drives everything else.

### Fallback: Canva Deep Infographic (when NLM quota expired)
When NLM quota is exhausted, do NOT just run `canva_carousel.py` with shallow Claude research. Instead:

1. Run `claude_researcher.py` with a **deep** prompt — 5 specific facts with real numbers, Kamal's personal angle injected, emotional hook
2. Pass research to a new `canva_infographic.py` (to be built) that creates **one single-panel infographic** — not a multi-slide carousel
3. The infographic should match NotebookLM's style: clear header, icon-supported data points, clean layout, one emotion
4. Post to Slack + use on LinkedIn

The Canva infographic is built once per topic, not 6 carousel slides. Quality over quantity.

---

## Part 3 — Caption Rules Per Platform

### LinkedIn (tech only)
- First person, specific to what Kamal built/learned
- Opening line = a specific fact or observation (not a question, not a buzzword)
- 3 short paragraphs max, no bullet lists
- One genuine question at the end
- 3–4 hashtags on their own line at the end
- No: "Game changer", "Excited to share", "In today's fast-paced world", decorative emojis
- Model: `claude-sonnet-4-6` always

### Instagram / TikTok / Reels
- Emotional hook first line (delayed-answer technique)
- 3–4 bullet points with specific visual details
- "Save this" or "Swipe to see" CTA
- Question to drive comments
- 4 trending hashtags
- Sound like Kamal talking to a friend

### Vlog
- Full script format: HOOK → PROBLEM → SOLUTION → CTA
- Specific Islamabad locations always
- Cut markers every 2–4 seconds

---

## Part 4 — Pipeline Changes (What Gets Built)

### Change 1: Replace Reddit trend scanner as primary source
**File:** `content-scheduler.py`  
**Change:** Add `TOPIC_BANK` dict (60 seeds above) to the scheduler. `pick_topic()` first checks Notion for manually queued topics, then falls back to the bank (picks the one not used in the last 14 days), then uses trend scanner as supplementary signal only.

### Change 2: New `canva_infographic.py` script
**File:** `scripts/canva_infographic.py` (new)  
**What it does:** Creates a single professional infographic via Canva MCP — one panel, clear hierarchy, 5–6 data points with icons, NLM-quality layout. Takes: topic, track, hook, insights (list of 5), emotional angle. Returns: design_id, edit_url, export_url.

### Change 3: NLM fallback uses `canva_infographic.py`
**File:** `content-scheduler.py` `run_nlm_fallback()`  
**Change:** Replace `canva_carousel.py` call with `canva_infographic.py`. Still runs `claude_researcher.py` for the research, but outputs one infographic instead of a carousel.

### Change 4: LinkedIn gets infographic, not local PNG
**Already partially done (2026-06-03):** `wait_for_nlm_infographic()` added.  
**Remaining:** When NLM quota fails and Canva fallback runs, use the Canva infographic export as the LinkedIn image too.

### Change 5: Painting channel added
**File:** `content-scheduler.py`  
**Change:** Add `painting` to `TRACK_SUBREDDITS`, `TRACK_CHANNEL`, `HANDLES`. Add 20 painting topic seeds. Painting track: Slack DM only (no LinkedIn auto-post).

### Change 6: Topic bank seeded into Notion
**One-time:** Run a script to insert all 60 topic seeds into the Notion Content Calendar DB with `Status=Pending` and correct `Track` values. This gives a 2-month runway.

---

## Implementation Order

1. Seed Notion Content Calendar with 60 topics (one-time, immediate value)
2. Build `canva_infographic.py` — the Canva NLM-quality infographic
3. Update `run_nlm_fallback()` to use infographic not carousel
4. Update `pick_topic()` to use bank before trend scanner
5. Add painting channel
6. Test full pipeline end-to-end with a dry run

---

## What Does NOT Change

- NLM as primary visual tool — it stays, it's good
- The `nlm_poll_and_send()` background threading — keep it
- LinkedIn auto-post for tech only
- Slack DM for all channels
- Notion Content Log tracking
- Quality gates: caption must have personal angle, topic must pass Send Test
