---
name: taleemabad-core
description: Django LMS backend for training system
---

# taleemabad-core — Training LMS Backend

## Overview
- **GitHub**: Taleemabad organization (private)
- **Local Path**: `/home/oye/Documents/taleemabad-core`
- **Tech Stack**: Django, PostgreSQL, Celery, DRF
- **Purpose**: RESTful API for training management, quizzes, progress tracking, AI feedback
- **Status**: Active development
- **Primary Consumer**: [[taleemabad-cms]] (React frontend)

## Key Components

### Training Management
- Models: Training, Level
- Endpoints: `/api/v1/trainings/`
- Features: CRUD, level hierarchy, asset linking

### Quiz System
- Models: Quiz, QuizQuestion, QuizAnswer, QuizResult
- Endpoints: `/api/v1/quiz_results/` (submission, grading)
- Features: Score calculation, answer validation

### Media Assets (S3)
- Presigned URL generation: `POST /api/v1/internal/media_assets/presigned_upload_url/`
- Browser-to-S3 uploads (no backend file handling)
- Metadata storage in database

### User Progress & AI Feedback
- Celery task for async feedback generation
- NIETE learner sync
- Progress tracking and completion status

### Authentication
- JWT tokens via [[taleemabad-auth]]
- Token validation middleware
- User roles and permissions

## Testing Standards

**Unit Tests**: Every model and endpoint
**Database**: Test DB (Django default)
**Integration Tests**: Celery + Redis, S3 presigned URLs
**Coverage**: Minimum 80%

**Command**: `python manage.py test` or `pytest`

See [[vault/memory/taleemabad_core_path]] for detailed technical reference.

## Related Files
- [[architecture]] — Tech stack, modules, patterns
- [[decisions]] — ADRs and why decisions were made
- [[related]] — Links to taleemabad-cms, taleemabad-auth
