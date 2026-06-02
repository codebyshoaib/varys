---
name: taleemabad-core
description: Multi-tenant Django LMS backend — the primary API server for Taleemabad's educational platform
updated: 2026-06-02
---

# taleemabad-core — Project Reference

## Overview
- **Local Path**: `/home/oye/Documents/taleemabad-core`
- **GitHub**: Taleemabad organization (private)
- **Purpose**: Multi-tenant educational platform REST API — coaching, teacher training, school management, offline sync
- **Primary Consumer**: taleemabad-cms (React / Nx monorepo frontend using Dexie.js offline-first)
- **Status**: Active development

## Tech Stack

| Layer | Tech | Notes |
|---|---|---|
| Language | Python 3.10 | |
| Framework | Django 4.2.8, DRF 3.14.0 | |
| Database | PostgreSQL 15 | Schema-isolated multi-tenancy via django-tenants |
| Cache/Queue | Redis 7 + Celery 5.3 | RabbitMQ as broker |
| Multi-tenancy | django-tenants | Every model must be tenant-scoped |
| Frontend sync | Dexie.js (IndexedDB) | Offline-first, push-sync via BasePushSyncSerializer |
| Code quality | black, isort, flake8, mypy, ESLint | Pre-commit enforced |
| Auth | JWT (from taleemabad-auth service) | |

## Django Apps (taleemabad_core/apps/)

| App | Purpose |
|---|---|
| `analytics` | Event tracking, usage analytics |
| `asset_manager` | S3 presigned uploads, media metadata |
| `book_library` | BookChapter and related library content |
| `coaching` | Coaching observations, school visits, answers — core domain |
| `community` | Community/discussion features |
| `core` | Shared mixins: SoftDeleteMixin, SoftDeleteAuditableMixin, TimeStampedModel |
| `exam_generator` | Exam generation tooling |
| `fln_assessment` | FLN (Foundational Literacy & Numeracy) assessments |
| `internal_apps` | Retool and internal tooling integrations |
| `lesson_plan` | CoreLessonPlan model, lesson plan management |
| `question_bank` | Reusable question pool |
| `schools` | School, SchoolClassSubject, Announcement, UserAnnouncement — tenant root |
| `slo` | Subject Learning Outcomes, GradeSubject, LessonPlan, Subject |
| `student_learning` | Student-level progress and learning tracking |
| `teacher_training` | Assessment, Submission, TeacherTrainingStatus |
| `tenants` | Tenant provisioning, schema management |
| `users` | User, CoachProfile, TeacherProfile, PrincipalProfile, RegionalManagerProfile |

## Non-Negotiable Constraints

1. **Test coverage ≥ 85%** — enforced at `/test` phase; gate blocks merge
2. **Confidence score ≥ 86%** — required before any PR is shipped
3. **Multi-tenancy** — every model/endpoint must be tenant-scoped; no cross-tenant leaks
4. **Soft-delete only** — `is_active=False` + `deleted_at`, never hard DELETE
5. **Reversible migrations** — every migration must have a tested `database_backwards`
6. **Linter score ≥ 95%** — black, isort, flake8, mypy all pass
7. **No `any` types** — mypy strict on all new code
8. **Never work on `develop` branch directly** — always feature branch → PR

## Harness Commands (inside taleemabad-core sessions)

```
/feature <name>   — Research + plan (outputs to .claude/features/YYYY-MM-DD-<name>/)
/develop <name>   — Implement approved plan
/test <name>      — Run validation + confidence scoring
/fix <name>       — Loop until ≥86%
/audit            — Security + code quality audit
```
