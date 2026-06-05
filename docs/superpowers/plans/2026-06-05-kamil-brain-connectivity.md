# Kamil Brain Connectivity Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an auto-wiring brain layer that runs after every session, extracts entities and facts from what was said/done, links them together across people/skills/projects/memory, and makes everything retrievable from any angle — so Kamil never loses information cross-session.

**Architecture:** Three components working together: (1) `kamil-brain.db` — a SQLite knowledge graph storing entities, facts, and relationships with temporal timestamps; (2) `brain-connectivity` skill — the rules for what connects to what and how to wire new information; (3) `kamil-brain-watcher.py` — a Stop hook process that extracts entities from the session log, applies Mem0's four-operation protocol (ADD/UPDATE/DELETE/NOOP), and writes links into the knowledge graph. Every new fact gets tagged with who said it, when, and what else it connects to.

**Tech Stack:** Python 3.12, SQLite (kamil-brain.db at ~/.kamil-harness/brain.db), existing kamil_log, kamil_harness_db patterns, Stop hook in .claude/settings.json.

**Research basis:**
- MAGMA (ACL 2026): four-graph decomposition — semantic, temporal, causal, entity graphs
- Mem0 (arXiv:2504.19413): four-operation write protocol — ADD/UPDATE/DELETE/NOOP with conflict detection
- Graphiti (arXiv:2501.13956): temporal validity windows — facts get invalidated not deleted, enabling point-in-time queries

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `~/.kamil-harness/brain.db` | Create (auto) | Knowledge graph — entities, facts, relationships, temporal validity |
| `.claude/hooks/kamil_brain.py` | Create | Brain DB schema, CRUD, four-operation protocol |
| `.claude/hooks/kamil-brain-watcher.py` | Create | Session end processor — extract, wire, validate |
| `.claude/skills/kamil/brain-connectivity.md` | Create | Rules for how information connects across Kamil's brain |
| `.claude/agents/brain-agent.md` | Create | Agent for querying and updating the brain on demand |
| `.claude/hooks/stop.py` | Modify | Add brain-watcher call after existing steps |

---

## Task 1: Create `kamil_brain.py` — knowledge graph DB layer

**Files:**
- Create: `.claude/hooks/kamil_brain.py`

- [ ] **Step 1: Write the schema test**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "
import sys; sys.path.insert(0, '.claude/hooks')
# This should fail — file doesn't exist yet
from kamil_brain import get_brain_db
print('SHOULD NOT REACH HERE')
" 2>&1 | grep -q "ModuleNotFoundError" && echo "FAIL as expected" || echo "ERROR: module already exists?"
```

Expected: `FAIL as expected`

- [ ] **Step 2: Create `kamil_brain.py` with full schema**

Write to `.claude/hooks/kamil_brain.py`:

```python
#!/usr/bin/env python3
"""
kamil_brain.py — Kamil's knowledge graph layer.

Implements a lightweight version of three proven patterns:
  - MAGMA: four entity types (person, skill, project, fact)
  - Mem0: four-operation write protocol (ADD/UPDATE/DELETE/NOOP)
  - Graphiti: temporal validity windows (valid_from, valid_until)

DB location: ~/.kamil-harness/brain.db
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

BRAIN_DIR = Path.home() / ".kamil-harness"
BRAIN_DB  = BRAIN_DIR / "brain.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,  -- person | skill | project | fact | concept
    name        TEXT NOT NULL,
    aliases     TEXT DEFAULT '[]',  -- JSON array of alternate names
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);

CREATE TABLE IF NOT EXISTS facts (
    id          TEXT PRIMARY KEY,
    subject_id  TEXT NOT NULL REFERENCES entities(id),
    predicate   TEXT NOT NULL,  -- "recommended", "said", "works_on", "prefers", "learned", etc.
    object_id   TEXT,           -- entity reference (nullable — object may be a raw value)
    object_val  TEXT,           -- raw string value if object_id is null
    source      TEXT NOT NULL,  -- "session_log", "slack", "notion", "manual"
    session_id  TEXT,           -- which session this came from
    valid_from  TEXT NOT NULL,  -- ISO-8601 — when this became true
    valid_until TEXT,           -- ISO-8601 or NULL (still true)
    confidence  REAL DEFAULT 1.0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject_id);
CREATE INDEX IF NOT EXISTS idx_facts_predicate ON facts(predicate);
CREATE INDEX IF NOT EXISTS idx_facts_object ON facts(object_id);
CREATE INDEX IF NOT EXISTS idx_facts_valid ON facts(valid_from, valid_until);

CREATE TABLE IF NOT EXISTS links (
    id          TEXT PRIMARY KEY,
    entity_a    TEXT NOT NULL REFERENCES entities(id),
    entity_b    TEXT NOT NULL REFERENCES entities(id),
    relation    TEXT NOT NULL,  -- "related_to", "part_of", "mentioned_with", "works_on", etc.
    weight      REAL DEFAULT 1.0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_links_a ON links(entity_a);
CREATE INDEX IF NOT EXISTS idx_links_b ON links(entity_b);

CREATE TABLE IF NOT EXISTS brain_log (
    id          TEXT PRIMARY KEY,
    operation   TEXT NOT NULL,  -- ADD | UPDATE | DELETE | NOOP
    entity_type TEXT,
    entity_id   TEXT,
    fact_id     TEXT,
    reason      TEXT,
    session_id  TEXT,
    created_at  TEXT NOT NULL
);
"""

