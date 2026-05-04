---
name: Taleemabad CMS Project
description: React SPA for content management and S3 uploads
type: project
---

# taleemabad-cms — Content Management System

## Location & Tech
- **Path**: `repos/taleemabad-cms/`
- **Tech**: React 19, Vite, TypeScript, TailwindCSS
- **Package Manager**: npm
- **Styling**: TailwindCSS utilities
- **Environment**: `.env` points to local/staging backend via `VITE_API_BASE_URL`

## Key Features

### S3 Upload Flow (Presigned URLs)
- **Backend Endpoint**: `POST /api/v1/internal/media_assets/presigned_upload_url/`
- **Frontend Hook**: `useS3Upload` — handles file selection, upload to S3, progress tracking
- **AssetForm Component**: File picker + upload button + auto-populate S3 URL
- **Flow**: Browser → S3 presigned URL (direct upload, no backend file handling)

### Media Asset Management
- **AssetLibrary**: Searchable dropdown for linking existing assets
- **TrainingForm**: Asset picker for training content
- **Metadata**: Title, description, file type, S3 URL stored in database

### Training Management
- **TrainingCRUD**: Create, edit, delete trainings
- **AssetLinking**: Associate media with training content
- **QuizBuilder**: Inline quiz creation with answer options
- **Publishing**: Draft → published workflow

### Admin Dashboard
- **Overview**: Training list, asset count, user stats
- **Quick Actions**: Create training, upload asset, manage users
- **Status Cards**: Active trainings, pending quizzes, recent uploads

## Code Structure

```
src/
├── components/
│   ├── AssetForm.tsx          # File picker + S3 upload UI
│   ├── AssetLibrary.tsx       # Searchable asset dropdown
│   ├── TrainingForm.tsx       # Training CRUD form
│   ├── QuizBuilder.tsx        # Inline quiz editor
│   ├── Dashboard.tsx          # Admin overview
│   └── ...
├── hooks/
│   ├── useS3Upload.ts         # S3 presigned URL upload logic
│   └── ...
├── types/
│   └── index.ts               # TypeScript interfaces for API contracts
└── services/
    └── api.ts                 # API client wrapper
```

## Testing Standards

- **Type-Check**: `npm run type-check` before commit (TypeScript strict mode)
- **Linting**: `npm run lint` (ESLint + Prettier)
- **Build**: `npm run build` validates production bundle
- **No components without types**: All React props must be fully typed

## S3 Configuration

- **Bucket**: Separate CMS bucket (not shared with core)
- **CORS**: Configured for localhost dev + staging/prod domains
- **Credentials**: `VITE_API_BASE_URL` auth handled by backend presigned URL endpoint
- **Credential Set**: Backend has separate AWS S3 CMS credentials (not core credentials)

## Development Workflow

1. **Start dev server**: `npm run dev`
2. **Verify environment**: Check `VITE_API_BASE_URL` points to correct backend
3. **Type-check**: `npm run type-check` in terminal
4. **Build before commit**: `npm run build` validates bundle
5. **Feature checklist**: Component types → user flow → S3 integration → dashboard display

## Related Projects

- [[vault/memory/taleemabad_core_path]] — Backend API consumer; shared S3 presigned URL endpoint
- [[vault/memory/taleemabad_training_project]] — Training system this UI manages
