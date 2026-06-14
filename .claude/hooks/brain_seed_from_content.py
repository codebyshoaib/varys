#!/usr/bin/env python3
"""
brain_seed_from_content.py — Seeds brain.db from NLM notebook research.

Two modes:
  1. Called by content-scheduler.py after each track run:
       seed_from_nlm_insights(topic, track, nb_id, nlm_insights)
  2. Called directly to seed from any NLM notebook:
       python3 brain_seed_from_content.py --notebook-id <id> --topic <topic> --track tech

What it writes to brain.db:
  - entity type=learning  (one per topic researched)
  - facts: key_insight, pattern, tool_mentioned, lesson, source_notebook
  - links: learning → concept/tool entities (creates them if missing)

This is how Varys learns from his own research instead of discarding it.
"""

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from varys_brain import get_brain_db, upsert_entity, write_fact, write_link, find_entity
from varys_log import klog, klog_error

NLM         = "/home/oye/.local/bin/nlm"
NLM_PROFILE = os.environ.get("NLM_PROFILE", "work")

# Notebooks that are high-value for Varys's self-improvement as an agent.
# These get seeded automatically when this script is run standalone (daily cron).
PRIORITY_NOTEBOOKS = {
    "1ba69f8c-06cd-427d-bac8-d0f6ca855961": ("The harness I built so I never write the same code twice", "tech"),
    "bd172268-0000-0000-0000-000000000000": ("How I built a Notion-backed memory system for my AI agent", "tech"),
    "d9865250-0000-0000-0000-000000000000": ("I built a Slack bot that runs my entire dev workflow", "tech"),
    "12cd1f10-0000-0000-0000-000000000000": ("Why my Claude agent has hooks that block it from doing bad things", "tech"),
    "47e23b38-0000-0000-0000-000000000000": ("The self-healing observer that fixes my cron jobs at 3am", "tech"),
    "ff59f78a-0000-0000-0000-000000000000": ("Building a content scheduler that actually knows what to post", "tech"),
    "dcadddcd-0000-0000-0000-000000000000": ("The one hook that saves me from AI hallucinations every day", "tech"),
}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_nlm(args: list, timeout: int = 120) -> tuple[bool, str]:
    try:
        r = subprocess.run([NLM] + args, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout.strip() or r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def query_notebook_for_brain(nb_id: str, topic: str) -> dict:
    """Query NLM notebook with structured extraction prompt. Returns parsed dict."""
    query = (
        f"For the topic '{topic}', extract the following in JSON format:\n"
        f"1. key_insights: list of 5 specific, concrete facts or principles (each max 20 words)\n"
        f"2. patterns: list of 3 reusable architectural or behavioral patterns discovered\n"
        f"3. tools_mentioned: list of specific tools, libraries, or systems referenced\n"
        f"4. lessons_learned: list of 3 lessons that should change how Varys builds agents\n"
        f"5. one_line_summary: single sentence summarising the most important takeaway\n\n"
        f"Output ONLY valid JSON with these exact keys. No explanation."
    )
    ok, out = run_nlm(["notebook", "query", nb_id, query, "--profile", NLM_PROFILE], timeout=120)
    if not ok:
        return {}
    try:
        # NLM wraps answer in {"value": {"answer": "..."}}
        data = json.loads(out)
        answer = data.get("value", {}).get("answer", out)
    except Exception:
        answer = out

    # Extract JSON from the answer text
    try:
        start = answer.find("{")
        end   = answer.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(answer[start:end])
    except Exception:
        pass

    # Fallback: ask Claude to parse it
    try:
        parse_prompt = (
            f"Extract JSON from this text with keys: key_insights (list), patterns (list), "
            f"tools_mentioned (list), lessons_learned (list), one_line_summary (str).\n\n"
            f"Text:\n{answer[:2000]}\n\nOutput ONLY the JSON object."
        )
        r = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", parse_prompt],
            capture_output=True, text=True, timeout=60,
        )
        raw = r.stdout.strip()
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except Exception:
        pass

    return {}


