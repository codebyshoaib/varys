# NLM → Notion Tracking Fix — Implementation Plan

**Goal:** Every NLM action (notebook creation, research, artifact generation, artifact result) is
fully tracked in Notion so Kamal can audit "what did NLM produce today?" without opening
NotebookLM or reading Slack.

**Root problem:** `content-scheduler.py` creates/uses NLM notebooks and triggers artifacts, but
only saves the `nb_id` to Notion. Artifact outcomes (success/fail/pending), research insights,
and cross-links between Content Calendar and Content Log are all missing.

**No new files needed** — all fixes are surgical edits to `content-scheduler.py`.

---

## Schema changes needed first

### Content Log DB — add 3 properties
| Property | Type | Values |
|---|---|---|
| `NLMArtifacts` | text | JSON: `{"slide_deck":"completed","infographic":"failed","mind_map":"pending"}` |
| `NLMInsights` | text | First 1500 chars of `nlm_query_for_content()` result |
| `ContentCalendarPageID` | text | Notion page ID of the source Content Calendar entry |

### Content Calendar DB — add 1 property
| Property | Type | Purpose |
|---|---|---|
| `ContentLogPageID` | text | Backlink to the Content Log entry created for this topic |

---

## Task 1: Add 4 properties to Notion DBs via MCP

- [ ] **Step 1: Add `NLMArtifacts` (text) to Content Log DB**
- [ ] **Step 2: Add `NLMInsights` (text) to Content Log DB**
- [ ] **Step 3: Add `ContentCalendarPageID` (text) to Content Log DB**
- [ ] **Step 4: Add `ContentLogPageID` (text) to Content Calendar DB**
- [ ] **Step 5: Verify all 4 properties appear in both DB schemas**

Use `mcp__claude_ai_Notion__notion-update-data-source` for each.

---

## Task 2: Fix `log_to_content_log()` — add 3 new fields + return page ID

**File:** `.claude/hooks/content-scheduler.py`

**Current signature:**
```python
def log_to_content_log(topic, track, score, reason, caption, hashtags,
                        nb_id, li_post_id, vlog_angle, platforms, status="Generated"):
```

**New signature:**
```python
def log_to_content_log(topic, track, score, reason, caption, hashtags,
                        nb_id, li_post_id, vlog_angle, platforms, status="Generated",
                        nlm_insights="", nlm_artifacts=None,
                        calendar_page_id="") -> str:
    """Returns the created Content Log page ID."""
```

**Changes:**
- [ ] **Step 1: Add `nlm_insights`, `nlm_artifacts`, `calendar_page_id` params**
- [ ] **Step 2: Write `NLMInsights` to Notion (truncate to 1800 chars)**
- [ ] **Step 3: Write `NLMArtifacts` as JSON string (e.g. `{"slide_deck":"triggered","infographic":"triggered"}`)**
- [ ] **Step 4: Write `ContentCalendarPageID` to Notion**
- [ ] **Step 5: Return the created page's ID from `notion_create_page()`** — need to read the response `id` field

For Step 5, update `notion_create_page()` to return the page ID:
```python
def notion_create_page(db_id: str, properties: dict) -> str:
    ...
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
        return data.get("id", "")
```

- [ ] **Step 6: Commit**

---

## Task 3: Fix `nlm_poll_and_send()` — write artifact result back to Notion

**File:** `.claude/hooks/content-scheduler.py`

**Current:** Posts to Slack only. Never updates Notion.

**New:** After artifact completes or fails, update the Content Log entry's `NLMArtifacts` field.

- [ ] **Step 1: Add `log_page_id: str` param to `nlm_poll_and_send()`**
- [ ] **Step 2: On artifact `completed` — call `notion_update_page(log_page_id, {"NLMArtifacts": ...})`**
  - Merge the new status into the existing JSON string (read current value, parse, update key, write back)
- [ ] **Step 3: On artifact `failed` — same update with `"failed"` status**
- [ ] **Step 4: On timeout — update with `"timeout"` status**
- [ ] **Step 5: Commit**

Helper to merge artifact status:
```python
def _update_artifact_status(log_page_id: str, artifact_type: str, status: str):
    """Read existing NLMArtifacts JSON from Notion, update one key, write back."""
    # Fetch current value, parse JSON, update, write back
    # Use notion_get_page_prop() helper or just overwrite with known state
```

Since we control what we write, the simplest approach: pass the full `artifacts_state` dict
into the thread at launch time, mutate it, write the whole thing back.

---

## Task 4: Wire backlink — Content Calendar → Content Log

**File:** `.claude/hooks/content-scheduler.py`

In `run_fitness_or_tech()` and `run_vlog()`:

- [ ] **Step 1: Capture `log_page_id` returned by `log_to_content_log()`**
- [ ] **Step 2: Call `notion_update_page(calendar_page_id, {"ContentLogPageID": {"rich_text": [{"text": {"content": log_page_id}}]}})`**
- [ ] **Step 3: Pass `log_page_id` into all 3 `nlm_poll_and_send()` thread calls**
- [ ] **Step 4: Pass `calendar_page_id` into `log_to_content_log()` as `calendar_page_id=page_id`**
- [ ] **Step 5: Commit**

---

## Task 5: Store NLM insights in Notion page body

**File:** `.claude/hooks/content-scheduler.py`

Currently `nlm_insights` is only used to generate the caption. It's never persisted.

- [ ] **Step 1: After `log_to_content_log()` returns `log_page_id`, write `nlm_insights` as page body blocks**

Use `notion-update-page` or a direct API call to append block content:
```python
def _write_page_body(page_id: str, content: str):
    """Write text content as paragraph blocks to a Notion page."""
    token = _notion_token()
    body = json.dumps({
        "children": [{"object": "block", "type": "paragraph",
                      "paragraph": {"rich_text": [{"type": "text",
                                                   "text": {"content": content[:1800]}}]}}]
    }).encode()
    req = urllib.request.Request(
        f"https://api.notion.com/v1/blocks/{page_id}/children",
        data=body, method="PATCH",
        headers={"Authorization": f"Bearer {token}",
                 "Notion-Version": "2022-06-28",
                 "Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=10).read()
```

- [ ] **Step 2: Call `_write_page_body(log_page_id, nlm_insights)` after log entry created**
- [ ] **Step 3: Commit**

---

## Task 6: Smoke test

- [ ] **Step 1: Run `pick_topic("tech")` — verify it returns a topic**
- [ ] **Step 2: Manually call `log_to_content_log()` with test data — verify row created in Notion with all 3 new fields**
- [ ] **Step 3: Verify `notion_create_page()` now returns a page ID (not empty string)**
- [ ] **Step 4: Verify backlink written to Content Calendar page**
- [ ] **Step 5: Final commit + log entry**

---

## What This Fixes

After this plan is complete:

| Before | After |
|---|---|
| NLM artifacts trigger silently | Each artifact has status: triggered → completed/failed/timeout |
| NLM research insights lost after caption | Insights stored in Content Log page body |
| Content Calendar and Content Log are disconnected | Bidirectional link: Calendar page has `ContentLogPageID`, Log has `ContentCalendarPageID` |
| Can't audit "what did NLM do today?" | Filter Content Log by date, see full NLM pipeline outcome per topic |

