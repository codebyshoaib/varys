---
type: rule
owner: kamil
last_verified: 2026-06-03
---

# NotebookLM — {{AGENT_NAME}}'s Research Intelligence Layer

Every notebook {{AGENT_NAME}} creates is registered in **Notion NLM Registry** (`{{config:NOTION_NLM_REGISTRY_DB_ID}}`).
This registry is the single source of truth. **Always check it before answering any research question.**

## When to Use NotebookLM

NotebookLM is a **content and research tool**. Use it for:
- Content creation (scripts, posts, carousels, podcasts, mindmaps)
- Internet research on a topic (fitness, niches, trends, freelance)
- Pre-researched deep-dives for content generation

**Do NOT use NotebookLM for:**
- Engineering Q&A — read the actual source code/repo/docs directly
- Pattern lookups from code repos — clone and read the repo
- Answering Slack engineering questions — use WebFetch, Grep, or gh CLI
- Storing architectural knowledge — living code is always more accurate

## The Rule

> For engineering questions: read the source directly (repo, code, docs).
> For content/research questions: check the NLM Registry first.

Engineering question arrives on Slack → use tools (WebFetch, gh CLI, Read) to find the answer from the actual source. Never create a NotebookLM notebook as a proxy for a live codebase.

Content/research question arrives → check NLM Registry → query matching notebook → answer with citations.

## How to Search

```bash
# Via Slack trigger (kamil-slack-listener routes automatically)
nlm ask harness-research "what is the evaluator rationalization problem?"

# Manual query by alias
nlm notebook query e0c78776-a95c-4d4e-b920-b54af3b8099f "your question" --profile default

# Or by alias shortname
nlm ask django-tenancy "how to scope queries by tenant in Django?"
```

## Registry

| Alias | Domain | When to use |
|---|---|---|
| `harness-research` | research | Harness gaps, evaluator rationalization, hook exit codes, context rot, advisory vs enforcement, quality gates, memory systems |
| `django-tenancy` | engineering | Django multi-tenancy, tenant isolation, query filtering, taleemabad architecture |
| `api-latency` | engineering | API performance, latency reduction, query optimisation, N+1, caching |
| `supabase-vs-pocketbase` | engineering | BaaS comparison, Supabase, PocketBase, self-hosting |
| `claude-prompts` | engineering | Claude prompting, Claude Code tips, developer productivity |
| `instagram` | content | Instagram niches, content strategy, growth, monetisation |
| `reddit-jobs` | freelance | Freelance job sources, Reddit boards, remote work, House Fund leads |
| `pullups` | fitness | Pull-up progression, calisthenics, upper body strength |
| `swimming` | fitness | Swimming for beginners, freestyle technique, pool workouts |
| `cycling-zones` | fitness | Cycling training zones, FTP, structured training |
| `calisthenics-vs-gym` | fitness | Bodyweight vs weights, home vs gym |

Full registry with tags + summaries: https://app.notion.com/p/{{config:NOTION_NLM_REGISTRY_DB_ID}}

## Auto-Registration

Every `nlm research [topic]` or `nlm create [topic]` automatically:
1. Creates the notebook in NotebookLM
2. Registers it in Notion NLM Registry with alias, domain, tags, when_to_use
3. Updates `ALIASES` fallback in `notebooklm_handler.py` on next sync

New notebooks are immediately queryable by alias or keyword.

## When Someone Asks a Question on Slack

```
Question arrives
    ↓
Does registry have a matching notebook? (search by keyword)
    ├─ YES → nlm notebook query <id> "<question>" --profile default
    │        → post answer with "Source: [notebook title]" 
    │        → update Last Queried in registry
    └─ NO  → answer from training data
             → if topic is important, suggest: "nlm research <topic>" to build a notebook
```

## When Someone Wants to Implement Something

```
"How do I implement X in my project?"
    ↓
Check registry for relevant notebook
    ↓
Query: "what are the implementation steps for X?"
    ↓
Return: cited, structured answer from research sources
    ↓
Add: "Full research in NotebookLM: nlm ask <alias> [your question]"
```
