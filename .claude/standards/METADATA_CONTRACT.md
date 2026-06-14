---
type: reference
last_verified: 2026-06-01
owner: varys
---

# Metadata Contract

Every markdown file (except CLAUDE.md) starts with:

    ---
    type: router|runbook|reference|investigation|plan|changelog
    last_verified: YYYY-MM-DD
    owner: varys
    ---

## Freshness SLOs
| Doc | Max staleness |
|-----|---------------|
| CLAUDE.md | 2 weeks |
| Routers / rules | 1 month |
| Reference docs | 2 months |
| Changelogs | none |

When `last_verified` exceeds the SLO → open a bead.