def seed_from_nlm_insights(topic: str, track: str, nb_id: str,
                            nlm_insights: str, session_id: str = "") -> bool:
    """
    Called by content-scheduler after each track run.
    Parses raw nlm_insights text (no NLM query needed — insights already fetched).
    Writes learning entity + facts to brain.db.
    """
    if not nlm_insights or len(nlm_insights) < 100:
        return False

    # Parse insights into structured form via Claude
    parse_prompt = (
        f"Extract structured knowledge from this research about '{topic}' (track: {track}).\n"
        f"Output ONLY valid JSON with these keys:\n"
        f"  key_insights: list of 5 specific facts/principles (max 20 words each)\n"
        f"  patterns: list of 3 reusable patterns discovered\n"
        f"  tools_mentioned: list of tools/libraries/systems named\n"
        f"  lessons_learned: list of 3 lessons relevant to building better AI agents or content\n"
        f"  one_line_summary: single sentence, the most important takeaway\n\n"
        f"Research text:\n{nlm_insights[:2500]}\n\nJSON only."
    )
    try:
        r = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print", "-p", parse_prompt],
            capture_output=True, text=True, timeout=60,
        )
        raw = r.stdout.strip()
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        structured = json.loads(raw[start:end]) if start >= 0 and end > start else {}
    except Exception as e:
        print(f"[brain_seed] Parse failed: {e}")
        return False

    if not structured:
        return False

    ok = _write_to_brain(topic, track, nb_id, structured, session_id, source="content_pipeline")
    if ok:
        # Application Agent: what should Varys build given what he just learned?
        try:
            import threading
            threading.Thread(
                target=_run_application_agent, daemon=True
            ).start()
        except Exception as e:
            print(f"[brain_seed] apply-learnings thread failed (non-fatal): {e}")
    return ok


def seed_from_notebook(nb_id: str, topic: str, track: str,
                        session_id: str = "") -> bool:
    """
    Called standalone or from cron. Queries NLM notebook directly.
    Used to seed priority notebooks that already have research.
    """
    print(f"[brain_seed] Querying NLM notebook {nb_id[:8]} for '{topic}'")
    structured = query_notebook_for_brain(nb_id, topic)
    if not structured:
        print(f"[brain_seed] No structured data from notebook {nb_id[:8]}")
        return False
    return _write_to_brain(topic, track, nb_id, structured, session_id, source="nlm_notebook")


def _write_to_brain(topic: str, track: str, nb_id: str,
                     structured: dict, session_id: str, source: str) -> bool:
    """Write structured knowledge into brain.db."""
    db = get_brain_db()
    now = _now()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Entity: the learning itself
    entity_id   = f"learning-{nb_id[:8]}-{today}"
    entity_name = f"[{track}] {topic}"
    upsert_entity(db, entity_id, "learning", entity_name)

    # Core facts
    summary = structured.get("one_line_summary", "")
    if summary:
        write_fact(db, f"{entity_id}-summary", entity_id,
                   "one_line_summary", object_val=summary,
                   source=source, session_id=session_id)

    write_fact(db, f"{entity_id}-nb", entity_id,
               "source_notebook", object_val=nb_id,
               source=source, session_id=session_id)

    write_fact(db, f"{entity_id}-track", entity_id,
               "track", object_val=track,
               source=source, session_id=session_id)

    write_fact(db, f"{entity_id}-date", entity_id,
               "researched_on", object_val=today,
               source=source, session_id=session_id)

    # Key insights
    for i, insight in enumerate(structured.get("key_insights", [])[:5]):
        write_fact(db, f"{entity_id}-insight-{i}", entity_id,
                   "key_insight", object_val=insight,
                   source=source, session_id=session_id)

    # Patterns
    for i, pattern in enumerate(structured.get("patterns", [])[:3]):
        write_fact(db, f"{entity_id}-pattern-{i}", entity_id,
                   "pattern", object_val=pattern,
                   source=source, session_id=session_id)

    # Lessons learned
    for i, lesson in enumerate(structured.get("lessons_learned", [])[:3]):
        write_fact(db, f"{entity_id}-lesson-{i}", entity_id,
                   "lesson_learned", object_val=lesson,
                   source=source, session_id=session_id)

    # Tools mentioned → create concept entities + link
    for tool in structured.get("tools_mentioned", [])[:8]:
        tool_clean  = tool.strip().lower()[:50]
        tool_eid    = f"concept-{tool_clean.replace(' ', '-')}"
        upsert_entity(db, tool_eid, "concept", tool)
        link_id = f"link-{entity_id}-{tool_eid}"
        write_link(db, entity_id, tool_eid, "mentions_tool")

    db.commit()
    db.close()

    insights_count = len(structured.get("key_insights", []))
    tools_count    = len(structured.get("tools_mentioned", []))
    print(f"[brain_seed] ✅ Seeded '{topic}' → brain.db "
          f"({insights_count} insights, {tools_count} tools, source={source})")

    klog("brain_seeded", component="brain_seed_from_content",
         topic=topic, track=track, notebook=nb_id[:8],
         insights=insights_count, tools=tools_count, source=source)
    return True


