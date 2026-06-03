# Rumi Platform — Architecture & Learning Plan

**Repo:** https://github.com/Orenda-Project/rumi-platform.git  
**Local clone:** `/home/oye/Documents/free_work/rumi-platform`  
**Date documented:** 2026-06-03  
**Purpose:** Kamil's complete reference for working on this platform in future sessions.

---

## What Is Rumi?

An **open-source AI teaching assistant on WhatsApp**. Teachers in rural/under-resourced schools send voice recordings, photos, and text — and get back coaching reports, lesson plans, reading assessments, quizzes, and educational videos. No app install required; works on the phone teachers already carry.

- **Open-source / cloneable:** any ministry, NGO, or school network can deploy their own instance
- **One instance = one WhatsApp number + Supabase DB + API keys**
- **Feature gating:** features turn on when API keys are present — no tiers, no flags

---

## Top-Level Structure

```
rumi-platform/
├── bot/                    # WhatsApp bot (Node.js 18+, Express.js) — MAIN SERVICE
├── infrastructure/         # Supabase schema (73 tables), RLS, seed, migrations
├── dashboard/              # Observability portal (Node/Express + EJS) — Phase 2, optional
├── portal/                 # Teacher web app (React + TypeScript + Vite) — Phase 2, optional
├── docs/                   # Architecture docs, per-feature specs (12 docs), cost guide
├── tests/                  # Jest (93 suites, 1,161 tests) — conformance + domain tests
├── .claude/                # Agent-native: CLAUDE.md router + 16 operational skills
└── scripts/                # CI/CD, doctor, setup scripts
```

---

## Tech Stack

### Bot (Core Service)
| Layer | Technology |
|-------|------------|
| Runtime | Node.js ≥18 |
| Framework | Express.js ^5.1.0 |
| Messaging | WhatsApp Business Cloud API v21.0 (Meta) |
| LLM | OpenRouter (primary, 500+ models) / OpenAI direct (fallback) |
| Database | Supabase (PostgreSQL managed) |
| Cache | Redis (session state, language pref) |
| Queue | AWS SQS (default) or BullMQ/Redis (pluggable) |
| STT | Soniox (primary), Whisper, Modal MMS-ASR |
| TTS | ElevenLabs, Uplift (Urdu) |
| Images/Video | Kie.ai (Nano Banana Pro), FFmpeg |
| OCR/Vision | Mistral Vision, Chandra, Surya |
| Pronunciation | Azure Speech SDK |
| Storage | Cloudflare R2 (S3-compatible) |
| PDF | PDFKit, pdfmake, Playwright |

### Dashboard (Phase 2)
Node/Express + EJS + Chart.js — same Supabase DB

### Portal (Phase 2)
React + TypeScript + Vite + TailwindCSS — same Supabase DB, deployed on Vercel/Netlify

---

## Key Files to Know

### Entry Points
| File | What It Does |
|------|-------------|
| `bot/whatsapp-bot.js` | Webhook receiver, message dispatch router |
| `bot/workers/sqs-worker.js` | Background job poller and dispatcher |
| `dashboard/index.js` | Dashboard Express app |
| `portal/src/App.tsx` | Portal React root |

### Configuration
| File | What It Does |
|------|-------------|
| `.env.template` | All 60+ env vars with comments |
| `bot/shared/config/feature-availability.js` | Source of truth: which features are live |
| `bot/shared/config/branding.js` | Bot name, org, language, URLs |
| `bot/shared/config/region-config.js` | Per-region behavior routing |
| `bot/shared/services/llm-client.js` | OpenRouter/OpenAI factory singleton |
| `bot/shared/config/supabase.js` | DB client singleton |

### Handlers (where messages land)
| File | Handles |
|------|---------|
| `bot/shared/handlers/text-message.handler.js` | Text commands (3,300+ lines, main router) |
| `bot/shared/handlers/voice-message.handler.js` | Voice notes → STT → feature routing |
| `bot/shared/handlers/image-message.handler.js` | Photo classification → pic-to-LP / exam |
| `bot/shared/handlers/flow-response.handler.js` | WhatsApp Flow form submissions |
| `bot/shared/handlers/exam-checker.handler.js` | Exam sheet OCR pipeline |

### Services (49 total in `bot/shared/services/`)
**Core:** `llm-client.js`, `whatsapp.service.js`, `session.service.js`  
**Coaching:** `coaching/coaching-orchestrator.service.js` + 5 support files  
**Reading:** `reading/analysis.service.js` (1,500+ lines) + 4 support files  
**Video:** `video/video-orchestrator.service.js` + 4 pipeline files  
**Lesson Plans:** `lesson-plan-template.service.js`, `lesson-plan-queue.service.js`  
**Queue:** `queue/index.js` (driver factory), `queue/drivers/sqs.js`, `queue/drivers/bullmq.js`

