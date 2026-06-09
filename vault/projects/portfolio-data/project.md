---
name: portfolio-data
description: JSON data and blog posts for portfolio website
---

# portfolio-data — Portfolio Data Source

## Overview
- **GitHub**: Public (personal)
- **Local Path**: `repos/portfolio-data/`
- **Tech Stack**: JSON + Markdown
- **Purpose**: Source of truth for projects, experience, skills, blog posts
- **Status**: Active maintenance
- **Consumer**: [[projects/portfolio-website]] (consumed at build time)

## Files

### portfolio.json
```json
{
  "name": "{{USER_NAME}}",
  "title": "Senior Backend Engineer",
  "bio": "...",
  "projects": [...],
  "experience": [...],
  "skills": [...],
  "social": {...}
}
```

**Projects**: id, title, description, tech, github, demo, featured
**Experience**: company, role, startDate, endDate, description, achievements
**Skills**: category, skills (proficient, expert, learning)

### blogs.json
```json
[
  {
    "id": "1",
    "slug": "debugging-celery-tasks",
    "title": "Debugging Celery Task Queues in Django",
    "publishDate": "2026-05-04",
    "author": "{{USER_NAME}}",
    "category": "Backend",
    "tags": ["Django", "Celery", "Debugging"],
    "excerpt": "...",
    "content": {...}
  }
]
```

## When Claude Auto-Updates

### Update portfolio.json
When Kamal mentions:
- A new project shipped or milestone reached
- A new skill mastered or role taken on
- A new certification or qualification

### Create Blog Post
When Kamal:
- Solves a notable problem
- Implements a new pattern or technique
- Learns a lesson worth sharing
- Reaches a project milestone

### Blog Post Metadata
- `id`: Unique identifier (increment previous max)
- `slug`: URL-friendly title (kebab-case)
- `title`: Display title
- `publishDate`: `YYYY-MM-DD` format
- `author`: Always "{{USER_NAME}}"
- `category`: Backend, Frontend, DevOps, Career, etc.
- `tags`: Searchable keywords
- `excerpt`: One-sentence summary
- `content`: Full article

## Push Credentials
- **Method**: SSH push
- **Remote**: GitHub portfolio-data repo
- **Process**: Commit locally → `git push origin main`

## Related Files
- [[architecture]] — JSON schema, structure, validation
- [[related]] — Links to portfolio-website (consumer)
