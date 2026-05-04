---
name: Taleemabad Training Project
description: Training LMS backend system for NIETE integration
type: project
---

# Training LMS Backend — System Overview

## Purpose
Training management system for learners: create levels, build quizzes, track progress, generate AI feedback. Primary consumer: NIETE (National Institute of Education & Training Excellence).

## Core Components

### Levels
- Hierarchical: beginner → intermediate → advanced
- Each level has associated trainings
- Used for learner progression tracking

### Trainings
- Title, description, level
- Link to media assets (documents, videos)
- Associated quizzes
- Completion tracking

### Quizzes
- Questions (MCQ, short answer, etc.)
- Answer choices with correct answer marking
- Score calculation
- Timed or untimed

### User Progress
- Training completion status
- Quiz scores and timestamps
- Learning path recommendations
- NIETE sync: learner data pulled from NIETE API

### AI Feedback
- Celery task: generate personalized feedback on quiz submission
- Uses Claude API or similar LLM
- Feedback stored with quiz result
- User-facing: displayed in CMS dashboard

## API Endpoints

### Trainings
```
GET    /api/v1/trainings/                    # List all
POST   /api/v1/trainings/                    # Create new
GET    /api/v1/trainings/{id}/               # Retrieve one
PUT    /api/v1/trainings/{id}/               # Update
DELETE /api/v1/trainings/{id}/               # Delete
```

### Quizzes
```
GET    /api/v1/quizzes/                      # List
POST   /api/v1/quizzes/                      # Create
POST   /api/v1/quizzes/{id}/submit/          # Submit answers
```

### Quiz Results
```
GET    /api/v1/quiz_results/                 # User's results
GET    /api/v1/quiz_results/{id}/            # Specific result with feedback
```

### User Progress
```
GET    /api/v1/user_progress/                # User's completion status
```

### NIETE Sync
```
POST   /api/v1/internal/niete_sync/          # Pull user list, sync completions
GET    /api/v1/internal/niete_status/        # Last sync timestamp and count
```

### Media Assets
```
POST   /api/v1/internal/media_assets/presigned_upload_url/  # Get S3 URL
GET    /api/v1/media_assets/                 # List with metadata
```

## Database Schema

### Training
```
- id (PK)
- title, description
- level_id (FK)
- created_at, updated_at
```

### Quiz
```
- id (PK)
- training_id (FK)
- title, description
- is_published
```

### QuizQuestion
```
- id (PK)
- quiz_id (FK)
- question_text
- question_type (MCQ, short_answer, etc.)
```

### QuizAnswer (options for MCQ)
```
- id (PK)
- question_id (FK)
- answer_text
- is_correct
```

### QuizResult (submission)
```
- id (PK)
- user_id (FK)
- quiz_id (FK)
- score
- submitted_at
- feedback (text from Celery task)
```

### UserProgress
```
- id (PK)
- user_id (FK)
- training_id (FK)
- status (in_progress, completed)
- completion_date
```

## Async Tasks (Celery)

### Generate AI Feedback
```python
@celery.task
def generate_quiz_feedback(quiz_result_id):
    # Fetch result, quiz, answers
    # Call Claude API with prompt
    # Store feedback in result.feedback
    # Update user notification
```

**Trigger**: On quiz submission
**Retry**: 3 times with exponential backoff
**Queue**: default (no priority)

### NIETE Sync
```python
@celery.task
def sync_niete_learners():
    # Fetch user list from NIETE API
    # Create/update local users
    # Sync completion statuses back
    # Log sync metrics
```

**Trigger**: Daily scheduled task (9 AM)
**Retry**: 3 times
**Queue**: sync (separate queue for heavy tasks)

## Testing

### Unit Tests
- Model methods (calculation logic)
- API serialization/deserialization
- Permission checks

### Integration Tests
- End-to-end training → quiz → feedback flow
- Celery task execution with real Redis
- NIETE sync with staging API
- S3 presigned URL generation

### No Mocking Rule
- Database: Use test DB, not mocks
- Celery: Use test broker (RabbitMQ/Redis test instance)
- External APIs: Use staging endpoints where possible, not mocks

## Related Projects
- [[vault/memory/taleemabad_cms_project]] — Frontend consumer; training manager UI
- [[vault/memory/taleemabad_core_path]] — Backend implementation location
