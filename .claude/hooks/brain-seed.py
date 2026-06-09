#!/usr/bin/env python3
"""
brain-seed.py — One-time seeder for brain.db from existing vault/memory files.

Run once to bootstrap the brain with everything already known.
Safe to re-run — upsert_entity is idempotent.
"""
import sys, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from kamil_brain import get_brain_db, upsert_entity, write_fact, write_link

KAMIL_DIR = Path(__file__).parent.parent.parent
db = get_brain_db()
sid = "seed-" + uuid.uuid4().hex[:8]

# Known team members — replace with your own after /setup
PEOPLE = [
    ("person-you",      "{{USER_NAME}}", ["{{USER_NAME}}"]),
    # Add your team members here:
    # ("person-alice",  "Alice",    ["alice", "Alice Smith"]),
]
for pid, name, aliases in PEOPLE:
    upsert_entity(db, pid, "person", name, aliases)
    print(f"  person: {name}")

# Known projects — replace with your own after /setup
PROJECTS = [
    ("project-personal-agent-v2",  "personal-agent-v2"),
    # Add your projects here:
    # ("project-my-app",           "my-app"),
]
for pid, name in PROJECTS:
    upsert_entity(db, pid, "project", name)
    write_fact(db, f"fact-{uuid.uuid4().hex[:12]}", "person-you",
               "works_on", object_id=pid, source="seed", session_id=sid)
    print(f"  project: {name}")

# Known concepts — add or remove to match your interests
CONCEPTS = [
    ("concept-leadership",           "Leadership"),
    ("concept-systems-thinking",     "Systems Thinking"),
    ("concept-ai-agents",            "AI Agents"),
    ("concept-content-creation",     "Content Creation"),
    ("concept-backend-engineering",  "Backend Engineering"),
    ("concept-management",           "Management"),
]
for cid, name in CONCEPTS:
    upsert_entity(db, cid, "concept", name)
    write_fact(db, f"fact-{uuid.uuid4().hex[:12]}", "person-you",
               "interested_in", object_id=cid, source="seed", session_id=sid)
    print(f"  concept: {name}")

# Scan and register all existing skills
skills_dir = KAMIL_DIR / ".claude" / "skills"
if skills_dir.exists():
    for f in skills_dir.glob("*.md"):
        sid_ = f"skill-{f.stem}"
        upsert_entity(db, sid_, "skill", f.stem)
        write_fact(db, f"fact-{uuid.uuid4().hex[:12]}", sid_,
                   "is_part_of", object_val="agent_harness",
                   source="seed", session_id=sid)
        print(f"  skill: {f.stem}")

# Scan and register all existing agents
agents_dir = KAMIL_DIR / ".claude" / "agents"
if agents_dir.exists():
    for f in agents_dir.glob("*.md"):
        aid = f"agent-{f.stem}"
        upsert_entity(db, aid, "agent", f.stem)
        write_fact(db, f"fact-{uuid.uuid4().hex[:12]}", aid,
                   "is_part_of", object_val="agent_harness",
                   source="seed", session_id=sid)
        print(f"  agent: {f.stem}")

count = db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
facts = db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
print(f"\nSeed complete: {count} entities, {facts} facts in brain.db")
db.close()
