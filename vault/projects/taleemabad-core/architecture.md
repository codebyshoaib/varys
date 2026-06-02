---
name: taleemabad-core Architecture
description: App structure, key models, sync patterns, file paths
updated: 2026-06-02
---

# Architecture — taleemabad-core

## Directory Structure

```
taleemabad_core/
├── apps/
│   ├── analytics/
│   ├── asset_manager/
│   ├── book_library/          # BookChapter
│   ├── coaching/              # Core domain — observations, visits
│   │   ├── models.py          # CoachingObservation*, SchoolVisit*, Answer*
│   │   ├── serializers.py     # BasePushSyncSerializer subclasses
│   │   ├── push_sync_helpers.py
│   │   ├── views.py
│   │   ├── api/
│   │   ├── migrations/
│   │   └── tests/
│   ├── community/
│   ├── core/                  # Shared mixins
│   │   └── models.py          # SoftDeleteMixin, SoftDeleteAuditableMixin, TimeStampedModel
│   ├── exam_generator/
│   ├── fln_assessment/
│   ├── internal_apps/         # Retool integrations
│   ├── lesson_plan/           # CoreLessonPlan
│   ├── question_bank/
│   ├── schools/               # School, SchoolClassSubject, Announcement
│   ├── slo/                   # GradeSubject, LessonPlan, Subject
│   ├── student_learning/
│   ├── teacher_training/      # Assessment, Submission, TeacherTrainingStatus
│   ├── tenants/
│   └── users/                 # User, CoachProfile, TeacherProfile, PrincipalProfile, RegionalManagerProfile
├── settings/
├── urls.py
└── wsgi.py
```

## Key Models

### core (shared mixins)
- `SoftDeleteMixin` — adds `is_active` (BooleanField, default=True), `deleted_at`; overrides `save()` to set `deleted_at` on deactivation
- `SoftDeleteAuditableMixin(SoftDeleteMixin)` — adds audit fields
- `SoftDeleteAuditableMpttMixin(SoftDeleteMixin)` — MPTT tree + soft delete

### users
- `User` — base auth user
- `CoachProfile`, `TeacherProfile`, `PrincipalProfile`, `RegionalManagerProfile` — role profiles linked to User

### schools
- `School` — tenant root entity
- `SchoolClassSubject` — school × class × subject junction
- `Announcement`, `UserAnnouncement` — notification system

### coaching
- `CoachingObservation*` — observation forms for coaches visiting schools
- `SchoolVisit*` — school visit records
- Uses `GenericForeignKey` (GFK) for polymorphic user profile attachment (`gfk_helpers.py`)
- Uses `db_validators.py` for cross-table consistency checks

### teacher_training
- `Assessment`, `Submission`, `TeacherTrainingStatus`

### slo
- `GradeSubject`, `Subject`, `LessonPlan`

## Offline-First Sync Pattern (Push Sync)

The frontend (React + Dexie.js on IndexedDB) is offline-first. Sync uses a push model:

1. **Frontend writes** to Dexie locally, queues records with `updated_at` timestamps
2. **Sync push** calls DRF endpoints with `BasePushSyncSerializer`
3. **Backend merges** — timestamp-wins conflict resolution
4. **Dexie schema versioning** — `db.version(N).stores(...)` must be incremented on any schema change; use `db.transaction()` for multi-table writes to avoid partial state

Key files:
- `taleemabad_core/apps/coaching/push_sync_helpers.py` — server-side sync helpers
- `taleemabad_core/apps/coaching/serializers.py` — `BasePushSyncSerializer` subclasses
- Frontend: `api/teachertraining.ts` — every write must include `profileId` in key AND filter

## Harness Feature Folder

Every feature produces artifacts at:
```
.claude/features/YYYY-MM-DD-<feature>/
├── research.md
├── plan.md
├── develop.md
├── bugs.md
├── test-findings.md
├── confidence.md
└── status.md
```

## CI/CD
- GitHub Actions on PR → tests → linter → type-check
- Migrations tested for reversibility before merge
- Docker image built on merge to main
- Staging deploy automatic; production manual