### Workers (10 job processors in `bot/workers/`)
`coaching-orchestrator`, `lesson-plan-generation`, `lesson-plan-extraction`, `pic-lp-kieai`, `video-generation`, `quiz-job-handler`, `exam-grading`, `homework-bundle`, `stale-session`

### Database
| File | Size |
|------|------|
| `infrastructure/supabase/00_complete-schema.sql` | 3,739 lines, 73 tables, 38 functions, 27 triggers, 186+ indexes |
| `infrastructure/supabase/01_rls-policies.sql` | Row-Level Security |
| `infrastructure/supabase/02_seed-data.sql` | Reference data |
| `infrastructure/scripts/bootstrap-db.js` | One-command setup: `npm run bootstrap:db` |

---

## Database Schema (Key Tables)

| Domain | Key Tables |
|--------|-----------|
| Users | `users` (phone_number UNIQUE, name, grade, registration_completed) |
| Sessions | `conversations`, `chat_sessions` |
| Coaching | `coaching_sessions` (audio_url, transcript, analysis_report JSONB, pdf_report_url, status) |
| Reading | `reading_assessments` (wcpm, accuracy_pct, comprehension_score, level) |
| Lesson Plans | `lesson_plans`, `lesson_plan_requests`, `pre_generated_lps` |
| Quizzes | `quizzes`, `quiz_sessions`, `quiz_questions`, `quiz_answers` |
| Video | `video_requests`, `video_tasks`, `student_videos` |
| Attendance | `attendance_sessions`, `attendance_records` |
| Exam | `exam_check_sessions`, `exam_submissions`, `exam_grades` |
| A/B Tests | `ab_tests`, `ab_test_variants`, `ab_test_events` (Thompson sampling bandit) |
| Region Config | `region_features` (fail-open: curriculum LP, frameworks, pic_lp per region) |

---

## Core Application Flows

### Message Routing
```
Meta Cloud API → POST /webhook
  → text?     → text-message.handler (3,300 lines — main router)
  → voice?    → voice-message.handler → STT → coaching/reading/attendance
  → image?    → image-message.handler → classify → pic-to-LP / exam
  → flow?     → flow-response.handler → parse form → store DB
  → status?   → broadcast status handler
```

### Async Job Pattern
```
Handler enqueues job (non-blocking, <1s)
  → Queue (SQS or BullMQ)
  → sqs-worker.js polls + dispatches
  → Worker runs pipeline (coaching: ~30s, video: ~3-5min)
  → Results stored in Supabase
  → Bot sends WhatsApp notification
```

### Coaching Pipeline
```
Voice recording → Soniox STT → transcript → LLM analysis
→ Framework scoring (OECD/TEACH/HOTS/FICO/Danielson)
→ PDF report + reflective questions (TTS via ElevenLabs)
→ R2 storage → WhatsApp delivery
```

### Reading Assessment
```
Passage selection → student reads aloud → Soniox STT
→ WCPM calculation, accuracy %, comprehension scoring
→ Optional: Azure phoneme-level feedback
→ PDF report + TTS feedback → WhatsApp
```

### Lesson Plan
```
Text request → curriculum intercept? → pre-generated LP (instant)
  → No match → LLM (5E framework) → PDF → R2 → WhatsApp
Photo request → vision OCR → LLM content → Kie.ai images → PDF → WhatsApp
```

### Video Generation
```
Topic → LLM script → Kie.ai keyframe images → FFmpeg animation
→ ElevenLabs narration → mix + watermark → R2 → WhatsApp
```

---

## Notable Architecture Patterns

### Presence-Based Feature Gating
No feature flags or tiers. Each feature lists which API keys it needs.  
`bot/shared/config/feature-availability.js` — if keys present → feature on.

### Pluggable Queue
`QUEUE_DRIVER=sqs` or `QUEUE_DRIVER=bullmq` — same interface, swap at config time.

### Correlation IDs
Every webhook request gets a UUID that flows through handler → queue → worker → logs.  
`bot/shared/utils/structured-logger.js`

### Graceful Degradation
Missing optional key → graceful "feature unavailable" message, never a crash.

### Region Config (fail-open)
`region_features` DB table: per-region curriculum paths, frameworks, languages.  
Missing region row → defaults apply.

### WhatsApp Flows (Interactive Forms)
RSA-encrypted form submissions for registration, attendance, quiz answers, settings.  
`FLOW_PRIVATE_KEY` + `FLOW_PUBLIC_KEY` — decrypted in `flow-encryption.service.js`.

### A/B Testing
Thompson sampling bandit via `bandit.service.js`. Tables: `ab_tests`, `ab_test_variants`, `ab_test_events`.

---

## Coaching Frameworks
OECD · TEACH · HOTS · FICO · Danielson  
Defined in: `bot/shared/services/coaching/frameworks/`  
Selectable per region via `region_features.observation_framework` or `DEFAULT_OBSERVATION_FRAMEWORK` env var.

---

## Infrastructure & Deployment

