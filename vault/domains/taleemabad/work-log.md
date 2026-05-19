# Taleemabad Work Log

Tracks tasks shared by collaborators at Taleemabad/NIETE.

---

## 2026-04-23 — GBTLA Deployment Timeline — Oxbridge (FYI)

**From:** Manzil e Maqsood, CEO Oxbridge Innovative Solutions  
**Content:** Formal declaration of IP ownership + implementation framework for GBTLA (Game-Based Teaching, Learning and Assessment)

### Deployment Schedule
- **Phase 1 (Training Modules):** Deployed by **April 27, 2026** — 7 structured modules
- **Phase 2 (Lesson Plans):** Deployed by **May 4, 2026** — curriculum-aligned lesson plans (Grades 6-12)

### What's Included
- 7 training modules (foundations → implementation → assessment → advanced applications)
- Lesson plans for Grades 6-12 (Computer Science, Science, Biology, Chemistry, Physics)
- Integrated assessment tools, embedded games, MCQ quizzes
- LMS-based deployment via NIETE

### Notes
- IP owned by Oxbridge + Ministry of Planning, Development & Special Initiatives
- Content restricted to FDE teacher training + classroom contexts
- Progressive access model (quizzes required to unlock next module)
- Status: FYI — no response required. CMS problem already solved ✅

---

## 2026-04-20 — Oxbridge Certificate Training Feature ✅ COMPLETE

**Feature:** Vendor-specific training certificates with database metadata + FE PDF generation  
**Vendor:** Oxbridge Innovative Solutions (Pvt.) Ltd.  
**Teacher Levels:** Middle & High school teachers  
**Branch:** `feat/FE-adding-new-vender` (taleemabad-core)  
**Status:** ✅ COMPLETE — PR submitted for review

### Backend Implementation (Tasks 1-6) ✅ COMPLETE
- ✅ Certificate model (profile, course, assessment, vendor, teacher_name, training_name, completion_date, certificate_code, metadata)
- ✅ Custom managers (active/all objects)
- ✅ Serializers (CertificateSyncSerializer)
- ✅ Signals (auto-issue certificates on assessment pass, unique code generation)
- ✅ v3 Sync API integration (CourseSyncV3APIView updated to include certificates)
- ✅ Oxbridge training level created (Level record with vendor=OXBRIDGE)
- ✅ Comprehensive tests (243 lines model + 274 lines signals + 104 lines serializers + 174 lines sync)

**Commit:** `1aa7124af - feat: Add Certificate model and related functionality`

### Frontend Implementation (Tasks 7-10) ✅ COMPLETE
- ✅ Task 7: Oxbridge HTML certificate template with Navy branding
- ✅ Task 8: FE components (CertificateStorage, CertificateRenderer, CertificateDownload)
- ✅ Task 9: Training Selection UI (level filtering for Oxbridge eligibility)
- ✅ Task 10: Full integration & testing (sync + PDF download)

### Key Implementation Details
- **Certificate Code Format:** `OX-YYYYMMDDHHMM-RANDOM` (e.g., `OX-202604131023-a7f3c9`)
- **Metadata:** Stored as JSON (issuer, signatory, logo_url, colors for vendor branding)
- **Sync:** v3 API delivers certificate data to offline-first app
- **PDF:** Client-side rendering with jsPDF/html2pdf on FE
- **PR:** Submitted on `feat/FE-adding-new-vender` branch

### Documents
- **Feature Note:** `workspace/projects/oxbridge-training/oxbridge-certificate-feature.md` (updated)
- **Implementation Plan:** `workspace/projects/oxbridge-training/implementation-plan.md`

---

## 2026-04-20 — Taleemabad-University Code Review (Orenda Repo #4)

**Task:** Systematic review of Taleemabad-University (multi-agent LMS platform)  
**Status:** ✅ COMPLETE — 9 GitHub issues created

### Issues Found & Created

