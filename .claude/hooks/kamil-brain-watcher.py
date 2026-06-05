#!/usr/bin/env python3
"""
kamil-brain-watcher.py — Session end brain wiring.

Runs at stop hook time. Reads today's session log, extracts entities
and facts using Claude, then wires everything into kamil-brain.db.

Four-operation protocol (Mem0):
  ADD    — new entity or fact not seen before
  UPDATE — entity or fact that contradicts an existing one
  DELETE — entity or fact explicitly retracted
  NOOP   — entity or fact already known and unchanged
"""

import json
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
NVM_SOURCE = 'export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"'

EXTRACT_PROMPT = """You are Kamil's brain indexer. Read the session log below and extract ALL of:

1. PEOPLE — anyone mentioned by name
2. BOOKS/RESOURCES — any book, article, video, tool, or resource mentioned
3. DECISIONS — anything decided, approved, or agreed upon
4. NEW_HARNESS_ITEMS — new skills, agents, hooks, or workflows added to Kamil
5. PREFERENCES — any preference expressed by Kamal or a team member
6. FACTS — any other important fact that should be remembered

Return ONLY a JSON object:
{
  "entities": [
    {"id": "person-<slug>", "type": "person|skill|project|book|tool|concept", "name": "...", "aliases": []}
  ],
  "facts": [
    {"subject_id": "...", "predicate": "...", "object_id": null, "object_val": "...", "confidence": 0.9}
  ],
  "links": [
    {"entity_a": "...", "entity_b": "...", "relation": "..."}
  ]
}

ID naming rules:
- person: "person-<firstname-lowercase>" e.g. "person-mashood"
- skill: "skill-<name-slug>" e.g. "skill-avatar"
- book: "book-<title-slug>" e.g. "book-atomic-habits"

Never hallucinate — only extract what is in the log.

SESSION LOG:
{log_content}
"""


def _read_today_log():
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = KAMIL_DIR / "vault" / "logs" / f"{today}.md"
    if not log_file.exists():
        return ""
    return log_file.read_text(encoding="utf-8")


def _extract_with_claude(log_content, session_id):
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


def _scan_harness_for_new_items(db, session_id):
    """Scan agents/ and skills/kamil/ for new items not yet in brain.db."""
    if AGENTS_DIR.exists():
        for agent_file in AGENTS_DIR.glob("*.md"):
            agent_id = f"agent-{agent_file.stem}"
            existing = db.execute(
                "SELECT id FROM entities WHERE id=?", (agent_id,)
            ).fetchone()
            if not existing:
                upsert_entity(db, agent_id, "agent", agent_file.stem)
                write_fact(db, f"fact-{uuid.uuid4().hex[:12]}",
                           agent_id, "is_part_of",
                           object_val="kamil_harness",
                           source="harness_scan", session_id=session_id)

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


def _write_extraction_to_brain(db, extracted, session_id):
    """Write extracted entities, facts, and links into brain.db."""
    counts = {"entities": 0, "facts": 0, "links": 0, "operations": {}}

    for entity in extracted.get("entities", []):
        try:
            upsert_entity(db, entity["id"], entity["type"],
                          entity["name"], entity.get("aliases", []))
            counts["entities"] += 1
        except Exception as e:
            klog_error("brain-write-entity", e, entity_id=entity.get("id"))

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

    for link in extracted.get("links", []):
        try:
            write_link(db, link["entity_a"], link["entity_b"], link["relation"])
            counts["links"] += 1
        except Exception as e:
            klog_error("brain-write-link", e)

    return counts


def _sync_facts_to_notion(extracted, session_id):
    """Sync people facts to Notion People Intelligence DB (non-fatal if fails)."""
    try:
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

        for fact in extracted.get("facts", []):
            subject = fact.get("subject_id", "")
            if not subject.startswith("person-"):
                continue
            person_name = subject.replace("person-", "").replace("-", " ").title()
            predicate = fact.get("predicate", "")
            obj = fact.get("object_val") or fact.get("object_id", "")

            search_body = json.dumps({
                "filter": {"property": "Name", "title": {"contains": person_name}}
            }).encode()
            req = ur.Request(
                f"https://api.notion.com/v1/databases/{PEOPLE_DB}/query",
                data=search_body, headers=headers, method="POST"
            )
            _, body = notion_request(req)
            results = json.loads(body).get("results", [])

            if results:
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
                            "rich_text": [{"text": {"content": (existing_items + "\n" + new_item)[:2000]}}]
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
        print(f"[brain-watcher] Notion sync warning (non-fatal): {e}", file=sys.stderr)


def main():
    session_id = uuid.uuid4().hex[:12]
    print(f"[brain-watcher] Starting session {session_id}", file=sys.stderr)

    db = get_brain_db()

    # Step 1: Scan harness for new agents/skills
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

    # Step 5: Sync important facts to Notion
    print("[brain-watcher] Syncing to Notion...", file=sys.stderr)
    _sync_facts_to_notion(extracted, session_id)

    # Step 6: Log summary
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
