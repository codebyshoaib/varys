---
name: taleemabad-cms Architecture
description: Component structure, patterns, state management
---

# Architecture — taleemabad-cms

## Tech Stack
- **Framework**: React 19
- **Build**: Vite
- **Language**: TypeScript (strict mode)
- **Styling**: TailwindCSS
- **Package Manager**: npm
- **API Client**: Fetch API with custom wrapper

## Component Structure

### Pages
- **Dashboard** — Overview, stats, quick actions
- **TrainingList** — Paginated training list, bulk actions
- **TrainingDetail** — Single training view, edit form
- **AssetLibrary** — Searchable asset gallery
- **QuizBuilder** — Quiz editor with answer options
- **Settings** — Admin configuration

### Reusable Components
- **AssetForm** — File picker + S3 upload UI
- **AssetLibrary** — Dropdown for asset selection
- **TrainingForm** — Full training CRUD form (create, edit)
- **QuizBuilder** — Quiz question editor
- **Card** — Generic card component for layouts
- **Button** — Styled button with loading states
- **Modal** — Dialog for confirmations, alerts

### Custom Hooks
- **`useS3Upload`** — File selection, S3 presigned URL, upload progress
  - Returns: `{file, isUploading, progress, s3Url, error, upload()}`
  - Handles: Retry logic, progress events, error states

- **`useApi`** — Wrapper around fetch with loading/error states
  - Returns: `{data, loading, error, refetch}`
  - Handles: Request cancellation, timeout, JSON parsing

- **`useForm`** — Form state management (values, errors, touched)
  - Returns: `{values, errors, touched, handleChange, handleBlur, setValues}`
  - Handles: Validation, reset, submission

## Design Patterns

### Unidirectional Data Flow
- Props down: Parent → Child (one-way binding)
- Events up: Child → Parent (callbacks)
- State management: useState for component state, props for data

### Controlled Components
- Input values come from state
- onChange handlers update state
- Example: `<input value={values.title} onChange={handleChange} />`

### Composition over Inheritance
- Hooks over class components
- Small, focused components that compose together
- Example: AssetForm uses useS3Upload hook internally

### Async/Await Pattern
- API calls use async/await (not promises)
- Error boundaries for fetch errors
- Loading states shown during requests

## State Management

### Local Component State
- `useState` for form fields, UI toggles, simple data
- Sufficient for page-level state

### API Caching
- `useApi` hook caches responses
- Refetch function for manual refresh
- Could be extended to TanStack Query for advanced caching

### URL State
- Query parameters for filters, pagination
- Preserves state when user navigates away

## Type System

### API Response Types
```typescript
interface Training {
  id: string;
  title: string;
  description: string;
  assets: MediaAsset[];
  quizzes: Quiz[];
  published: boolean;
}

interface MediaAsset {
  id: string;
  title: string;
  s3Url: string;
  mimeType: string;
  size: number;
}

interface Quiz {
  id: string;
  title: string;
  questions: QuizQuestion[];
}
```

### Component Props
- Every component must have typed props
- No implicit `any` types
- Optional props use `?` operator

## Environment Configuration

```
.env:
VITE_API_BASE_URL=http://localhost:8000  # Dev
VITE_S3_REGION=us-east-1

.env.staging:
VITE_API_BASE_URL=https://staging-api.your-project.com

.env.production:
VITE_API_BASE_URL=https://api.your-project.com
```

## Build & Deployment

- **Dev**: `npm run dev` → Vite dev server (hot reload)
- **Build**: `npm run build` → Optimized bundle in `dist/`
- **Type-check**: `npm run type-check` → TypeScript validation
- **Lint**: `npm run lint` → ESLint + Prettier
- **Deploy**: GitHub Actions → Build → Deploy to S3 + CloudFront
