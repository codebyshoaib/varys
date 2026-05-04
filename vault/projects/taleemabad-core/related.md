---
name: taleemabad-core Relationships
description: Links to related projects and shared systems
---

# Related Projects

## Frontend Consumer
- **[[projects/taleemabad-cms]]** — React SPA that consumes this API
  - Calls training endpoints for CRUD
  - Uses presigned URL endpoint for asset uploads
  - Displays quiz results and feedback from this backend

## Authentication
- **[[projects/taleemabad-auth]]** — JWT auth middleware
  - Issues tokens; core validates them on protected endpoints
  - Shared middleware for permission checking
  - User role definitions shared between systems

## Shared Infrastructure

### Database
- Single PostgreSQL instance
- Core uses separate schema (ideally)
- Migrations coordinated between projects

### S3 Media Storage
- Core: Presigned URL generation for CMS uploads
- CMS: Browser uploads directly to S3
- Both projects: Reference same media assets by S3 URL

### Celery Task Queue
- Core: Background jobs (feedback, NIETE sync)
- Queue: Redis broker shared
- Monitoring: Can view job status via Flower dashboard

### NIETE Integration
- Core: Pulls learner list via NIETE API
- Core: Syncs training completion status back to NIETE
- CMS: Displays NIETE learner info in admin dashboard

## Cross-Project Workflows

### Training Creation → Publishing
1. **CMS**: Create training, upload assets via presigned URL
2. **Core**: Assets linked to training via S3 URL
3. **Core**: Training published → learners can enroll
4. **NIETE**: Sync pulls updated training list

### Quiz Submission → Feedback
1. **CMS**: Learner submits quiz answers
2. **Core**: Validate answers, calculate score
3. **Core**: Queue feedback generation task
4. **Celery**: Generate AI feedback asynchronously
5. **CMS**: Poll for feedback, display when ready

### Learner Progress Sync
1. **NIETE**: Upstream system tracking learner enrollment
2. **Core**: Daily sync pulls NIETE learner list
3. **Core**: Match NIETE users to local users
4. **Core**: Track progress in local database
5. **CMS**: Dashboard queries local progress