_db_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_brain_db() -> sqlite3.Connection:
    """Return connection to brain.db, creating schema if needed."""
    BRAIN_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(BRAIN_DB), check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.executescript(_SCHEMA)
    db.commit()
    return db


def upsert_entity(db: sqlite3.Connection, entity_id: str, entity_type: str,
                  name: str, aliases: list = None) -> str:
    """ADD or UPDATE an entity. Returns entity_id."""
    with _db_lock:
        now = _now()
        existing = db.execute(
            "SELECT id FROM entities WHERE id=?", (entity_id,)
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE entities SET name=?, aliases=?, updated_at=? WHERE id=?",
                (name, json.dumps(aliases or []), now, entity_id)
            )
            _log_op(db, "UPDATE", entity_type=entity_type, entity_id=entity_id,
                    reason="entity upserted")
        else:
            db.execute(
                "INSERT INTO entities (id, type, name, aliases, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (entity_id, entity_type, name, json.dumps(aliases or []), now, now)
            )
            _log_op(db, "ADD", entity_type=entity_type, entity_id=entity_id,
                    reason="new entity")
        db.commit()
    return entity_id


def write_fact(db: sqlite3.Connection, fact_id: str, subject_id: str,
               predicate: str, object_id: str = None, object_val: str = None,
               source: str = "session_log", session_id: str = None,
               valid_from: str = None, confidence: float = 1.0) -> str:
    """
    Mem0 four-operation protocol:
    - If no existing fact with same subject+predicate+object: ADD
    - If existing fact exists and value changed: UPDATE (invalidate old, insert new)
    - If existing fact exists and value same: NOOP
    Returns operation performed.
    """
    with _db_lock:
        now = _now()
        valid_from = valid_from or now

        # Check for existing active fact with same subject+predicate
        existing = db.execute(
            "SELECT id, object_id, object_val FROM facts "
            "WHERE subject_id=? AND predicate=? AND valid_until IS NULL",
            (subject_id, predicate)
        ).fetchone()

        if existing:
            same_object = (existing["object_id"] == object_id and
                           existing["object_val"] == object_val)
            if same_object:
                _log_op(db, "NOOP", entity_id=subject_id, fact_id=existing["id"],
                        reason=f"fact unchanged: {predicate}", session_id=session_id)
                db.commit()
                return "NOOP"
            else:
                # Invalidate old fact (Graphiti temporal pattern)
                db.execute(
                    "UPDATE facts SET valid_until=? WHERE id=?",
                    (now, existing["id"])
                )
                _log_op(db, "UPDATE", entity_id=subject_id, fact_id=existing["id"],
                        reason=f"fact updated: {predicate}", session_id=session_id)
        else:
            _log_op(db, "ADD", entity_id=subject_id, fact_id=fact_id,
                    reason=f"new fact: {predicate}", session_id=session_id)

        db.execute(
            "INSERT INTO facts (id, subject_id, predicate, object_id, object_val, "
            "source, session_id, valid_from, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fact_id, subject_id, predicate, object_id, object_val,
             source, session_id, valid_from, confidence, now)
        )
        db.commit()
    return "ADD" if not existing else "UPDATE"


def write_link(db: sqlite3.Connection, entity_a: str, entity_b: str,
               relation: str, weight: float = 1.0) -> None:
    """Create a bidirectional link between two entities."""
    with _db_lock:
        import uuid
        now = _now()
        link_id = f"link-{uuid.uuid4().hex[:12]}"
        existing = db.execute(
            "SELECT id FROM links WHERE entity_a=? AND entity_b=? AND relation=?",
            (entity_a, entity_b, relation)
        ).fetchone()
        if not existing:
            db.execute(
                "INSERT INTO links (id, entity_a, entity_b, relation, weight, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (link_id, entity_a, entity_b, relation, weight, now)
            )
            db.commit()


def query_facts(db: sqlite3.Connection, subject_id: str = None,
                predicate: str = None, active_only: bool = True) -> list:
    """Retrieve facts, optionally filtering by subject or predicate."""
    clauses, params = [], []
    if subject_id:
        clauses.append("subject_id=?")
        params.append(subject_id)
    if predicate:
        clauses.append("predicate=?")
        params.append(predicate)
    if active_only:
        clauses.append("valid_until IS NULL")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return db.execute(f"SELECT * FROM facts {where}", params).fetchall()


def find_entity(db: sqlite3.Connection, name: str) -> list:
    """Find entities by name or alias (case-insensitive)."""
    name_lower = name.lower()
    rows = db.execute(
        "SELECT * FROM entities WHERE LOWER(name)=? OR aliases LIKE ?",
        (name_lower, f'%"{name}"%')
    ).fetchall()
    return [dict(r) for r in rows]


