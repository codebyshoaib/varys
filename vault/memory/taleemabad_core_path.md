---
name: Taleemabad Core Path
description: Django backend location and key technical context
type: reference
---

# taleemabad-core — Backend Reference

## Location
- **Actual path**: `/home/oye/Documents/taleemabad-core` (NOT in repos/)
- **GitHub**: Stored in Taleemabad organization
- **Note**: There is a `repos/taleemabad-core` symlink in personal-agent-v2 for consistency

## Tech Stack
- **Framework**: Django REST Framework (DRF)
- **Database**: PostgreSQL
- **Queue**: Celery with Redis
- **Testing**: pytest with fixtures
- **Auth**: JWT tokens via taleemabad-auth middleware

## Key Modules

### Training Management (`apps/training/`)
- Model: Training (title, level, description, assets)
- Endpoints: `/api/v1/trainings/` (list, create, retrieve, update, delete)
- Relationships: Many-to-many with levels, quizzes, users

### Quiz System (`apps/quiz/`)
- Models: Quiz, QuizQuestion, QuizAnswer, QuizResult
- Endpoints: `/api/v1/quiz_results/` (submission, grading)
- AI Feedback: Celery task for generating personalized feedback

### Media Assets (`apps/media_assets/`)
- S3 integration with presigned URLs
- Endpoint: `POST /api/v1/internal/media_assets/presigned_upload_url/`
- Returns temporary S3 upload URL; browser uploads directly

### User Progress (`apps/user_progress/`)
- Tracks user training completion, quiz scores
- NIETE sync: pulls user list from NIETE, syncs completion status

## Testing Standards

### Unit Tests
- **Requirement**: Every model and endpoint must have tests
- **Database**: Use test database (Django automatically creates; pytest fixtures manage)
- **Coverage**: Minimum 80% coverage required
- **Command**: `python manage.py test` or `pytest`

### Integration Tests
- **Requirement**: Celery tasks must have integration tests hitting real Redis
- **Requirement**: S3 presigned URL endpoint tested with real AWS SDK
- **Requirement**: NIETE sync tested against staging API

### E2E Tests (Backlog)
- Automation harness planned for taleemabad-core
- auto-browser for form submission flows
- Once built, will verify: training create → upload asset → generate quiz → submit result

## Migrations

- **Always tested**: Never deploy untested migrations
- **Reversible**: Design migrations to be reversible (avoid data loss operations)
- **Concurrent writes**: Test migrations under load; Kamal has experience with Django locking

## Deployment

- **CI**: GitHub Actions runs tests before merge
- **Staging**: Automatic on push to staging branch
- **Production**: Manual trigger; requires verification of migrations and tests