| # | Title | Severity | Category |
|---|---|---|---|
| [#1](https://github.com/Orenda-Project/Taleemabad-University/issues/1) | Missing root CLAUDE.md for team onboarding | LOW | Docs |
| [#2](https://github.com/Orenda-Project/Taleemabad-University/issues/2) | SQL Injection in agent tools: runSqlQuery | HIGH | Security |
| [#3](https://github.com/Orenda-Project/Taleemabad-University/issues/3) | Webhook lacks signature verification from Skribby | CRITICAL | Security |
| [#4](https://github.com/Orenda-Project/Taleemabad-University/issues/4) | Webhook endpoint accepts unauthenticated requests | HIGH | Security |
| [#5](https://github.com/Orenda-Project/Taleemabad-University/issues/5) | Webhook processing via setImmediate — data loss risk | MEDIUM | Reliability |
| [#6](https://github.com/Orenda-Project/Taleemabad-University/issues/6) | Low test coverage — only 2 test files | MEDIUM | QA |
| [#7](https://github.com/Orenda-Project/Taleemabad-University/issues/7) | Too many console.log statements — needs structured logging | LOW-MEDIUM | Observability |
| [#8](https://github.com/Orenda-Project/Taleemabad-University/issues/8) | Missing .env.example documentation | LOW | Docs |
| [#9](https://github.com/Orenda-Project/Taleemabad-University/issues/9) | Integrate shared skills to reduce token waste | LOW | Architecture |

### Key Findings

**Security (Critical → High):**
- Webhook (/api/webhooks/skribby) — no HMAC signature verification, no authentication, accepts arbitrary sessionIds
- Agent tools — runSqlQuery executes unsanitized SQL despite SELECT-only claim
- Risk: Any attacker can modify session state, extract data, or trigger expensive queries

**Quality:**
- Test coverage extremely low (2 test files for 23-table schema + 6-agent system)
- 28+ console.log statements scattered through routes (should use structured logging)
- Webhook processing uses setImmediate without error handling/retry (data loss risk)

**Docs & DevEx:**
- No .env.example — developers don't know required credentials
- No root CLAUDE.md — team setup unclear
- Opportunity to use shared skills repo to reduce token waste in agent loops

### Tech Stack Verified
- Monorepo: pnpm workspaces (apps/api, apps/web, packages/shared)
- Backend: Express.js + Drizzle ORM + PostgreSQL (23 tables)
- Job queue: pg-boss (PostgreSQL-native)
- Auth: Google SSO + JWT (domain allowlist: taleemabad.com, niete.edu.pk)
- RBAC: Dynamic roles/permissions in DB
- External DB: Capacity Lab (Neo4j via bolt://)
- Tests: Vitest (unit/integration), Playwright (E2E)

### Next Steps
All 9 issues linked on GitHub. Highest priority: #2 (SQL injection), #3 (webhook signature), #6 (test coverage).

---

## 2026-04-09 — Email Summary

**Incoming emails:** 22 new since 2026-04-08

### 🔴 ACTION NEEDED
- **Mashhood Rastgar (Teams):** API compliance issue — `compliance-bugsence-tracker-key` disabled. Needs replacement with OAUTH. Remove all API keys.
- **Lesson Plan Assistant Monitoring:** Service went DOWN (06:41) then UP (06:56). Verify full health check.

### ℹ️ FYI / Ongoing
- **Observations Visibility Meeting:** Wed Apr 8, 2pm (calendar invite from Fatima Rahman) — check if attended
- **Muhammad Saim Probation Assessment:** HR thread (Aymen, Mashhood, Javariya, Kamal CC'd) — ongoing discussion
- **WFH Friday Guidelines:** Memo from Javariya (informational)
- **Ollama signup confirmation:** Kamal just joined community

---

## 2026-04-07 — BH-TT FDS: Model Fit Analysis (taleemabad-core)

- **From/Context:** Afifa Sultana — BH-TT SRD v2.0 (Beaconhouse FDS, NIETE app)
- **Summary:** Reviewed existing teacher_training models against BH FDS requirements. See analysis below.
- **Action taken:** Full model fit analysis done (see plans/)
- **Next action:** Build when videos arrive from Beaconhouse + internal decisions resolved

### What already exists ✅
- `Level` → maps to Subject Track (already has `vendor=BEACONHOUSE`, `passing_score`, `max_attempts`)
- `Course` → maps to Module (has `subject` FK, `course_quiz_title/instructions`)
- `Training` → maps to Content Item (video/reading, has `media_asset`)
- `Question` → maps to MCQ (has `hints`, belongs to Training/Course/GrandQuiz)
- `Assessment` → tracks attempts (`attempt_number`, `is_passed`, `score`)
- `TeacherTrainingStatus` → tracks per-training completion

### What's missing ❌
- Sequential lock-next logic (no lock field on Course/Training)
- MCQ bank size (15Q bank → draw 10) — no config on Course
- Course-level `passing_score` / `max_attempts` (only on Level)
- `ShortTask` model (file upload + mentor grading)
- `ReflectiveQuestion` model (or reuse open-ended Question)
- `Badge` model (subject-level, auto-issued)
- AI Literacy deduplication (complete once, mark across all tracks)
- Teacher → subject auto-assignment logic

## 2026-04-07 — Fuel Price Impact Meeting + Teams Mentions

- **From/Context:** Zeshan Ali Dhillon (zeshan.dhillon@taleemabad.com)
- **Summary:** Company-wide meeting Tue Apr 7, 4–4:45 PM on fuel price surge impact and commute decision. Open Q&A included.
- **Action taken:** None yet
- **Next action:** Attend or review notes after meeting

## 2026-04-07 — Resignation: Mahnoor Shafique — Mashhood Reply

- **From/Context:** Mashhood Rastgar (mashhood.rastgar@taleemabad.com)
- **Summary:** Mashhood replied to Mahnoor's resignation letter thread
- **Action taken:** None yet (draft reply was previously ready for Kamal to approve)
- **Next action:** Review Mashhood's reply and send Kamal's response if still pending

## 2026-04-07 — Gul Perwasha 1:1 — Agent Flow

- **From/Context:** Gul Perwasha (gul.perwasha@taleemabad.com)
- **Summary:** Meeting scheduled Tue Apr 7, 1:30–2:00 PM to understand agent flow
- **Action taken:** Accepted/declined status unknown
- **Next action:** Check calendar response status

## 2026-04-06 — Principal Dashboard Feature (taleemabad-core)

**Task:** Build Principal Dashboard — share school progress data with principals
**Project:** taleemabad-core
**Collaborator:** Fatima Rahman (fatima.rahman@taleemabad.com)
**Status:** In progress
**Jira:** [MC20-17145](https://orendatrust.atlassian.net/browse/MC20-17145)

### Plan
1. Fatima prepares the feature spec/doc
2. Kamal reviews and guides Fatima through implementation in taleemabad-core

### Notes
- Dashboard surfaces school-level progress to principals
- Kamal is acting as tech lead / guide for Fatima on this feature

---

## 2026-04-02 — 🔴 End Cycle Review: Phase 2 (TODAY)

**Meeting:** End of Cycle Review — Q&A Session
**When:** Thursday Apr 2 | 11:00 AM – 1:00 PM (ICT slot: **12:15 – 1:00 PM**)
**Format:** Hybrid — in-person at I-10 + online
**Shared by:** Usman Imtiaz (via Teams)

**Kamal's slot — ICT Region (12:15–1:00 PM)**
Teams presenting: LP team + EG team + Schema + CRO + Teacher Promotion Policy + **Teacher Training**
In-room: Bilal, Asma, Hashir, Waheed, Sara, Hataf, Umama, Kamran, Mahnoor, Nimra, Zeeshan

**What this is:** Teams walk leadership through Q1 Rock documentation, address questions, align on Q2 path forward.
**Kamal's prep:** Be ready to present/answer questions on Teacher Training Q1 progress.

---

## 2026-04-02 — FDE Meeting Action Items (Meeting: 01/04/2026)

**Meeting:** FDE Committee Room, 1st April 2026, 1:00 PM
**Attendees:** Ma'am Riffat Jabeen, Fiaz sab, Haroon Yasin, Ali Sipra + NIETE/Taleemabad team
**Shared by:** Bilal Sadiq (via Teams)

### Kamal's Action Items
- [x] **Add training content list on dashboard** for Ma'am Riffat — with Momina Raja — done 2026-04-06
- [x] **Make Level 2 & 3 live for Middle and High school** — with Anam Masood — done 2026-04-06

### Other Team Action Items (for awareness)
| Action | Owners |
|--------|--------|
| Fix teacher-school mapping issue on dashboard | Hashir Hussain, Muhammad Haris, Zeeshan Usaid |
| Data analysis on primary student outcomes | Muhammad Muzzammil Patel, Sara Fatima |
| Onboard all middle school teachers before Apr 20, start Level 2 & 3 training | Anam Masood |
| Onboard Academic Vice Principals (Middle & High) on NIETE app + dashboard | Anam Masood, Bilal |
| Create marketing video — NIETE program lifecycle | Mahnoor Tanweer |
| Share detailed workings of assigned vs utilized funds (contract + PC-1) | Jahan Zaib Sherwani, Saad Zahid |
| Prepare for internal audit (documents + invoices) | Jahan Zaib Sherwani |
| Submit signed addendum + funds appropriation + studio PO | Bilal |
| Clarify PMU process for addendum-2 validity + funds reappropriation | Bilal |
| Develop NIETE Institute plan for PC-1 | Bilal |
| Assign finance POC + FDE focal person for documentation | Bilal, Jahan Zaib Sherwani |

---

## 2026-04-02 — Lesson Plan Assistant downtime

- **Alert:** LP Assistant (lp-assistant.taleemabad.com) went down at 10:43 AM PKT, recovered by 10:48 AM PKT (~5 min outage)
- **Source:** Uptime Kuma alert emails

---

## 2026-04-02 — Teacher Training Collaboration (NIETE / Oxbridge)

- **Project:** Smart Schools Project - GBTLA (Government Beaconhouse Teacher Learning Alliance)
- **Parties:** Oxbridge (Abrar) → NIETE (Anam) → Taleemabad LMS (Kamal)
- **Thread:** Follow-up on teacher training collaboration
- **Update (Apr 1):** Abrar shared Google Drive folder with 2 recorded training sessions + quizzes organized by session
  - Drive: https://drive.google.com/drive/folders/1VsVAJVx8tLbi9pKre-mzqmu51fER0NQy
- **Kamal's response (Apr 1):** Clarified 3 LMS technical points:
  1. MP4 videos supported natively
  2. MCQ (single) + MSQ (multiple) quiz types supported; open-ended also possible (adds complexity)
  3. No Google Forms API integration — can embed link or use built-in quiz builder
- **Anam (Apr 1):** Chasing Saher Waheed (saherwaheed@concordia.edu.pk) for FDE LMS content + final roadmap doc — new academic year starting early April
- **Saher's last update (Mar 16):** Data uploaded to drive, videos + final roadmap still pending
- **Status:** Waiting on Abrar to review Kamal's reply and finalize quiz/video upload. Also waiting on Saher for FDE LMS content.
- **Action taken (2026-04-02):** Replied to Abrar — confirmed MCQ/MSQ/scoring/unlock all supported. Flagged missing per-option feedback content, asked them to add correct/incorrect explanations per answer option.
- **Next action:** Wait for Abrar to share updated quiz doc with per-option feedback

---

## 2026-04-02 — Jira Weekly Recap (Apr 1)

Unassigned tickets flagged in weekly digest:
- **MC20-16948** — Recording limit reached - should hide resume button
- **MC20-16751** — Configure unit testing for the platform and implement test cases
- **MC20-16492** — IAM ajlal User
- **MC20-16813** — testing
- **MC20-16493** — Logs guide for End users
- **MC20-16494** — Langfuse Query
- **MC20-16454** — test

---

## 2026-04-02 — Calendar / Meetings

- **Eid Celebrations & One Dish Party** — Fri Apr 3, 2pm–4pm PKT (invited by Javariya Mufarrakh)
- **Monthly Eng Sync Up** — Fri Apr 10, 4pm–4:45pm PKT (updated by Aymen Abid)
- **Weekly Sync: Functional Rocks Engineering** — Weekly Thu 12pm–1pm PKT (new recurring, set by Usman Imtiaz)

---

## 2026-04-02 — Team Update

- **Mahnoor Shafique** (Senior SWE) submitted resignation — last working day April 30, 2026 (1-month notice)

---

## 2026-04-14 — Taleemabad-Auth Comprehensive Review

**Task:** Conduct detailed security & architecture review of Taleemabad-Auth service  
**Repo:** https://github.com/Orenda-Project/Taleemabad-Auth (Go + PostgreSQL)  
**Status:** ✅ DONE  
**Scope:** Thorough analysis across codebase, architecture, endpoints, security

### Review Completed
- ✅ Full architecture analysis (multi-tenant JWT auth service)
- ✅ Identified core features (login/refresh/logout, password reset, PII encryption, brute-force protection, rate limiting, audit logging)
- ✅ Documented project structure, API endpoints, environment setup
- ✅ Evaluated role hierarchy and data flow across Taleemabad services
- ✅ Created comprehensive review document: `workspace/projects/taleemabad-auth.md`

### Issues Created & Pushed to GitHub
- **Issue #3:** [Missing CLAUDE.md](https://github.com/Orenda-Project/Taleemabad-Auth/issues/3) — workspace automation config
- **Issue #4:** [Missing Swagger/OpenAPI](https://github.com/Orenda-Project/Taleemabad-Auth/issues/4) — auto-generated API docs
- **Issue #5:** [Missing Taleemabad Integration Architecture](https://github.com/Orenda-Project/Taleemabad-Auth/issues/5) — critical: user ownership, role levels, deletion flows, sync strategy

### Key Architectural Gaps Flagged
1. **User Data Ownership** — unclear if Auth Service or taleemabad-core is source of truth
2. **Role Level Definitions** — Teachers/Principals/Admins need clear level assignments (50/75/100?)
3. **Permission Model** — Fine-grained vs level-based access control unclear
4. **Deletion Flow** — No documented user deletion synchronization between services
5. **Sync Strategy** — User creation/update flows not defined across CMS, Core, Mobile

---

## 2026-03-31 — Enable Level 2 & Level 3 for mid/high teachers

- **From:** Anam Masood (anam.masood@niete.pk)
- **Task:** Enable Level 2 and Level 3 for mid and high teachers
- **Jira:** [MC20-17099](https://orendatrust.atlassian.net/browse/MC20-17099)
- **PR:** [#4758 — Engineering one prompt fixture](https://github.com/Orenda-Project/taleemabad-core/pull/4758)
- **Status:** done
- **Completed:** 2026-04-01