def seed_priority_notebooks():
    """Seed all priority agentic/harness notebooks into brain.db. Run daily."""
    db = get_brain_db()
    # Get full notebook list to resolve IDs (PRIORITY_NOTEBOOKS has placeholder UUIDs)
    ok, out = run_nlm(["notebook", "list", "--profile", NLM_PROFILE])
    if not ok:
        print(f"[brain_seed] Could not list notebooks: {out[:100]}")
        return

    try:
        all_notebooks = {nb["id"]: nb for nb in json.loads(out)}
    except Exception:
        print(f"[brain_seed] Could not parse notebook list")
        return

    # Match by title substring for priority notebooks
    priority_titles = {
        "harness i built so i never write": ("The harness I built so I never write the same code twice", "tech"),
        "notion-backed memory system":      ("How I built a Notion-backed memory system for my AI agent", "tech"),
        "slack bot that runs my entire":    ("I built a Slack bot that runs my entire dev workflow", "tech"),
        "hooks that block it from doing":   ("Why my Claude agent has hooks that block it from doing bad things", "tech"),
        "self-healing observer":            ("The self-healing observer that fixes my cron jobs at 3am", "tech"),
        "content scheduler that actually":  ("Building a content scheduler that actually knows what to post", "tech"),
        "one hook that saves me from ai":   ("The one hook that saves me from AI hallucinations every day", "tech"),
        "parallel agents":                  ("How I use parallel agents to do 6 hours of work in 45 minutes", "tech"),
        "notion-backed memory":             ("How I built a Notion-backed memory system for my AI agent", "tech"),
    }

    seeded = 0
    for nb_id, nb in all_notebooks.items():
        title_lower = nb.get("title", "").lower()
        for match_key, (full_title, track) in priority_titles.items():
            if match_key in title_lower and nb.get("source_count", 0) > 0:
                # Check if already seeded today
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                entity_id = f"learning-{nb_id[:8]}-{today}"
                existing = db.execute(
                    "SELECT id FROM entities WHERE id=?", (entity_id,)
                ).fetchone()
                if existing:
                    print(f"[brain_seed] Already seeded today: {full_title[:50]}")
                    break
                db.close()
                ok = seed_from_notebook(nb_id, full_title, track)
                db = get_brain_db()
                if ok:
                    seeded += 1
                break

    db.close()
    print(f"[brain_seed] Priority seed complete: {seeded} notebooks seeded into brain.db")


def _run_application_agent():
    """Fire varys-apply-learnings in the same process environment. Non-blocking (called in thread)."""
    try:
        apply_mod_path = Path(__file__).parent / "varys-apply-learnings.py"
        if apply_mod_path.exists():
            subprocess.run(
                ["python3", str(apply_mod_path), "--days", "1"],
                timeout=180,
            )
        else:
            # Fallback: import and call directly
            sys.path.insert(0, str(Path(__file__).parent))
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "varys_apply_learnings", apply_mod_path
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.run(days=1)
    except Exception as e:
        print(f"[brain_seed] apply-learnings thread error (non-fatal): {e}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Seed brain.db from NLM notebooks")
    p.add_argument("--notebook-id", help="Specific notebook ID to seed")
    p.add_argument("--topic",       help="Topic for the notebook")
    p.add_argument("--track",       default="tech", choices=["fitness","tech","vlog","painting"])
    p.add_argument("--all-priority", action="store_true",
                   help="Seed all priority agentic/harness notebooks")
    args = p.parse_args()

    if args.all_priority:
        seed_priority_notebooks()
    elif args.notebook_id and args.topic:
        ok = seed_from_notebook(args.notebook_id, args.topic, args.track)
        sys.exit(0 if ok else 1)
    else:
        print("Usage: --all-priority  OR  --notebook-id <id> --topic <topic>")
        sys.exit(1)
