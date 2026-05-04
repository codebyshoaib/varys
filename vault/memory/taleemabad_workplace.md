---
name: Taleemabad Workplace
description: Kamal's employer and primary work context
type: project
---

# Taleemabad — Workplace Context

## Organization
- **Name**: Taleemabad
- **Domain**: Education technology, training management
- **Location**: Primary contact via NIETE (National Institute of Education & Training Excellence)
- **Collaborator**: Anam Masood (anam.masood@niete.pk) — sends implementation tasks

## Projects Owned / Led

### Training LMS Backend (taleemabad-core)
- **Tech**: Django REST API, PostgreSQL, Celery
- **Purpose**: Levels, quizzes, AI feedback, training progress tracking
- **Endpoints**: Training CRUD, quiz results, AI feedback, NIETE sync

### Content Management System (taleemabad-cms)
- **Tech**: React 19, Vite, TypeScript, TailwindCSS
- **Purpose**: Manage trainings, upload media assets, build quiz content
- **Features**: Presigned S3 upload, asset library, training form builder

### Authentication (taleemabad-auth)
- **Tech**: JWT-based middleware
- **Purpose**: Token issuance and validation across services
- **Shared**: Used by both core and cms

## Key Concerns

### Media Assets (S3)
- Separate S3 bucket for CMS
- Presigned URLs for browser-to-S3 uploads (no backend file handling)
- Bucket mapping and credential sets managed in `[[vault/memory/media_assets_api]]`

### Database & Migrations
- PostgreSQL backend
- All migrations tested before deploy
- Never force migrations in production

### Async Tasks (Celery)
- Background jobs for email, notifications, data processing
- Integration tests required; must hit real Redis/Celery, not mocks

## Contact & Process

- **Jira Project**: MC20 on `orendatrust.atlassian.net`
- **Auto-Jira Hook**: `hooks/auto-jira.py` creates MC20 tickets via API
- **Jira Token**: Stored at `~/.claude/hooks/.jira`
- **Email**: Work tracked in `vault/domains/taleemabad/work-log.md`

## Deployment

- **Staging**: Test environment; OK to deploy frequently
- **Production**: Requires verification; coordinate with Anam if uncertain
- **CI/CD**: GitHub Actions (verify before push)