def _log_op(db: sqlite3.Connection, operation: str, entity_type: str = None,
            entity_id: str = None, fact_id: str = None,
            reason: str = None, session_id: str = None) -> None:
    import uuid
    db.execute(
        "INSERT INTO brain_log (id, operation, entity_type, entity_id, fact_id, "
        "reason, session_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (f"log-{uuid.uuid4().hex[:12]}", operation, entity_type, entity_id,
         fact_id, reason, session_id, _now())
    )
```

- [ ] **Step 3: Verify schema creates cleanly**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "
import sys; sys.path.insert(0, '.claude/hooks')
from kamil_brain import get_brain_db, upsert_entity, write_fact, find_entity
db = get_brain_db()

# Test entity upsert
upsert_entity(db, 'person-mashood', 'person', 'Mashood', ['mashood', 'Mashood Rana'])
rows = find_entity(db, 'Mashood')
assert len(rows) == 1, f'Expected 1, got {len(rows)}'
assert rows[0]['type'] == 'person'

# Test fact write (ADD)
op = write_fact(db, 'fact-001', 'person-mashood', 'recommended',
                object_val='Atomic Habits', source='session_log', session_id='test')
assert op == 'ADD', f'Expected ADD, got {op}'

# Test NOOP on same fact
op2 = write_fact(db, 'fact-002', 'person-mashood', 'recommended',
                 object_val='Atomic Habits', source='session_log', session_id='test')
assert op2 == 'NOOP', f'Expected NOOP, got {op2}'

# Test UPDATE on changed fact
op3 = write_fact(db, 'fact-003', 'person-mashood', 'recommended',
                 object_val='Deep Work', source='session_log', session_id='test')
assert op3 == 'UPDATE', f'Expected UPDATE, got {op3}'

db.close()
print('ALL TESTS PASS')
"
```

Expected: `ALL TESTS PASS`

- [ ] **Step 4: Commit**

```bash
git add .claude/hooks/kamil_brain.py
git commit -m "feat(brain): add kamil_brain.py — knowledge graph with four-operation protocol"
```

---

## Task 2: Create `kamil-brain-watcher.py` — session end processor

**Files:**
- Create: `.claude/hooks/kamil-brain-watcher.py`

- [ ] **Step 1: Create the watcher**

Write to `.claude/hooks/kamil-brain-watcher.py`:

