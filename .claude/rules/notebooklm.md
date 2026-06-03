---
type: rule
owner: kamil
last_verified: 2026-06-03
---

# NotebookLM — Kamil's Research Intelligence Layer

Every notebook Kamil creates is registered in **Notion NLM Registry** (`1de6a08dc4784ab69a672ffcf890758a`).
This registry is the single source of truth. **Always check it before answering any research question.**

## The Rule

> Before answering any question about a topic Kamil has researched, check the NLM Registry.
> If a matching notebook exists — query it. Answer with cited evidence, not from training memory.

This applies in ALL contexts:
- Slack question arrives → search registry → query notebook → answer with citations
- Someone wants to implement something → find relevant notebook → pull implementation guidance
- Working on a taleemabad feature → check if there's engineering research on the pattern
- Kamal asks "how do I..." → registry first, training data second

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

Full registry with tags + summaries: https://app.notion.com/p/1de6a08dc4784ab69a672ffcf890758a

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
