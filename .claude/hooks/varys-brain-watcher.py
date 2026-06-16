#!/usr/bin/env python3
"""
varys-brain-watcher.py — Passive brain indexer. Runs at session end (Stop hook).

Reads the actual conversation transcript (not the session log), extracts
durable facts using Claude, writes to brain.db.

Extracts: people, decisions, learnings, books/tools, preferences, harness changes.
"""

import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from varys_brain import get_brain_db, upsert_entity, write_fact, write_link

try:
    from varys_log import klog, klog_error
except Exception:
    klog = klog_error = lambda *a, **kw: None

VARYS_DIR  = Path(__file__).parent.parent.parent
SKILLS_DIR = VARYS_DIR / ".claude" / "skills" / "varys"
AGENTS_DIR = VARYS_DIR / ".claude" / "agents"
NVM_SOURCE = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'

EXTRACT_PROMPT = """You are Varys's brain indexer. Read the conversation below and extract durable facts worth remembering across future sessions.

Extract ONLY these categories:
1. DECISIONS — anything decided, approved, or explicitly agreed upon (e.g. "use X instead of Y", "don't do Z")
2. LEARNINGS — insights, discoveries, things that turned out to be true or false
3. PEOPLE — anyone mentioned by name with any context about them (role, team, what they did)
4. BOOKS / TOOLS / RESOURCES — any external resource referenced
5. PREFERENCES — how Shoaib wants things done, what he likes/dislikes
6. HARNESS_CHANGES — new skills, agents, hooks, or scripts added to Varys

Skip: small talk, routine tool calls, generic summaries. Only save facts that would be useful weeks from now.

Return ONLY valid JSON (no markdown, no explanation):
{
  "entities": [
    {"id": "decision-<slug>", "type": "decision|person|book|tool|concept|skill|agent", "name": "...", "aliases": []}
  ],
  "facts": [
    {"subject_id": "...", "predicate": "...", "object_id": null, "object_val": "...", "confidence": 0.9}
  ],
  "links": [
    {"entity_a": "...", "entity_b": "...", "relation": "..."}
  ]
}

ID rules:
- decision: "decision-<slug>"   e.g. "decision-slack-only-for-people"
- person:   "person-<firstname>" e.g. "person-mashood"
- book:     "book-<title-slug>"  e.g. "book-atomic-habits"
- tool:     "tool-<name>"        e.g. "tool-chromadb"
- concept:  "concept-<name>"

Fact predicates to use:
- decided: <what was decided>
- learned: <what was learned>
- prefers: <preference>
- mentioned: <context>
- referenced: <resource>
- added_to_harness: varys_harness

Never hallucinate. Only facts explicitly present in the conversation.

CONVERSATION:
{transcript}
"""


def _read_session_log():
    """Read today's vault/logs/YYYY-MM-DD.md — written by session-logger.py hook."""
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = VARYS_DIR / "vault" / "logs" / f"{today}.md"
    if not log_file.exists():
        return ""
    return log_file.read_text(encoding="utf-8")


def _extract_with_claude(transcript_text, session_id):
    if not transcript_text.strip():
        return {"entities": [], "facts": [], "links": []}

    # ponytail: cap at 6000 chars — enough context, cheap enough to run every session
    prompt = EXTRACT_PROMPT.replace("{transcript}", transcript_text[-6000:])
    prompt_file = Path(f"/tmp/brain-extract-{session_id}.txt")
    prompt_file.write_text(prompt, encoding="utf-8")

    try:
        result = subprocess.run(
            ["bash", "-c",
             f'{NVM_SOURCE} && claude --dangerously-skip-permissions --print -p "$(cat {prompt_file})"'],
            capture_output=True, text=True, timeout=60,
            cwd=str(VARYS_DIR),
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


def _scan_harness(db, session_id):
    """Register any new agents/skills not yet in brain.db."""
    for agent_file in (AGENTS_DIR.glob("*.md") if AGENTS_DIR.exists() else []):
        aid = f"agent-{agent_file.stem}"
        if not db.execute("SELECT 1 FROM entities WHERE id=?", (aid,)).fetchone():
            upsert_entity(db, aid, "agent", agent_file.stem)
            write_fact(db, f"fact-{uuid.uuid4().hex[:12]}", aid, "is_part_of",
                       object_val="varys_harness", source="harness_scan", session_id=session_id)

    for skill_file in (SKILLS_DIR.glob("*.md") if SKILLS_DIR.exists() else []):
        sid = f"skill-{skill_file.stem}"
        if not db.execute("SELECT 1 FROM entities WHERE id=?", (sid,)).fetchone():
            upsert_entity(db, sid, "skill", skill_file.stem)
            write_fact(db, f"fact-{uuid.uuid4().hex[:12]}", sid, "is_part_of",
                       object_val="varys_harness", source="harness_scan", session_id=session_id)


def _write_to_brain(db, extracted, session_id):
    counts = {"entities": 0, "facts": 0, "links": 0, "ops": {}}

    for entity in extracted.get("entities", []):
        try:
            upsert_entity(db, entity["id"], entity["type"],
                          entity["name"], entity.get("aliases", []))
            counts["entities"] += 1
        except Exception as e:
            klog_error("brain-write-entity", e, entity_id=entity.get("id"))

    for fact in extracted.get("facts", []):
        try:
            op = write_fact(
                db, f"fact-{uuid.uuid4().hex[:12]}",
                subject_id=fact["subject_id"],
                predicate=fact["predicate"],
                object_id=fact.get("object_id"),
                object_val=fact.get("object_val"),
                source="transcript",
                session_id=session_id,
                confidence=fact.get("confidence", 1.0),
            )
            counts["facts"] += 1
            counts["ops"][op] = counts["ops"].get(op, 0) + 1
        except Exception as e:
            klog_error("brain-write-fact", e)

    for link in extracted.get("links", []):
        try:
            write_link(db, link["entity_a"], link["entity_b"], link["relation"])
            counts["links"] += 1
        except Exception as e:
            klog_error("brain-write-link", e)

    return counts


def main():
    session_id = uuid.uuid4().hex[:12]

    # Drain stdin (Stop hook passes JSON we don't need)
    try:
        sys.stdin.read()
    except Exception:
        pass

    print(f"[brain-watcher] session={session_id}", file=sys.stderr)

    db = get_brain_db()
    _scan_harness(db, session_id)

    log_text = _read_session_log()
    if not log_text.strip():
        print("[brain-watcher] no session log today — skipping extraction", file=sys.stderr)
        db.close()
        return 0

    print(f"[brain-watcher] extracting from {len(log_text)} chars of session log...", file=sys.stderr)
    extracted = _extract_with_claude(log_text, session_id)

    counts = _write_to_brain(db, extracted, session_id)

    ops = counts["ops"]
    print(f"[brain-watcher] done. entities={counts['entities']} facts={counts['facts']} "
          f"links={counts['links']} ADD={ops.get('ADD',0)} UPDATE={ops.get('UPDATE',0)} "
          f"NOOP={ops.get('NOOP',0)}", file=sys.stderr)
    klog("brain-watcher-complete", component="brain-watcher",
         session_id=session_id, **{k: v for k, v in counts.items() if k != "ops"})

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
