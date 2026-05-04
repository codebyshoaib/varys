---
name: taleemabad-cms
description: React SPA for training content management
---

# taleemabad-cms — Content Management System

## Overview
- **GitHub**: Taleemabad organization (private)
- **Local Path**: `repos/taleemabad-cms/`
- **Tech Stack**: React 19, Vite, TypeScript, TailwindCSS
- **Purpose**: SPA for managing trainings, uploading assets, building quizzes
- **Status**: Active development
- **Primary API**: [[taleemabad-core]] (Django backend)

## Key Features

### S3 Upload Flow
- **Backend Endpoint**: `POST /api/v1/internal/media_assets/presigned_upload_url/`
- **Frontend Hook**: `useS3Upload` — file selection, upload to S3, progress tracking
- **Component**: AssetForm — file picker + upload button + auto-populate S3 URL
- **Flow**: Browser → S3 presigned URL (direct upload, no backend file handling)

### Media Asset Management
- **AssetLibrary**: Searchable dropdown for linking existing assets
- **TrainingForm**: Asset picker for training content
- **Metadata**: Title, description, file type, S3 URL

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
├── components/           # React components
│   ├── AssetForm.tsx
│   ├── AssetLibrary.tsx
│   ├── TrainingForm.tsx
│   ├── QuizBuilder.tsx
│   └── Dashboard.tsx
├── hooks/               # Custom React hooks
│   ├── useS3Upload.ts   # S3 upload logic
│   └── ...
├── types/               # TypeScript interfaces
│   └── index.ts
└── services/            # API client wrappers
    └── api.ts
```

## Development Workflow

1. **Start dev server**: `npm run dev`
2. **Check environment**: Verify `VITE_API_BASE_URL` points to correct backend
3. **Type-check**: `npm run type-check` (strict mode required)
4. **Build validation**: `npm run build` before commit
5. **Feature checklist**: Component types → user flow → S3 integration → dashboard

## Testing Standards

- **Type-Check**: `npm run type-check` before commit (TypeScript strict mode)
- **Linting**: `npm run lint` (ESLint + Prettier)
- **Build**: `npm run build` validates production bundle
- **No `any` types** without justification

See [[vault/memory/taleemabad_cms_project]] for detailed reference.

## Related Files
- [[architecture]] — Components, patterns, state management
- [[decisions]] — UI decisions, component design trade-offs
- [[related]] — Links to taleemabad-core (API consumer)
