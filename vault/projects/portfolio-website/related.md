---
name: portfolio-website Relationships
description: Links to portfolio-data and deployment
---

# Related Projects

## Data Source
- **[[projects/portfolio-data]]** — JSON data and blog posts consumed by this site
  - `portfolio.json` — Projects, experience, skills
  - `blogs.json` — Blog posts with metadata
  - Both fetched at build time for static generation

## Build & Deployment Flow

```
1. Git push to portfolio-website
2. GitHub Actions triggered
3. Run `npm run build:data` → fetch latest from portfolio-data
4. Run `npm run build:site` → generate static HTML
5. Deploy to GitHub Pages / Vercel / CloudFront
6. Site live within minutes
```

## Auto-Publishing to Blog

When you accomplish something notable (new project, bug fix, lesson learned):
1. **Create blog post** in [[projects/portfolio-data]]
2. **Update `blogs.json`** with metadata
3. **Push to portfolio-data**
4. **Manually trigger website build** (or next auto-deploy)
5. **New post live** on portfolio website

See [[vault/memory/portfolio_ownership]] for the full publishing workflow.

## Content Updates

### Update Projects
1. Edit `portfolio-data/portfolio.json`
2. Add/modify project entry with GitHub URL, tech stack, description
3. Push to portfolio-data
4. Website rebuilds (auto or manual trigger)

### Update Experience
1. Edit `portfolio-data/portfolio.json` → experience section
2. Add new role or update existing role
3. Push to portfolio-data
4. Website rebuilds

### Update Skills
1. Edit `portfolio-data/portfolio.json` → skills section
2. Categorize by domain (Backend, Frontend, etc.)
3. Push and rebuild
