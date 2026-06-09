---
name: portfolio-data Relationships
description: Links to portfolio-website and auto-publishing workflow
---

# Related Projects

## Website Consumer
- **[[projects/portfolio-website]]** — Consumes this data at build time
  - Fetches `portfolio.json` for projects, experience, skills
  - Fetches `blogs.json` for blog posts
  - Generates static HTML during build
  - No runtime dependencies (data is static)

## Auto-Publishing Workflow

### When Claude Publishes a Blog Post

1. **Session achievement**: Kamal solves something notable, ships a feature, learns a lesson
2. **Claude creates entry** in `blogs.json` with metadata
3. **Commit and push** to portfolio-data: `git commit -m "blog: <slug>" && git push`
4. **Website rebuilds** (manually triggered or auto on CI):
   - Pulls latest `blogs.json`
   - Generates HTML for new post
   - Updates blog index/archive
5. **Post live** within minutes on portfolio-website

### When Claude Updates Portfolio

1. **Kamal mentions** new project, skill, experience
2. **Claude updates** `portfolio.json` with new entry
3. **Commit and push**: `git commit -m "update: <type>" && git push`
4. **Website rebuilds**:
   - Pulls latest `portfolio.json`
   - Regenerates projects/experience sections
   - Rebuilds SEO metadata
5. **Changes live** on portfolio-website

## Sync Checklist (Auto-Publishing)

Claude should auto-publish when:
- [ ] Bug fixed or solved (write blog post?)
- [ ] Feature shipped (add to projects?)
- [ ] New pattern discovered (blog post?)
- [ ] Architectural decision made (blog + update portfolio?)
- [ ] Milestone reached (add to experience?)
- [ ] New skill mastered (add to skills?)

Each requires:
1. Valid JSON (no syntax errors)
2. Unique blog slug (if new post)
3. Author = "{{USER_NAME}}"
4. Date = today's date (YYYY-MM-DD)
5. All required fields filled

See [[vault/memory/portfolio_ownership]] for full details on when and how to publish.