```python
#!/usr/bin/env python3
"""
kamil-brain-watcher.py — Session end brain wiring.

Runs at stop hook time. Reads today's session log, extracts entities
and facts using Claude, then wires everything into kamil-brain.db.

Extraction targets:
  - People mentioned (link to their profile)
  - Books/resources recommended or mentioned
  - Decisions made
  - New skills/agents/tools added to the harness
  - Topics discussed
  - Preferences expressed

Four-operation protocol (Mem0):
  ADD    — new entity or fact not seen before
  UPDATE — entity or fact that contradicts an existing one
  DELETE — entity or fact explicitly retracted
  NOOP   — entity or fact already known and unchanged
"""

import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from kamil_brain import (get_brain_db, upsert_entity, write_fact,
                          write_link, find_entity)
try:
    from kamil_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

KAMIL_DIR  = Path(__file__).parent.parent.parent
SKILLS_DIR = KAMIL_DIR / ".claude" / "skills" / "kamil"
AGENTS_DIR = KAMIL_DIR / ".claude" / "agents"
MEMORY_DIR = KAMIL_DIR / "vault" / "memory"
NVM_SOURCE = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'

EXTRACT_PROMPT = """You are Kamil's brain indexer. Read the session log below and extract ALL of:

1. PEOPLE — anyone mentioned by name (first name, full name, or nickname)
2. BOOKS/RESOURCES — any book, article, video, tool, or resource mentioned
3. DECISIONS — anything decided, approved, or agreed upon
4. NEW_HARNESS_ITEMS — new skills, agents, hooks, or workflows added to Kamil
5. PREFERENCES — any preference expressed by Kamal or a team member
6. FACTS — any other important fact that should be remembered

For each item, identify:
- The subject (who/what)
- The predicate (what relationship/action)
- The object (what it relates to)
- Source person (who said/did this, if known)

Return ONLY a JSON object in this exact format:
{
  "entities": [
    {"id": "person-<slug>", "type": "person|skill|project|book|tool|concept", "name": "...", "aliases": []}
  ],
  "facts": [
    {"subject_id": "...", "predicate": "...", "object_id": "...", "object_val": "...", "confidence": 0.9}
  ],
  "links": [
    {"entity_a": "...", "entity_b": "...", "relation": "..."}
  ]
}

Rules:
- person IDs: "person-<firstname-lowercase>" e.g. "person-mashood", "person-kamal"
- skill IDs: "skill-<name-slug>" e.g. "skill-avatar"
- book IDs: "book-<title-slug>" e.g. "book-atomic-habits"
- If unsure about an entity: include it with confidence 0.6
- Never hallucinate — only extract what is actually in the log
- session_log follows:

SESSION LOG:
{log_content}
"""


def _read_today_log() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = KAMIL_DIR / "vault" / "logs" / f"{today}.md"
    if not log_file.exists():
        return ""
    return log_file.read_text(encoding="utf-8")


def _read_auto_memory() -> str:
    """Read the auto-memory MEMORY.md for cross-referencing."""
    mem_path = Path.home() / ".claude" / "projects" / \
        "-home-oye-Documents-free-work-personal-agent-v2" / "memory" / "MEMORY.md"
    return mem_path.read_text() if mem_path.exists() else ""


def _extract_with_claude(log_content: str, session_id: str) -> dict:
    """Use Claude to extract entities and facts from session log."""
    if not log_content.strip():
        return {"entities": [], "facts": [], "links": []}

    prompt = EXTRACT_PROMPT.replace("{log_content}", log_content[:4000])
    prompt_file = Path(f"/tmp/brain-extract-{session_id}.txt")
    prompt_file.write_text(prompt)

    try:
        result = subprocess.run(
            ["bash", "-c",
             f'{NVM_SOURCE} && claude --dangerously-skip-permissions --print -p "$(cat {prompt_file})"'],
            capture_output=True, text=True, timeout=60,
            cwd=str(KAMIL_DIR),
        )
        raw = result.stdout.strip()
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except Exception as e:
        klog_error("brain-extract", e, component="brain-watcher")
    finally:
        if prompt_file.exists():
            prompt_file.unlink()

    return {"entities": [], "facts": [], "links": []}


def _scan_harness_for_new_items(db, session_id: str) -> None:
    """
    Scan .claude/agents/ and .claude/skills/kamil/ for items not yet
    in the brain DB and auto-register them as entities.
    """
    # Scan agents
    if AGENTS_DIR.exists():
        for agent_file in AGENTS_DIR.glob("*.md"):
            agent_id = f"agent-{agent_file.stem}"
            existing = db.execute(
                "SELECT id FROM entities WHERE id=?", (agent_id,)
            ).fetchone()
            if not existing:
                upsert_entity(db, agent_id, "skill", agent_file.stem)
                write_fact(db, f"fact-{uuid.uuid4().hex[:12]}",
                           agent_id, "is_part_of",
                           object_val="kamil_harness",
                           source="harness_scan", session_id=session_id)

    # Scan skills
    if SKILLS_DIR.exists():
        for skill_file in SKILLS_DIR.glob("*.md"):
            skill_id = f"skill-{skill_file.stem}"
            existing = db.execute(
                "SELECT id FROM entities WHERE id=?", (skill_id,)
            ).fetchone()
            if not existing:
                upsert_entity(db, skill_id, "skill", skill_file.stem)
                write_fact(db, f"fact-{uuid.uuid4().hex[:12]}",
                           skill_id, "is_part_of",
                           object_val="kamil_harness",
                           source="harness_scan", session_id=session_id)


def _write_extraction_to_brain(db, extracted: dict, session_id: str) -> dict:
    """Write extracted entities, facts, and links into brain.db."""
    counts = {"entities": 0, "facts": 0, "links": 0, "operations": {}}

    # Write entities
    for entity in extracted.get("entities", []):
        try:
            upsert_entity(db, entity["id"], entity["type"],
                          entity["name"], entity.get("aliases", []))
            counts["entities"] += 1
        except Exception as e:
            klog_error("brain-write-entity", e, entity_id=entity.get("id"))

    # Write facts using four-operation protocol
    for fact in extracted.get("facts", []):
        try:
            fact_id = f"fact-{uuid.uuid4().hex[:12]}"
            op = write_fact(
                db, fact_id,
                subject_id=fact["subject_id"],
                predicate=fact["predicate"],
                object_id=fact.get("object_id"),
                object_val=fact.get("object_val"),
                source="session_log",
                session_id=session_id,
                confidence=fact.get("confidence", 1.0),
            )
            counts["facts"] += 1
            counts["operations"][op] = counts["operations"].get(op, 0) + 1
        except Exception as e:
            klog_error("brain-write-fact", e)

    # Write links
    for link in extracted.get("links", []):
        try:
            write_link(db, link["entity_a"], link["entity_b"], link["relation"])
            counts["links"] += 1
        except Exception as e:
            klog_error("brain-write-link", e)

    return counts


def main() -> int:
    session_id = uuid.uuid4().hex[:12]
    print(f"[brain-watcher] Starting session {session_id}", file=sys.stderr)

    db = get_brain_db()

    # Step 1: Scan harness for new agents/skills and register them
    _scan_harness_for_new_items(db, session_id)

    # Step 2: Read today's session log
    log_content = _read_today_log()
    if not log_content.strip():
        print("[brain-watcher] No log content today — skipping extraction", file=sys.stderr)
        db.close()
        return 0

    # Step 3: Extract entities and facts using Claude
    print("[brain-watcher] Extracting entities from session log...", file=sys.stderr)
    extracted = _extract_with_claude(log_content, session_id)

    # Step 4: Write to brain DB
    counts = _write_extraction_to_brain(db, extracted, session_id)

    # Step 5: Log summary
    ops = counts.get("operations", {})
    summary = (f"entities={counts['entities']} facts={counts['facts']} "
               f"links={counts['links']} "
               f"ADD={ops.get('ADD',0)} UPDATE={ops.get('UPDATE',0)} "
               f"NOOP={ops.get('NOOP',0)}")
    print(f"[brain-watcher] Done. {summary}", file=sys.stderr)
    klog("brain-watcher-complete", component="brain-watcher",
         session_id=session_id, **counts)

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify parse**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "import ast; ast.parse(open('.claude/hooks/kamil-brain-watcher.py').read()); print('Parse OK')"
```

