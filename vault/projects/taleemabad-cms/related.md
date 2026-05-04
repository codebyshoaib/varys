---
name: taleemabad-cms Relationships
description: Links to related projects and shared systems
---

# Related Projects

## Backend API
- **[[projects/taleemabad-core]]** — RESTful API this SPA consumes
  - Training endpoints for CRUD
  - Presigned URL endpoint for asset uploads
  - Quiz submission and result endpoints
  - Progress tracking endpoints

## Authentication
- **[[projects/taleemabad-auth]]** — JWT auth middleware
  - Tokens obtained from auth service
  - Sent in Authorization header to core API
  - User roles determine admin/editor/viewer access

## Shared Infrastructure

### S3 Media Storage
- **Flow**: CMS user selects file → requests presigned URL from core → uploads directly to S3
- **Bucket**: Separate CMS bucket (different from core's data storage)
- **Credentials**: Backend has AWS credentials; frontend never touches S3 secrets
- **CORS**: Configured for localhost dev + staging/prod domains

### API Communication
- **Base URL**: `VITE_API_BASE_URL` environment variable points to core API
- **Dev**: `http://localhost:8000`
- **Staging**: `https://staging-api.taleemabad.com`
- **Production**: `https://api.taleemabad.com`

## Cross-Project Workflows

### Training Creation with Assets
1. **CMS**: Admin clicks "Create Training"
2. **CMS**: Form shows AssetForm component
3. **CMS**: User selects file, clicks "Upload"
4. **CMS/Hook**: Calls `POST /api/v1/internal/media_assets/presigned_upload_url/` from core
5. **Core**: Returns temporary S3 URL
6. **CMS/useS3Upload**: Browser uploads directly to S3 with presigned URL
7. **CMS**: On success, stores S3 URL in form
8. **CMS**: User completes training form, submits
9. **Core**: Receives training with S3 asset URL, stores in database

### Quiz Submission Flow
1. **CMS**: Learner loads TrainingDetail page
2. **CMS**: Fetches quiz from core
3. **CMS**: QuizBuilder renders questions
4. **CMS**: Learner submits answers
5. **CMS**: Calls `POST /api/v1/quiz_results/` on core
6. **Core**: Calculates score, queues feedback task
7. **Core**: Returns immediate response with score
8. **CMS**: Shows score to learner
9. **Celery (async)**: Generates AI feedback
10. **CMS**: Polls for feedback, displays when ready

### Learner Progress Display
1. **CMS**: Dashboard queries `/api/v1/user_progress/`
2. **Core**: Returns completion stats for current user
3. **CMS**: Dashboard renders progress cards with completion percentages
4. **Core/Daily**: NIETE sync updates completion data
5. **CMS**: User sees updated progress on refresh
