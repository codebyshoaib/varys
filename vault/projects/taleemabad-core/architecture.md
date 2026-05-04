---
name: taleemabad-core Architecture
description: Technical architecture, patterns, design decisions
---

# Architecture — taleemabad-core

## Tech Stack
- **Framework**: Django REST Framework (DRF)
- **Language**: Python 3.x
- **Database**: PostgreSQL
- **Queue**: Celery with Redis
- **Testing**: pytest + Django test client
- **Deployment**: Docker + GitHub Actions

## Core Modules

### `apps/training/`
- **Models**: Training, Level, TrainingMedia
- **Serializers**: TrainingSerializer, LevelSerializer
- **Views**: TrainingViewSet, LevelViewSet
- **Endpoints**: `/api/v1/trainings/`, `/api/v1/levels/`
- **Purpose**: Training CRUD, level hierarchy, asset relationships

### `apps/quiz/`
- **Models**: Quiz, QuizQuestion, QuizAnswer, QuizResult
- **Serializers**: QuizSerializer, QuizResultSerializer
- **Views**: QuizViewSet, QuizResultViewSet
- **Endpoints**: `/api/v1/quizzes/`, `/api/v1/quiz_results/`
- **Features**: Score calculation, answer validation, result storage

### `apps/media_assets/`
- **Models**: MediaAsset
- **Views**: PresignedURLView
- **Endpoint**: `POST /api/v1/internal/media_assets/presigned_upload_url/`
- **Purpose**: Generate S3 presigned URLs for browser uploads
- **Integration**: Boto3 for AWS SDK

### `apps/user_progress/`
- **Models**: UserProgress
- **Purpose**: Track training completion, quiz scores, learning paths
- **Endpoints**: `/api/v1/user_progress/`

### `apps/niete_sync/`
- **Celery Task**: `sync_niete_learners()`
- **Purpose**: Pull user list from NIETE API, sync completion status
- **Schedule**: Daily at 9 AM
- **Retry**: 3 times with exponential backoff

### `apps/feedback/`
- **Celery Task**: `generate_quiz_feedback(quiz_result_id)`
- **Purpose**: Call Claude API to generate personalized feedback
- **Async**: Decoupled from request/response cycle
- **Integration**: LLM API for feedback generation

## Design Patterns

### ViewSet Pattern (DRF)
- Combines list, retrieve, create, update, delete into single class
- Automatic routing via SimpleRouter
- Example: TrainingViewSet handles all `/api/v1/trainings/*` endpoints

### Serializer-Model Pairs
- Model: Database representation
- Serializer: Request/response validation and transformation
- Example: Training model + TrainingSerializer for API contract

### Celery Async Tasks
- Long-running operations (feedback, NIETE sync) as background tasks
- Redis broker for task queue
- Retry policy for failed tasks
- No blocking of request/response

### JWT Authentication
- Token issued by [[taleemabad-auth]]
- Middleware validates tokens on protected endpoints
- Permission classes: IsAuthenticated, IsAdminUser, custom

## Testing Strategy

### Unit Tests
- Test model methods (calculations, validations)
- Test serializer field validation
- Test API responses with mocked dependencies
- File: `apps/*/tests.py`

### Integration Tests
- Test full request/response cycle
- Hit real database (test DB)
- Celery task execution with test broker
- Example: Quiz submission → score calculation → feedback task queued

### Database Tests
- Migrations tested (schema changes are reversible)
- Concurrent write scenarios
- Foreign key constraints verified

### No Mocking Rule
- Database: Use test DB, not mocks
- Celery: Use test broker, not mocks
- External APIs: Use staging endpoints or fixtures, not mocks

## Deployment Architecture

### CI/CD Pipeline
- GitHub Actions on push/PR
- Run tests → type-check → build Docker image
- Push to staging on merge to main
- Manual trigger for production

### Database Migrations
- Use Django migrations for all schema changes
- Migrations are reversible (avoid data loss operations)
- Test migrations before deploying to staging
- Coordinate with team before production deployment

### Environment Variables
- `.env.local` for development
- `.env.staging`, `.env.production` for deployed environments
- Secrets (DB password, AWS keys, API tokens) stored in GitHub Secrets