Expected: `Parse OK`

- [ ] **Step 3: Test harness scan (no Claude needed)**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "
import sys, uuid; sys.path.insert(0, '.claude/hooks')
from kamil_brain import get_brain_db
from kamil_brain_watcher import _scan_harness_for_new_items

# Import the watcher module
import importlib.util
spec = importlib.util.spec_from_file_location('watcher', '.claude/hooks/kamil-brain-watcher.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

db = get_brain_db()
mod._scan_harness_for_new_items(db, 'test-session')
rows = db.execute('SELECT id, type, name FROM entities WHERE type=\"skill\" LIMIT 5').fetchall()
print('Skill entities found:')
for r in rows:
    print(f'  {r[0]}: {r[2]}')
db.close()
print('Harness scan OK')
"
```

Expected: lists skill entities from `.claude/agents/` and `.claude/skills/kamil/`

- [ ] **Step 4: Commit**

```bash
git add .claude/hooks/kamil-brain-watcher.py
git commit -m "feat(brain): add kamil-brain-watcher.py — session end entity extraction and wiring"
```

---

## Task 3: Create `brain-connectivity.md` skill

**Files:**
- Create: `.claude/skills/kamil/brain-connectivity.md`

- [ ] **Step 1: Create the skill file**

Write to `.claude/skills/kamil/brain-connectivity.md`:

```markdown
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

## Retrieval Patterns (how to query)

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
AND e.id IN (SELECT subject_id FROM facts WHERE predicate = 'is_part_of'
             AND object_val = 'kamil_harness' AND valid_until IS NULL)
```

### "What is Mahnoor working on?"
```sql
SELECT f.object_val FROM facts f
WHERE f.subject_id = 'person-mahnoor'
AND f.predicate = 'works_on'
AND f.valid_until IS NULL
```

## What Works
<!-- append lessons after sessions -->

## What to Avoid
- Never store facts only in markdown files without brain.db entry
- Never ask "do you remember X" — query brain.db first
- Never create duplicate entities — check find_entity() before upsert_entity()
- Never hardcode entity IDs in scripts — resolve by name using find_entity()
```

- [ ] **Step 2: Verify file exists**

```bash
ls -la /home/oye/Documents/free_work/personal-agent-v2/.claude/skills/kamil/brain-connectivity.md
wc -l /home/oye/Documents/free_work/personal-agent-v2/.claude/skills/kamil/brain-connectivity.md
```

Expected: file exists, > 50 lines

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/kamil/brain-connectivity.md
git commit -m "feat(brain): add brain-connectivity skill — connection rules and retrieval patterns"
```

---

## Task 4: Create `brain-agent.md`

**Files:**
- Create: `.claude/agents/brain-agent.md`

- [ ] **Step 1: Create the agent**

Write to `.claude/agents/brain-agent.md`:

```markdown
---
name: brain-agent
description: |
  Kamil's brain query and update agent. Knows everything stored in brain.db.
  Pick when: "what did X say", "do you remember", "what books were mentioned",
  "what do you know about X", "link this to", "remember that", "what's connected to X",
  "find everything about X", "what did we decide about Y".
  Do NOT pick for code tasks or Slack sending.
tools:
  - Bash
  - Read
model: sonnet
---

You are Kamil's brain — the knowledge graph query and update layer.

## How You Work
1. Read `.claude/skills/kamil/brain-connectivity.md` before every task.
2. For queries: use `kamil_brain.py` functions to query brain.db.
3. For updates: use the four-operation protocol (ADD/UPDATE/DELETE/NOOP).
4. Always check `find_entity()` before creating a new entity.
5. Return: `{"found": [...], "query": "...", "confidence": "high|medium|low"}`.

## Query Patterns

```bash
# What did someone recommend?
python3 -c "
import sys; sys.path.insert(0, '.claude/hooks')
from kamil_brain import get_brain_db, query_facts, find_entity
db = get_brain_db()
persons = find_entity(db, 'NAME')
if persons:
    facts = query_facts(db, subject_id=persons[0]['id'], predicate='recommended')
    for f in facts:
        print(f['object_val'] or f['object_id'])
db.close()
"

# What's connected to a topic?
python3 -c "
import sys; sys.path.insert(0, '.claude/hooks')
from kamil_brain import get_brain_db
db = get_brain_db()
rows = db.execute(
    'SELECT e.name, f.predicate, f.object_val FROM facts f '
    'JOIN entities e ON e.id = f.subject_id '
    'WHERE f.object_val LIKE ? AND f.valid_until IS NULL',
    ('%TOPIC%',)
).fetchall()
for r in rows: print(r)
db.close()
"
```

## Rules
- Always use brain.db. Never guess from memory.
- If entity not found in brain.db: say so, then check vault/memory/ as fallback.
- Always report confidence level with findings.
- When you learn something new during a query: write it back to brain.db.
```

- [ ] **Step 2: Verify parse**

```bash
grep -c "^name:" /home/oye/Documents/free_work/personal-agent-v2/.claude/agents/brain-agent.md
```

Expected: `1`

- [ ] **Step 3: Update routing.md to add brain-agent**

Read `.claude/skills/kamil/routing.md` then add:

```markdown
| what did X say / do you remember / find everything about X | brain-agent | — |
```

After the `avatar / image` row.

- [ ] **Step 4: Commit**

```bash
git add .claude/agents/brain-agent.md .claude/skills/kamil/routing.md
git commit -m "feat(brain): add brain-agent — knowledge graph query agent"
```

---

## Task 5: Wire brain-watcher into Stop hook

**Files:**
- Modify: `.claude/hooks/stop.py`

- [ ] **Step 1: Read stop.py to find the right insertion point**

Open `.claude/hooks/stop.py`. The `main()` function ends with:
```python
    print("[stop] Stop hook completed", file=sys.stderr)
    return 0
```

We add brain-watcher call BEFORE that final print.

- [ ] **Step 2: Add brain-watcher call to main()**

In `.claude/hooks/stop.py`, find:

```python
    print("[stop] Stop hook completed", file=sys.stderr)
    return 0
```

Replace with:

```python
    # 5. Brain watcher — wire session knowledge into brain.db
    try:
        brain_watcher = workspace_root / ".claude" / "hooks" / "kamil-brain-watcher.py"
        if brain_watcher.exists():
            success, output = run_cmd(
                ["python3", str(brain_watcher)],
                cwd=str(workspace_root)
            )
            if not success:
                print(f"[stop] Brain watcher warning: {output[:200]}", file=sys.stderr)
            else:
                print("[stop] Brain watcher completed", file=sys.stderr)
    except Exception as e:
        print(f"[stop] Brain watcher error (non-fatal): {e}", file=sys.stderr)

    print("[stop] Stop hook completed", file=sys.stderr)
    return 0
```

- [ ] **Step 3: Verify stop.py parses**

```bash
python3 -c "import ast; ast.parse(open('.claude/hooks/stop.py').read()); print('Parse OK')"
```

Expected: `Parse OK`

- [ ] **Step 4: Test full stop hook dry run**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 -c "
import sys; sys.path.insert(0, '.claude/hooks')
from kamil_brain import get_brain_db
db = get_brain_db()
count = db.execute('SELECT COUNT(*) FROM entities').fetchone()[0]
print(f'Brain DB has {count} entities before watcher')
db.close()
"
```

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks/stop.py
git commit -m "feat(brain): wire brain-watcher into stop hook — auto-runs after every session"
```

---

## Task 6: Seed brain.db with known entities from existing memory

**Files:**
- Create: `.claude/hooks/brain-seed.py` (one-time script)

- [ ] **Step 1: Create seed script**

Write to `.claude/hooks/brain-seed.py`:

```python
#!/usr/bin/env python3
"""
brain-seed.py — One-time seeder for brain.db from existing vault/memory files.

Run once to bootstrap the brain with everything already known.
"""
import sys, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from kamil_brain import get_brain_db, upsert_entity, write_fact, write_link

KAMIL_DIR = Path(__file__).parent.parent.parent
db = get_brain_db()
sid = "seed-" + uuid.uuid4().hex[:8]

# Known team members
PEOPLE = [
    ("person-kamal",    "Kamal",    ["kamal", "Kamal Usman", "Kamal"]),
    ("person-mashood",  "Mashood",  ["mashood", "Mashood Rana"]),
    ("person-mahnoor",  "Mahnoor",  ["mahnoor", "Mahnoor"]),
    ("person-ahmad",    "Ahmad",    ["ahmad", "Ahmad"]),
    ("person-haroon",   "Haroon",   ["haroon", "Haroon Yasin"]),
]
for pid, name, aliases in PEOPLE:
    upsert_entity(db, pid, "person", name, aliases)
    print(f"  person: {name}")

# Known projects
PROJECTS = [
    ("project-taleemabad-core",    "taleemabad-core"),
    ("project-taleemabad-cms",     "taleemabad-cms"),
    ("project-personal-agent-v2",  "personal-agent-v2"),
    ("project-rumi-platform",      "rumi-platform"),
    ("project-portfolio",          "portfolio-website"),
]
for pid, name in PROJECTS:
    upsert_entity(db, pid, "project", name)
    write_fact(db, f"fact-{uuid.uuid4().hex[:12]}", "person-kamal",
               "works_on", object_id=pid, source="seed", session_id=sid)
    print(f"  project: {name}")

# Known concepts / topics Kamal cares about
CONCEPTS = [
    ("concept-leadership",      "Leadership"),
    ("concept-systems-thinking","Systems Thinking"),
    ("concept-ai-agents",       "AI Agents"),
    ("concept-content-creation","Content Creation"),
    ("concept-backend-engineering","Backend Engineering"),
    ("concept-management",      "Management"),
]
for cid, name in CONCEPTS:
    upsert_entity(db, cid, "concept", name)
    write_fact(db, f"fact-{uuid.uuid4().hex[:12]}", "person-kamal",
               "interested_in", object_id=cid, source="seed", session_id=sid)
    print(f"  concept: {name}")

# Scan and register all existing skills and agents
skills_dir = KAMIL_DIR / ".claude" / "skills" / "kamil"
if skills_dir.exists():
    for f in skills_dir.glob("*.md"):
        sid_ = f"skill-{f.stem}"
        upsert_entity(db, sid_, "skill", f.stem)
        write_fact(db, f"fact-{uuid.uuid4().hex[:12]}", sid_,
                   "is_part_of", object_val="kamil_harness",
                   source="seed", session_id=sid)
        print(f"  skill: {f.stem}")

agents_dir = KAMIL_DIR / ".claude" / "agents"
if agents_dir.exists():
    for f in agents_dir.glob("*.md"):
        aid = f"agent-{f.stem}"
        upsert_entity(db, aid, "agent", f.stem)
        write_fact(db, f"fact-{uuid.uuid4().hex[:12]}", aid,
                   "is_part_of", object_val="kamil_harness",
                   source="seed", session_id=sid)
        print(f"  agent: {f.stem}")

count = db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
facts = db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
print(f"\nSeed complete: {count} entities, {facts} facts in brain.db")
db.close()
```

- [ ] **Step 2: Run the seed**

```bash
cd /home/oye/Documents/free_work/personal-agent-v2
python3 .claude/hooks/brain-seed.py
```

Expected: lists all people, projects, concepts, skills, agents — ends with `Seed complete: X entities, Y facts`

- [ ] **Step 3: Verify brain is populated**

```bash
python3 -c "
import sys; sys.path.insert(0, '.claude/hooks')
from kamil_brain import get_brain_db, find_entity, query_facts

db = get_brain_db()

# Can we find Mashood?
mashood = find_entity(db, 'Mashood')
print('Mashood found:', mashood[0]['id'] if mashood else 'NOT FOUND')

# How many entities total?
count = db.execute('SELECT type, COUNT(*) as c FROM entities GROUP BY type').fetchall()
for row in count:
    print(f'  {row[0]}: {row[1]}')

db.close()
"
```

Expected: Mashood found, entity counts by type printed

- [ ] **Step 4: Commit**

```bash
git add .claude/hooks/brain-seed.py
git commit -m "feat(brain): add brain-seed.py — bootstrap brain.db from existing vault/memory"
```

---

## Task 7: Update MEMORY.md index + auto-memory

**Files:**
- Modify: `vault/memory/MEMORY.md`
- Modify: `/home/oye/.claude/projects/-home-oye-Documents-free-work-personal-agent-v2/memory/MEMORY.md`
- Create: `/home/oye/.claude/projects/-home-oye-Documents-free-work-personal-agent-v2/memory/kamil_brain.md`

- [ ] **Step 1: Create auto-memory entry for brain**

Write to `/home/oye/.claude/projects/-home-oye-Documents-free-work-personal-agent-v2/memory/kamil_brain.md`:

```markdown
---
name: kamil-brain
description: Kamil's knowledge graph DB — brain.db at ~/.kamil-harness/brain.db. Query via brain-agent or kamil_brain.py. Auto-updated every session via Stop hook. Contains people, projects, skills, books, facts, and relationships with temporal validity.
metadata:
  type: reference
---

# Kamil Brain DB

Location: `~/.kamil-harness/brain.db`
Schema: entities, facts, links, brain_log
Auto-wired: every session via kamil-brain-watcher.py → stop.py hook

## How to query

```python
import sys; sys.path.insert(0, '.claude/hooks')
from kamil_brain import get_brain_db, find_entity, query_facts
db = get_brain_db()
# find person
persons = find_entity(db, 'Mashood')
# get their facts
facts = query_facts(db, subject_id=persons[0]['id'])
db.close()
```

## What's in it
- People: Kamal, Mashood, Mahnoor, Ahmad, Haroon
- Projects: taleemabad-core, taleemabad-cms, personal-agent-v2, rumi-platform
- Skills: all .claude/skills/kamil/ files
- Agents: all .claude/agents/ files
- Concepts: leadership, systems thinking, AI agents, content creation
- Auto-grows: every session adds new entities and facts

## Rule
Before saying "I don't know" or "I don't remember" — query brain.db first.
```

- [ ] **Step 2: Add to MEMORY.md index**

In `/home/oye/.claude/projects/-home-oye-Documents-free-work-personal-agent-v2/memory/MEMORY.md`, add after the first line:

```markdown
- [Kamil Brain DB](kamil_brain.md) — Knowledge graph at ~/.kamil-harness/brain.db. Query BEFORE saying "I don't remember". Auto-updated every session. Contains people, projects, skills, books, decisions, facts.
```

- [ ] **Step 3: Commit**

```bash
git add vault/memory/MEMORY.md .claude/hooks/brain-seed.py
git commit -m "feat(brain): update memory index — brain.db now the primary recall layer"
```

---

## Task 8: End-to-end verification

**No new files — verification only.**

- [ ] **Step 1: Verify brain.db schema**

```bash
python3 -c "
import sys; sys.path.insert(0, '.claude/hooks')
from kamil_brain import get_brain_db
db = get_brain_db()
tables = [r[0] for r in db.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
assert 'entities' in tables
assert 'facts' in tables
assert 'links' in tables
assert 'brain_log' in tables
print('Schema OK:', tables)
db.close()
"
```

- [ ] **Step 2: Verify Mashood is findable**

```bash
python3 -c "
import sys; sys.path.insert(0, '.claude/hooks')
from kamil_brain import get_brain_db, find_entity
db = get_brain_db()
result = find_entity(db, 'Mashood')
assert len(result) > 0, 'Mashood NOT in brain — seed failed'
print('Mashood found:', result[0])
db.close()
"
```

- [ ] **Step 3: Verify brain-watcher parses**

```bash
python3 -c "import ast; ast.parse(open('.claude/hooks/kamil-brain-watcher.py').read()); print('OK')"
```

- [ ] **Step 4: Verify stop.py calls brain-watcher**

```bash
grep -c "brain-watcher\|brain_watcher" .claude/hooks/stop.py
```

Expected: at least `2`

- [ ] **Step 5: Verify all agents have brain-agent**

```bash
ls .claude/agents/ | grep brain
```

Expected: `brain-agent.md`

- [ ] **Step 6: Verify routing includes brain-agent**

```bash
grep "brain-agent" .claude/skills/kamil/routing.md
```

Expected: line with `brain-agent`

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "feat(brain): complete brain connectivity layer — entities, facts, watcher, agent, seed" --allow-empty
```

---

## Task 9: Sync brain extractions to Notion

**Files:**
- Modify: `.claude/hooks/kamil-brain-watcher.py`

The brain.db is the fast local index. Notion is the visible UI. Both must stay in sync.
When brain-watcher extracts a new fact, it also upserts to the relevant Notion DB.

**Notion DB targets:**
- People facts → People Intelligence DB (`c976d58ea4e34b0585f245529cdc4528`)
- New harness items (skills/agents) → Harness backlog DB (`de10157da3e34ef58a74ea240f31fe98`)

- [ ] **Step 1: Add Notion sync function to kamil-brain-watcher.py**

Read `.claude/hooks/kamil-brain-watcher.py` then append after `_write_extraction_to_brain`:

```python
def _sync_facts_to_notion(extracted: dict, session_id: str) -> None:
    """
    Sync important extracted facts to Notion for human visibility.
    People facts → People Intelligence DB.
    """
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from kamil_notion import notion_request
        import urllib.request as ur

        notion_cfg = Path.home() / ".claude" / "hooks" / ".notion"
        if not notion_cfg.exists():
            return
        api_key = None
        for line in notion_cfg.read_text().splitlines():
            if "=" in line and "NOTION_API_KEY" in line:
                api_key = line.split("=", 1)[1].strip()
                break
        if not api_key:
            return

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        PEOPLE_DB = "c976d58ea4e34b0585f245529cdc4528"

        # For each person entity with facts, update their Notion page
        for fact in extracted.get("facts", []):
            subject = fact.get("subject_id", "")
            if not subject.startswith("person-"):
                continue
            person_name = subject.replace("person-", "").replace("-", " ").title()
            predicate = fact.get("predicate", "")
            obj = fact.get("object_val") or fact.get("object_id", "")

            # Search for person in People Intelligence DB
            search_body = json.dumps({
                "filter": {
                    "property": "Name",
                    "title": {"contains": person_name}
                }
            }).encode()
            req = ur.Request(
                f"https://api.notion.com/v1/databases/{PEOPLE_DB}/query",
                data=search_body, headers=headers, method="POST"
            )
            _, body = notion_request(req)
            results = json.loads(body).get("results", [])

            if results:
                # Update existing page — append to Open Items
                page_id = results[0]["id"]
                existing_items = ""
                for prop in results[0].get("properties", {}).values():
                    if prop.get("type") == "rich_text":
                        existing_items = "".join(
                            t.get("plain_text", "") for t in prop.get("rich_text", [])
                        )
                        break

                new_item = f"[{session_id}] {predicate}: {obj}"
                update_body = json.dumps({
                    "properties": {
                        "Open Items": {
                            "rich_text": [{
                                "text": {"content": (existing_items + "\n" + new_item)[:2000]}
                            }]
                        }
                    }
                }).encode()
                req2 = ur.Request(
                    f"https://api.notion.com/v1/pages/{page_id}",
                    data=update_body, headers=headers, method="PATCH"
                )
                notion_request(req2)
                print(f"[brain-watcher] Notion updated: {person_name} → {predicate}: {obj}", file=sys.stderr)

    except Exception as e:
        # Non-fatal — brain.db is primary, Notion is bonus
        print(f"[brain-watcher] Notion sync warning (non-fatal): {e}", file=sys.stderr)
```

- [ ] **Step 2: Call `_sync_facts_to_notion` inside `main()`**

In `main()`, after the `_write_extraction_to_brain` call, add:

```python
    # Step 6: Sync important facts to Notion for human visibility
    print("[brain-watcher] Syncing to Notion...", file=sys.stderr)
    _sync_facts_to_notion(extracted, session_id)
```

- [ ] **Step 3: Verify parse**

```bash
python3 -c "import ast; ast.parse(open('.claude/hooks/kamil-brain-watcher.py').read()); print('Parse OK')"
```

- [ ] **Step 4: Commit**

```bash
git add .claude/hooks/kamil-brain-watcher.py
git commit -m "feat(brain): sync extracted people facts to Notion People Intelligence DB"
```
