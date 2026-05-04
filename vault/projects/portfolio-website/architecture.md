---
name: portfolio-website Architecture
description: Site structure, components, design system
---

# Architecture — portfolio-website

## Tech Stack
- **Build**: Vite / Webpack (TBD)
- **Framework**: Vue / React / Next.js (TBD)
- **Styling**: TailwindCSS + custom Amber palette
- **Deployment**: GitHub Pages / Vercel / CloudFront
- **Data**: JSON from [[projects/portfolio-data]]

## Design System — Amber Editorial

### Color Palette
- **Primary**: #A3B59A (warm sage green)
- **Accent**: #D4A574 (amber/tan)
- **Dark**: #2C2C2C (dark charcoal)
- **Light**: #F8F5F0 (off-white/cream)

### Typography
- **Headlines**: Serif font (elegant, editorial)
- **Body**: Sans-serif (readable, modern)
- **Mono**: Monospace (code blocks)

### Components
- **Cards**: Project/experience cards with hover effects
- **Buttons**: Styled CTAs with hover states
- **Typography**: Heading styles (h1-h4), body copy
- **Grid**: Responsive layouts (mobile-first)

## Site Structure

```
/
├── /index.html            # Home page
├── /projects.html         # Projects page (grid)
├── /blog/                 # Blog posts
│   ├── /[slug]/
│   └── /archive.html
├── /about.html            # About (experience + skills)
├── /contact.html          # Contact page
└── /assets/               # Images, icons
```

## Data Fetching

### Static Generation
- Build-time: Fetch `portfolio.json` and `blogs.json` from portfolio-data
- Generate static HTML for each project, blog post
- No runtime data fetching (fast, no dependencies on API)

### Blog Post Rendering
- Markdown → HTML conversion at build time
- Code syntax highlighting (Prism.js or similar)
- Metadata: title, date, author, tags, image

## Performance Optimizations

- **Image optimization**: Lazy loading, responsive images
- **Code splitting**: Per-route bundles
- **Minification**: CSS, JS, HTML compressed in build
- **Caching**: Browser cache headers configured
- **CDN**: CloudFront caching for static assets

## Build Process

```bash
npm run build:data    # Fetch portfolio-data
npm run build:site    # Build static site
npm run serve         # Local preview
npm run deploy        # Push to production
```

## Deployment

- **GitHub Pages**: Automatic on push to main
- **Vercel**: Automatic on git push (alternative)
- **CloudFront**: CDN caching for fast delivery globally

## Related Data

See [[projects/portfolio-data]] for:
- `portfolio.json` — Projects, experience, skills
- `blogs.json` — Blog posts with metadata