### Required Env Vars (8)
`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `OPENROUTER_API_KEY`, `REDIS_URL`,  
`WHATSAPP_TOKEN`, `PHONE_NUMBER_ID`, `WEBHOOK_VERIFY_TOKEN`, `WABA_ID`

### Setup Commands
```bash
npm install
cp .env.template .env  # fill in required vars
npm run doctor          # preflight check
npm run bootstrap:db    # create schema + RLS + seed
npm run setup:flows     # register WhatsApp Flows with Meta
npm start               # run bot (port 3000)
node bot/workers/sqs-worker.js  # run worker
```

### Deployment (Railway recommended)
Push to GitHub → Railway auto-deploys. Three processes: `web` (bot), `worker`, `dashboard`.  
`bot/Procfile` defines process types.

### CI/CD
GitHub Actions on every push:
1. Secret scan (gitleaks)
2. Schema + column conformance guards
3. 93 Jest suites (1,161 tests) — all mocked, no external services needed

---

## Agent-Native Design (.claude/)

The repo ships with 16 operational skills for AI agents working in this codebase:

| Skill | When to invoke |
|-------|---------------|
| `digital-coach` | Architecture orientation, orientation hub |
| `feature-tracer` | Trace a feature end-to-end |
| `debugging` | Root cause investigation, correlation-id tracing |
| `coaching` | Coaching pipeline changes |
| `reading-assessment` | Reading pipeline changes |
| `whatsapp-flows` | Build/modify WhatsApp Flows |
| `video-generation` | Video pipeline |
| `database-analysis` | Query the DB |
| `qa-testing` | Adding/fixing tests |
| `logging` | Add structured logging |
| `cross-agent-safety` | Edit shared services |
| `pre-merge-checklist` | Before any merge |
| `setup` | Platform setup |
| `customizing` | Adapt frameworks, languages, LLM |
| `registration` | User onboarding flow |
| `ab-testing` | A/B test setup |

**Rule:** When working in `bot/`, invoke the relevant skill before touching code.

---

## Learning Plan for Kamil

### Phase 1 — Orientation (1-2 hours)
1. Read `CLAUDE.md` (root) → `bot/CLAUDE.md` → `infrastructure/CLAUDE.md`
2. Read `docs/architecture.md` (message flow diagram)
3. Run `npm run doctor` in the clone (verify what's live)
4. Open `bot/whatsapp-bot.js` — trace a text message from `/webhook` to `text-message.handler.js`

### Phase 2 — Core Services (2-3 hours)
5. Read `bot/shared/config/feature-availability.js` — understand gating
6. Read `bot/shared/services/llm-client.js` — understand LLM interface
7. Read `bot/shared/services/queue/index.js` + both drivers — understand async job pattern
8. Read `bot/shared/handlers/text-message.handler.js` sections:
   - Feature detector call
   - Lesson-plan intercept
   - Coaching routing

### Phase 3 — Key Pipelines (3-4 hours)
9. **Coaching:** `coaching-orchestrator.service.js` → framework files → PDF report
10. **Reading:** `reading/analysis.service.js` — WCPM calc, comprehension scoring
11. **Lesson Plans:** `lesson-plan-template.service.js` → `docs/LP_PATHS.md`
12. **Video:** `video/video-orchestrator.service.js` → 4 pipeline files

### Phase 4 — Database & Testing (1-2 hours)
13. Skim `infrastructure/supabase/00_complete-schema.sql` — know the table domains
14. Read `tests/setup/` — conformance guards (schema, columns, flows, hygiene)
15. Run `npm test` — watch what passes, understand the domain test structure

### Phase 5 — WhatsApp Flows & Deployment (1 hour)
16. Invoke `.claude/skills/whatsapp-flows` skill — understand Flow lifecycle
17. Read `docs/railway-operations.md` — how to deploy and scale
18. Read `docs/agent-customization.md` — how to adapt frameworks, languages, LLM

### Quick Reference Commands
```bash
# Health check
npm run doctor

# Run tests
npm test

# Simulate a message without WhatsApp
node bot/scripts/simulate.js

# Check which features are available
node -e "require('./bot/shared/config/feature-availability').printMatrix()"

# Bootstrap DB (idempotent)
npm run bootstrap:db
```

---

## Files To Read First (Priority Order)

1. `/home/oye/Documents/free_work/rumi-platform/CLAUDE.md`
2. `/home/oye/Documents/free_work/rumi-platform/bot/CLAUDE.md`
3. `/home/oye/Documents/free_work/rumi-platform/docs/architecture.md`
4. `/home/oye/Documents/free_work/rumi-platform/bot/whatsapp-bot.js`
5. `/home/oye/Documents/free_work/rumi-platform/bot/shared/config/feature-availability.js`
6. `/home/oye/Documents/free_work/rumi-platform/bot/shared/handlers/text-message.handler.js`
7. `/home/oye/Documents/free_work/rumi-platform/bot/shared/services/llm-client.js`
8. `/home/oye/Documents/free_work/rumi-platform/infrastructure/supabase/00_complete-schema.sql`
