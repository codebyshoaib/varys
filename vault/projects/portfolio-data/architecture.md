---
name: portfolio-data Architecture
description: JSON schema and data structure
---

# Architecture — portfolio-data

## portfolio.json Schema

```json
{
  "name": "string",
  "title": "string",
  "bio": "string",
  "image": "url",
  "email": "string",
  "location": "string",
  "social": {
    "github": "url",
    "linkedin": "url",
    "twitter": "url (optional)"
  },
  "projects": [
    {
      "id": "string",
      "title": "string",
      "description": "string",
      "image": "url (optional)",
      "tech": ["string"],
      "github": "url",
      "demo": "url (optional)",
      "featured": "boolean",
      "year": "number"
    }
  ],
  "experience": [
    {
      "id": "string",
      "company": "string",
      "role": "string",
      "startDate": "YYYY-MM",
      "endDate": "YYYY-MM (null if current)",
      "description": "string",
      "achievements": ["string"]
    }
  ],
  "skills": [
    {
      "category": "string",
      "items": [
        {
          "name": "string",
          "level": "expert | proficient | learning"
        }
      ]
    }
  ]
}
```

## blogs.json Schema

```json
[
  {
    "id": "number",
    "slug": "string (kebab-case)",
    "title": "string",
    "description": "string (short summary)",
    "author": "{{USER_NAME}} (always)",
    "publishDate": "YYYY-MM-DD",
    "updatedDate": "YYYY-MM-DD (optional)",
    "category": "string (Backend | Frontend | DevOps | Career | etc.)",
    "tags": ["string"],
    "image": "url (featured image, optional)",
    "featured": "boolean (show on homepage)",
    "excerpt": "string (one-liner for preview)",
    "content": {
      "sections": [
        {
          "heading": "string",
          "body": "markdown or html",
          "code": "code block (optional)"
        }
      ]
    },
    "seo": {
      "metaDescription": "string",
      "keywords": ["string"]
    }
  }
]
```

## Naming Conventions

### Blog Slug
- Kebab-case: `debugging-celery-tasks`
- Reflects title for SEO
- No underscores or spaces
- Max 50 characters

### Project ID
- Kebab-case: `taleemabad-cms`
- Unique across all projects
- Matches GitHub repo name when applicable

### Category (Blog)
- Backend, Frontend, DevOps, Career, Architecture, Database, Testing, etc.
- Used for filtering and navigation

### Tags (Blog)
- Technology/skill names: Django, React, PostgreSQL, Celery, etc.
- Problem domain: Debugging, Performance, Security, API Design, etc.
- Keep list consistent (don't create variant spellings)

## Data Validation

### Before Publishing
1. Valid JSON (no syntax errors)
2. All required fields populated
3. URLs are valid (http/https)
4. Blog slug is unique
5. Date formats are YYYY-MM-DD
6. Category is from approved list
7. Author is "{{USER_NAME}}"

### Example: Valid Blog Entry
```json
{
  "id": 42,
  "slug": "fixing-n-plus-one-queries",
  "title": "Fixing N+1 Query Problems in Django",
  "description": "How to identify and fix N+1 queries for better database performance",
  "author": "{{USER_NAME}}",
  "publishDate": "2026-05-04",
  "category": "Backend",
  "tags": ["Django", "Performance", "PostgreSQL"],
  "excerpt": "N+1 query problems can cripple performance. Here's how to spot and fix them.",
  "content": {
    "sections": [...]
  }
}
```

## Deployment

- **Git push**: `git push origin main`
- **Consumer**: portfolio-website fetches on build (no realtime sync)
- **Blog live**: Within minutes of pushing (on next website rebuild)
- **CDN cache**: Bust if immediate update needed (set cache headers)
