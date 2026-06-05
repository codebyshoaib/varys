# Brain Connectivity — How Kamil Wires Knowledge

> The rules for connecting new information across Kamil's brain.
> Read this before any task that adds new knowledge to the system.
> Brain DB: ~/.kamil-harness/brain.db

## Core Rules
- Every new fact must link to at least one existing entity. No orphans.
- Use the four-operation protocol: ADD / UPDATE / DELETE / NOOP. Never raw append.
- Tag every fact with: who said it, when, and confidence level.
- If a fact contradicts an existing one: UPDATE (invalidate old, add new). Never delete.
- When in doubt about a connection: add it with confidence 0.6 and let it mature.
- Before saying "I don't remember" — query brain.db first.

## Entity Types and When to Create Them

| Type | When to create | Example ID |
|---|---|---|
| person | Any team member, contact, or person mentioned | person-mashood |
| skill | Any skill file in .claude/skills/kamil/ | skill-avatar |
| agent | Any agent in .claude/agents/ | agent-research-agent |
| project | Any active project | project-taleemabad-core |
| book | Any book, article, or resource mentioned | book-atomic-habits |
| tool | Any tool, framework, or technology | tool-django |
| concept | Any abstract idea worth remembering | concept-systems-thinking |
| fact | Standalone fact with no better type | fact-kamal-timezone |

## Connection Patterns (what links to what)

### When someone recommends a book
```
person-X → recommended → book-Y
person-X → mentioned_with → concept-Z (the topic the book covers)
book-Y → covers → concept-Z
```

### When a new skill/agent is added
```
skill-X → is_part_of → kamil_harness
skill-X → handles → concept-Y (what the skill does)
skill-X → reads → skill-Z (skill files it depends on)
```

### When Kamal expresses a preference
```
person-kamal → prefers → X
person-kamal → mentioned_with → context-Y (when/why)
```

### When a decision is made
```
person-kamal → decided → fact-X
fact-X → about → project-Y (if project-related)
fact-X → on_date → YYYY-MM-DD
```

### When a team member says something important
```
person-X → said → fact-Y
fact-Y → in_context → project-Z or concept-Z
```

## Retrieval Patterns (SQL queries to use)

### "What did Mashood recommend?"
```sql
SELECT f.object_val FROM facts f
WHERE f.subject_id = 'person-mashood'
AND f.predicate = 'recommended'
AND f.valid_until IS NULL
```

### "What books were mentioned this month?"
```sql
SELECT e.name, f.valid_from FROM entities e
JOIN facts f ON f.object_id = e.id OR f.subject_id = e.id
WHERE e.type = 'book'
AND f.valid_from >= '2026-06-01'
```

### "What skills does Kamil have?"
```sql
SELECT e.name FROM entities e
WHERE e.type IN ('skill', 'agent')
AND e.id IN (
  SELECT subject_id FROM facts
  WHERE predicate = 'is_part_of'
  AND object_val = 'kamil_harness'
  AND valid_until IS NULL
)
```

### "What is Mahnoor working on?"
```sql
SELECT f.object_val FROM facts f
WHERE f.subject_id = 'person-mahnoor'
AND f.predicate = 'works_on'
AND f.valid_until IS NULL
```

## How to Query in Python

```python
import sys; sys.path.insert(0, '.claude/hooks')
from kamil_brain import get_brain_db, find_entity, query_facts
db = get_brain_db()
persons = find_entity(db, 'Mashood')
if persons:
    facts = query_facts(db, subject_id=persons[0]['id'], predicate='recommended')
    for f in facts:
        print(f['object_val'] or f['object_id'])
db.close()
```

## What Works
<!-- append lessons after sessions -->

## What to Avoid
- Never store facts only in markdown files without brain.db entry
- Never ask "do you remember X" — query brain.db first
- Never create duplicate entities — check find_entity() before upsert_entity()
- Never hardcode entity IDs in scripts — resolve by name using find_entity()
- Never use raw SQL string formatting — always use parameterized queries
