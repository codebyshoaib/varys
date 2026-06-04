# Kamil Brain Redesign — Design Spec
**Date:** 2026-06-04  
**Status:** Approved  
**Owner:** Kamal

---

## Problem

The Kamil harness has all the data but no connective tissue. Failures like "message Mahnoor" — where the answer exists in Notion but the agent returns "I don't know" — are retrieval/routing failures, not missing-data problems. Two People DBs exist with no merge. Write-backs after interactions are inconsistent or missing. The retrieval chain (Notion → NLM → web) exists only in docs and is easy to skip.

**Goal:** Make the agent behave like a human teammate — read context before replying, remember history per person, escalate retrieval automatically, and always write back after every interaction.

---

## Architecture Overview

Three layers:

1. **SQLite speed layer** — graph-ready entities + relations + interaction log. The agent's fast working memory. Canonical for read performance.
2. **`kamil_context.py`** — single source of truth for all retrieval and write rules. All scripts import it. Docs defer to it.
3. **Notion** — human-readable mirror. Receives distilled summaries via sync loop. Canonical for aliases (Notion edits flow down to SQLite).

---

## Section 1: SQLite Schema

```sql
-- Schema version marker
CREATE TABLE schema_meta (version INTEGER NOT NULL);
INSERT INTO schema_meta VALUES (1);

-- Core entities
CREATE TABLE entities (
  id          TEXT PRIMARY KEY,         -- uuid
  type        TEXT NOT NULL,            -- person | pr | thread | ticket | notebook | job
  external_id TEXT,                     -- slack_id, notion_page_id, gh_pr_number, etc.
  name        TEXT,
  meta        JSON                      -- includes aliases: ["Mahnoor","@m.noor"]
);
CREATE INDEX idx_entities_type_extid ON entities(type, external_id);

-- Relations (store once, query both directions)
CREATE TABLE relations (
  id         TEXT PRIMARY KEY,
  from_id    TEXT NOT NULL REFERENCES entities(id),
  to_id      TEXT NOT NULL REFERENCES entities(id),
  rel_type   TEXT NOT NULL,             -- reviewed | mentioned_in | assigned_to | interacted_with | linked_to
  meta       JSON,
  created_at INTEGER NOT NULL
);
CREATE INDEX idx_relations_from ON relations(from_id, rel_type);
CREATE INDEX idx_relations_to   ON relations(to_id,   rel_type);

-- Interaction log
CREATE TABLE interactions (
  id           TEXT PRIMARY KEY,        -- sha256(source + external_id) — dedup key
  person_id    TEXT NOT NULL REFERENCES entities(id),
  source       TEXT NOT NULL,           -- slack | claude_session
  external_id  TEXT NOT NULL,           -- slack: "{channel}_{ts}", session: "{session_id}_{turn_index}"
  raw          TEXT,
  summary      TEXT,                    -- agent-distilled at interaction time (caller's responsibility)
  open_items   TEXT,                    -- JSON list; promote to own table if cross-person queries needed
  synced_notion INTEGER DEFAULT 0,      -- 0=pending, 1=synced, -1=dead-letter
  sync_retries  INTEGER DEFAULT 0,      -- capped at 5; dead-letter after cap
  created_at   INTEGER NOT NULL
);
CREATE INDEX idx_interactions_person ON interactions(person_id, created_at);

-- NLM registry cache (mirror of Notion NLM Registry)
CREATE TABLE nlm_notebooks (
  id           TEXT PRIMARY KEY,        -- notebook uuid
  alias        TEXT,
  domain       TEXT,
  keywords     TEXT,                    -- space-separated for LIKE matching
  last_queried INTEGER
);
```

