---
name: Portfolio Ownership
description: Responsibility for portfolio website and blog data
type: project
---

# Portfolio Ownership — Website & Data

## Repositories

### portfolio-website
- **Path**: `repos/portfolio-website/`
- **Tech**: Static site (HTML/CSS/JS or framework)
- **Purpose**: Public showcase of projects, skills, experience
- **Design System**: Amber editorial design (custom color palette)
- **Deployment**: Custom build + push (verify build succeeds before commit)

### portfolio-data
- **Path**: `repos/portfolio-data/`
- **Tech**: JSON data + markdown blog posts
- **Contents**: 
  - `portfolio.json` — Projects, experience, skills, certifications
  - `blogs.json` — Blog posts with metadata
- **Deployment**: Commit + push; website consumes this data

## Auto-Publishing Rules

### When to Publish a Blog Post
Claude should write a blog post automatically (without being asked) when:
1. Something meaningful was built, shipped, or solved in a session
2. A new technique, pattern, or architectural decision was made
3. A notable problem was debugged and solved
4. A project milestone was reached
5. An interesting opinion or lesson emerged from the work

### How to Publish
1. Write post in `repos/portfolio-data/blogs.json` — add to top of array with new `id`
2. Use existing schema: `id`, `slug`, `title`, `description`, `content.sections[]`, `excerpt`, `author`, `publishDate`, `tags`, `category`, `image`, `featured`, `seo`
3. Set `author` to `"Muhammad Kamal"` always
4. Commit and push from `repos/portfolio-data/`

### When to Update portfolio.json
Claude should update `repos/portfolio-data/portfolio.json` automatically when:
1. A new project is completed or reaches a significant milestone
2. A new role, skill, or certification is mentioned
3. Something belongs in experience, skills, or projects sections

## Push Credentials
- **Method**: SSH push (user has SSH key configured)
- **Remote**: GitHub (portfolio-data and portfolio-website repos)
- **Process**: Commit locally → `git push origin main`

## Design System
- **Name**: Amber Editorial
- **Colors**: Warm amber/brown palette for editorial feel
- **Fonts**: Professional, readable serif + sans-serif mix
- **Components**: Cards, typography, color utilities

## Related Notes
- Auto-publish to portfolio is logged in [[vault/domains/content/log]]
- Track all blog posts in [[vault/domains/content/pipeline]]