### Notes
- `open_items` is JSON in the interaction row for v1. If "show me all open items across people" becomes a real query, promote to `open_items(id, person_id, interaction_id, text, status, created_at)` as an additive change.
- `relations` uses from_id/to_id — `lookup_context()` queries both directions; never double-inserts reverse edges.
- `external_id` stability: Slack = `{channel}_{message_ts}` (immutable). Claude session = `{session_id}_{turn_index}` where turn_index is monotonic-within-session and session_id is globally unique. Turn_index must never reset mid-session.

---

## Section 2: `kamil_context.py`

**Canonical rule:** All retrieval and write logic lives here. `notion.md` and `slack.md` each contain one line: *"Retrieval and write rules are defined in `kamil_context.py` — do not re-specify here."*

### `resolve_person(name_or_id) → PersonRecord`

```
1. SQLite: match entities WHERE type='person' AND (
     name = ? (exact, case-insensitive)
     OR meta->>aliases LIKE ?
     OR external_id = ?
   )
2. If 0 hits → query People Intelligence (Notion MCP) → upsert to SQLite → return
3. If 1 hit → return PersonRecord
4. If 2+ hits:
   - Score by: exact name match > alias match > partial match
   - If top score is unique → return it, log PersonAmbiguous warning with all matches
   - If top score ties → raise PersonAmbiguous({candidates}) — caller decides
5. If 0 hits after Notion → raise PersonNotFound(name_or_id)
```

`PersonRecord`: `{entity_id, slack_id, notion_page_id, name, aliases, display_name}`

**Alias canonical direction:** Notion is canonical (edited by hand). SQLite mirrors on sync. When `record_interaction()` syncs, it also pulls aliases from Notion and updates `entities.meta`.

### `lookup_context(question, person_id=None) → ContextResult`

```
Route log: [] — appended at every step, returned in ContextResult.source_chain

1. Freshness gate:
   - Keywords: price, news, status, CI, job posting, PR, today, current, latest
   - If match → log "freshness:web" → skip to step 4
   - Log every gate decision (fired/not fired) with matched keywords or "no match"

2. Notion fetch:
   - Select DB by topic: people question → People Intelligence; PR/work → My PRs / Harness; 
     inbox → Slack Inbox; content → Content Calendar
   - Query via MCP → assess answer quality (empty / thin / clear)
   - If clear → return with source_chain=["notion:<db>"]

3. NLM check (if Notion thin):
   - Keyword-match question against nlm_notebooks.keywords
   - If match → query NLM notebook → assess quality
   - If clear → return with source_chain=["notion:<db>", "nlm:<alias>"]

4. Web search (if NLM thin/miss OR freshness gate fired):
   - Run web search → return with full source_chain
   - e.g. ["notion:people_intelligence", "nlm:fitness", "web"]

5. If all sources thin → return ContextResult(answer=None, source_chain=[...], needs_escalation=True)
   Never ask for permission on steps 2–4.
```

`ContextResult`: `{answer, source_chain: List[str], needs_escalation: bool}`

### `record_interaction(person_id, source, external_id, raw, summary, open_items) → str`

**Caller's responsibility:** `summary` and `open_items` must be agent-distilled before calling. Do not pass raw text into `summary`. The Slack listener and Stop hook both generate these before the call.

```
1. id = sha256(source + ":" + external_id)
2. If id already in interactions → return id (dedup, silent)
3. INSERT into interactions (synced_notion=0, sync_retries=0)
4. Return id

Sync loop (background, runs every ~60s):
  SELECT * FROM interactions WHERE synced_notion=0 AND sync_retries < 5
  For each row:
    - Append summary to People Intelligence page (Notion MCP)
    - Update Last Interaction date on person's Notion page
    - Upsert raw to Slack Inbox with person relation (if source=slack)
    - On success: SET synced_notion=1
    - On failure: INCREMENT sync_retries; if sync_retries >= 5: SET synced_notion=-1 (dead-letter), log error

Heartbeat: sync loop writes last_sync_at timestamp to schema_meta or a health row.
Dead-letter rows: logged to Observability DB + Axiom with person_id and failure reason.
```

---

## Section 3: DB Merge + Wiring

### Merging People DBs

**Source:** `Team People / focus` (`bbf6ade2...`)  
**Target:** `People Intelligence` (`c976d58e...`) — canonical going forward

**Merge procedure:**
1. **Dry run first.** `merge-people-dbs.py --dry-run` produces a match report:
   - Exact matches (name == name)
   - Fuzzy matches (Levenshtein distance ≤ 2, or alias hit) — flagged for human review
   - New records (in source only)
   - Output as Markdown table. Kamil approves before any write.
2. **After approval:** run `merge-people-dbs.py --write` — merges fields (role, current focus) and creates new pages.
3. **Grep for all references:** `grep -r "bbf6ade2" .` across entire repo. Rewire every hit to `c976d58e`. Confirm zero remaining references.
4. **Keep old DB live** (unreferenced) for one week. Confirm People Intelligence receives all writes during that window.
5. **Then archive:** rename to `[ARCHIVED] Team People` in Notion.

**Schema additions to People Intelligence:**
| Field | Type | Notes |
|---|---|---|
| `Slack ID` | Text | Required for `resolve_person()` |
| `Aliases` | Text | Comma-separated; Notion-canonical, synced to SQLite |
| `Last Interaction` | Date | Written by sync loop (not a Notion rollup — SQLite is the source) |
| `Open Items` | Text | Distilled summary of unresolved items; written by sync loop |

### Trigger Wiring

**`kamil-slack-listener.py`** — after every reply sent:
```python
summary, open_items = agent_distill(thread)  # agent generates before calling
record_interaction(
    person_id=resolve_person(sender_name).entity_id,
    source='slack',
    external_id=f"{channel}_{message_ts}",
    raw=thread_text,
    summary=summary,
    open_items=open_items
)
```

**`stop.py` Stop hook** — at session end, for each qualifying interaction:
```python
# Relevance filter — only log if:
# - a decision was made
# - a named person was involved
# - an open item was created or closed
# - work was completed
# Skip pure back-and-forth turns
if is_meaningful(turn):
    record_interaction(
        person_id=...,
        source='claude_session',
        external_id=f"{session_id}_{turn_index}",  # turn_index monotonic, never resets
        raw=turn_text,
        summary=agent_distill(turn),
        open_items=extract_open_items(turn)
    )
```

### Docs Update

`notion.md` retrieval/write section → replace with:
> *Retrieval and write rules are defined in `.claude/hooks/kamil_context.py` — do not re-specify here.*

`slack.md` lookup/send section → replace with:
> *Person lookup and interaction write-back: see `.claude/hooks/kamil_context.py` — do not re-specify here.*

---

## What This Fixes

| Failure | Root cause | Fix |
|---|---|---|
| "Message Mahnoor" → "I don't know" | No routing rule; two DBs not merged | `resolve_person()` + merged DB |
| Agent replies without reading thread | No enforced read-first step | Slack listener reads thread before reply; `lookup_context()` fetches person profile first |
| No memory of past interactions | No write-back; no per-person history | `record_interaction()` mandatory after every reply; SQLite speed layer |
| Stops to ask "should I use NLM or web?" | No escalation rule in code | `lookup_context()` escalation chain; fully automatic |
| Retrieval rules drift between scripts | Rules in docs, not code | `kamil_context.py` canonical; docs point to it |

---

## File Locations

```
.claude/hooks/kamil_context.py          — new: core module (resolve_person, lookup_context, record_interaction)
.claude/hooks/merge-people-dbs.py       — new: one-time migration script
.claude/hooks/kamil-slack-listener.py   — modified: wire record_interaction
.claude/hooks/stop.py                   — modified: wire record_interaction with relevance filter
.claude/rules/notion.md                 — modified: one-line defer to kamil_context.py
.claude/rules/slack.md                  — modified: one-line defer to kamil_context.py
~/.kamil-harness/harness.db             — modified: new tables added (migration from schema v_current to v1)
```
