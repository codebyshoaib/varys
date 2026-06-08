---
title: MemPalace - How It Works for Claude's Memory
description: Complete explanation of MemPalace architecture and integration
---

# MemPalace: Enhanced Memory for Claude

## The Problem MemPalace Solves

**Claude's Default Limitation**: Claude has no memory between sessions. Every new conversation:
- Loses all prior context
- Forgets what projects you're working on
- Forgets decisions, patterns, people relationships
- Requires you to re-explain the same context repeatedly

**Example**:
```
Session 1: You tell Claude about taleemabad-core architecture (10 min explanation)
Session 2: You ask about a bug in taleemabad-core
           Claude: "I don't know this codebase. Tell me about it"
           (Lose 10 minutes re-explaining)
```

**MemPalace Solution**: Persistent, searchable memory that Claude can access across sessions.

---

## How MemPalace Works

### Architecture Overview

```
┌─────────────────────────────────────────┐
│         Your Vault (vault/)             │
│  - memory/ (19 files)                   │
│  - projects/ (5 projects)               │
│  - domains/ (5 life areas)              │
│  - logs/ (session logs)                 │
│  - plans/ (strategic plans)             │
└──────────────┬──────────────────────────┘
               │
               │ (post-tool-use.py hook)
               │ "Sync vault files to memory"
               │
               ↓
┌─────────────────────────────────────────┐
│      MemPalace Local Storage            │
│  (ChromaDB vector database)             │
│                                         │
│  ┌─ Wing: "workspace"                  │
│  │  └─ Room: "memory"                  │
│  │     └─ Drawer: 19 memory files      │
│  │                                     │
│  ├─ Wing: "taleemabad-core"            │
│  │  ├─ Room: "project"                 │
│  │  ├─ Room: "architecture"            │
│  │  └─ Room: "related"                 │
│  │                                     │
│  └─ Wing: "taleemabad"                 │
│     ├─ Room: "work-log"                │
│     ├─ Room: "incidents"               │
│     └─ Room: "contacts"                │
│                                         │
│  + Vector embeddings for semantic search
└──────────────┬──────────────────────────┘
               │
               │ (MCP tools)
               │ "Retrieve memory"
               │
               ↓
┌─────────────────────────────────────────┐
│         Claude in New Session           │
│                                         │
│ "I remember: You're working on         │
│  taleemabad-core (Django LMS).         │
│  Related: taleemabad-cms (frontend)    │
│  Last session: Fixed quiz feedback"    │
└─────────────────────────────────────────┘
```

---

## Key Concepts

### 1. **Wings** — High-Level Context
A "wing" is a major context area.

**Examples**:
- `workspace` — General personal-agent context
- `taleemabad-core` — Current project context
- `taleemabad-cms` — Frontend project context
- `taleemabad` — Work domain context

**Why**: Organizes memory so Claude can say "I need the taleemabad-core wing" without loading everything.

---

### 2. **Rooms** — Subcategories
Within each wing, rooms organize specific topics.

**Examples**:
- Wing: `taleemabad-core`, Room: `project` → Overview, tech stack
- Wing: `taleemabad-core`, Room: `architecture` → Design patterns, modules
- Wing: `taleemabad-core`, Room: `related` → Sibling projects (cms, auth)

**Why**: Allows searching "show me architecture context" without noise from work-logs or incidents.

---

### 3. **Drawers** — Individual Memories
Each drawer is a single memory file.

**Examples**:
- `workspace/memory/user_profile.md` → Who you are, your preferences
- `taleemabad-core/project/project.md` → Project overview
- `taleemabad/work-log/2026-05-04.md` → Today's work

**Why**: Fine-grained retrieval. Claude can pull exactly the memory it needs.

---

### 4. **Vector Embeddings** — Semantic Search
MemPalace converts text to vectors (embeddings) for intelligent search.

**How it works**:
```
User asks: "How do I fix quiz feedback bugs?"

MemPalace searches for:
  - "quiz feedback" (exact match)
  - Similar concepts: "AI feedback", "Celery tasks", "async feedback"
  
Returns: 
  - taleemabad-core/architecture/modules (Celery + feedback)
  - taleemabad-training-project (feedback system design)
  - work-log entries mentioning "feedback"
```

**Why**: Claude doesn't need you to remember the exact file names. Just describe what you need.

---

## How Integration Works in personal-agent-v2

### Step 1: You Edit a File (vault/)
```markdown
# vault/memory/user_profile.md
Senior Backend Engineer, 10 years Python/Django
```

### Step 2: post-tool-use.py Hook Fires
```python
# Automatically triggered after Write tool
[post-tool-use] Syncing vault file
  File: vault/memory/user_profile.md
  Wing: 'workspace' | Room: 'memory'
  Size: 2.5 KB

# MCP call to MemPalace (TODO):
# mempalace_upsert(
#   wing="workspace",
#   room="memory",
#   content="Senior Backend Engineer...",
#   filepath="vault/memory/user_profile.md"
# )
```

### Step 3: MemPalace Stores in Vector DB
```
MemPalace palace/chroma.sqlite3:
  ✓ Indexed: "Senior Backend Engineer"
  ✓ Indexed: "Python/Django expertise"
  ✓ Indexed: "Terminal-native"
  ✓ Created embeddings for semantic search
```

### Step 4: project-detect.py Loads on Session Start
```python
# Session starts in /your/project/path
[project-detect] Detected project: taleemabad-core
[project-detect] Loading context from MemPalace

# MCP calls (TODO):
# mempalace_activate_wing("taleemabad-core")
# related = mempalace_get_related_projects("taleemabad-core")
# recent_sessions = mempalace_get_last_sessions("taleemabad-core", count=3)

Claude is now aware:
  - Current project: taleemabad-core
  - Related projects: taleemabad-cms, taleemabad-auth
  - Last 3 sessions in this project
```

### Step 5: Claude Uses Memory Naturally
```
User: "What was the issue with quiz feedback we fixed last week?"

Claude uses MemPalace:
  mempalace_search("quiz feedback issue", wing="taleemabad-core")
  
Returns:
  - vault/logs/2026-04-28.md (mentions "fixed feedback async task")
  - vault/projects/taleemabad-core/architecture.md (Celery section)
  - vault/domains/taleemabad/work-log.md (incident notes)

Claude responds:
  "Based on your last session, you fixed the quiz feedback 
   Celery task timeout. The issue was... [pulls context]"
```

---

## The 29 MemPalace MCP Tools (Available)

MemPalace provides 29 MCP tools for memory operations:

### Read Operations
- `mempalace_search(query, wing?)` — Search by keyword/concept
- `mempalace_get_wing(wing)` — Load entire wing
- `mempalace_get_room(wing, room)` — Load specific room
- `mempalace_get_drawer(wing, room, drawer)` — Load single file

### Write Operations
- `mempalace_upsert(wing, room, content, filepath)` — Add/update memory
- `mempalace_archive(wing, room, drawer)` — Archive old memory
- `mempalace_link(wing1, wing2)` — Create relationship

### Context Operations
- `mempalace_get_related(wing)` — Related wings/projects
- `mempalace_get_last_sessions(wing, count)` — Recent session summaries
- `mempalace_get_context_summary(wing)` — Quick context snapshot

### Plus 19 more for advanced operations (entity extraction, knowledge graph, timestamps, etc.)

---

## What MemPalace Does NOT Do (Yet)

### ❌ Not Currently Implemented in Hooks
- [ ] Automatic MemPalace upsert in post-tool-use.py (MCP integration pending)
- [ ] Automatic context loading in project-detect.py (MCP integration pending)
- [ ] Automatic context display to Claude (needs Claude Code hook support)

### ⚠️ Still TODO
- [ ] Wire up MCP tool calls in hooks
- [ ] Test vector search quality
- [ ] Set up entity extraction for automatic relationship detection
- [ ] Configure knowledge graph for complex relationships

---

## Example: How It Solves Your Problems

### Problem 1: Lost Context Between Sessions

**Before (v1)**:
```
Session 1: 
  User: "I'm fixing a bug in quiz feedback"
  Claude: "Tell me about the codebase"
  (15 min explanation)

Session 2:
  User: "How did I fix that quiz bug?"
  Claude: "I don't have that context. Tell me again"
  (Lose 15 min)
```

**After (v2 with MemPalace)**:
```
Session 1:
  User: "I'm fixing a bug in quiz feedback"
  Claude: (pulls from taleemabad-core wing in MemPalace)
  Claude: "I see the quiz feedback system. Celery async, Django signals..."
  (Already has context)

Session 2:
  [project-detect] loads taleemabad-core context
  User: "How did I fix that quiz bug?"
  Claude: (searches MemPalace for "quiz feedback bug fix")
  Claude: "You fixed the Celery timeout... [pulls from work-log]"
  (Immediate answer)
```

---

### Problem 2: Inter-Project Context Loss

**Before (v1)**:
```
Session in taleemabad-core:
  Claude: "I don't know what taleemabad-cms is"
  (They're siblings, but no connections)

User has to explain: "cms uploads files via S3 presigned URLs"
  (context lost each session)
```

**After (v2 with MemPalace)**:
```
Session in taleemabad-core:
  [project-detect] Loads taleemabad-core + related projects

Claude automatically knows:
  - taleemabad-cms (frontend consumer)
  - taleemabad-auth (JWT provider)
  - Related: S3 presigned URL flow, async feedback

User: "The presigned URL endpoint is timing out"
Claude: "Ah, CMS is hitting core's presigned URL endpoint.
  Looking at your S3 config..."
  (Context flows naturally)
```

---

### Problem 3: Claude Goes Off-Scope During Coding

**Before (v1)**:
```
User: "Fix the quiz feedback bug"
Claude: (No memory of scope)
Claude: (Also refactors 3 unrelated modules)
Claude: (Updates 10 files when only 2 needed)
Claude: (Adds premature abstractions)
```

**After (v2 with MemPalace + Karpathy-skills)**:
```
User: "Fix the quiz feedback bug"
MemPalace loads context:
  - workspace/memory/feedback_coding.md (surgical changes rule)
  - taleemabad-core/architecture.md (minimal scope)

Claude sees:
  "Claude must follow karpathy-skills discipline"
  "Only touch: apps/feedback/, not others"
  
Claude fixes only what's necessary
Claude: "Fixed Celery timeout in apps/feedback/tasks.py"
(No scope creep)
```

---

## Integration Timeline

### Current Status (2026-05-04)
- ✅ MemPalace installed
- ✅ MemPalace initialized  
- ✅ MCP server configured
- ✅ Hooks have MCP placeholders
- ⏳ **TODO**: Wire up actual MCP tool calls

### Next Phase (When Ready)
1. Test mempalace CLI to verify indexing works
2. Implement MCP upsert in post-tool-use.py
3. Implement MCP wing loading in project-detect.py
4. Test semantic search quality
5. Monitor and improve based on real usage

---

## How to Test MemPalace Now

### Test 1: Index the Vault
```bash
cd /your/project/path

# Mine (index) the vault
mempalace --palace mempalace mine vault --yes

# Verify
mempalace --palace mempalace status
```

### Test 2: Search
```bash
# Search for concept
mempalace --palace mempalace search "taleemabad training"

# Expected output:
# - vault/projects/taleemabad-core/project.md
# - vault/memory/taleemabad_training_project.md
# - vault/domains/taleemabad/work-log.md
```

### Test 3: Get Wing
```bash
# Load entire "taleemabad-core" wing
mempalace --palace mempalace get-wing taleemabad-core

# Expected: All files for that project
```

---

## Key Differences: MemPalace vs Other Approaches

| Approach | Storage | Retrieval | Cost | Setup |
|----------|---------|-----------|------|-------|
| **MemPalace** (v2) | Local ChromaDB | Semantic search (vectors) | Free | 1 pip install |
| Pinecone | Cloud | Semantic search | $$$ | API key |
| Weaviate | Local/Cloud | Vector DB | $ | Docker |
| Simple File Search | Disk | Keyword grep | Free | None |
| Reddit/Context | None | Lost | Free | Lose context |

**MemPalace**: Best balance of free + local + semantic search

---

## What Claude Can Do With MemPalace Memory

### Problem-Solving
- "I remember you fixed a similar bug last week" (search work-log)
- "Based on past decisions..." (pull from decisions.md)
- "The architecture pattern you use..." (pull from architecture.md)

### Context Awareness
- "You're in taleemabad-core, related projects are..." (auto-loaded)
- "Your last 3 sessions on this project..." (from session summaries)
- "Key people on this project..." (from contacts)

### Continuous Learning
- "You prefer surgical changes, so I'll only touch..."
- "You always test migrations before deploy"
- "These projects share the S3 bucket, so..."

### Knowledge Reuse
- "You've documented this pattern in other projects"
- "The portfolio auto-publish workflow is..."
- "Anam Masood usually needs..."

---

## Why This Solves "Claude Forgets"

### Root Cause
Claude's 128K context window is for ONE session only.
New session = fresh start = no memory.

### Solution
MemPalace (ChromaDB) is persistent across sessions.
Each new session: Load relevant context from MemPalace before working.

### Result
- Claude starts each session with your context already loaded
- No need to re-explain projects, decisions, patterns
- Relationships between projects surface automatically
- Work history informs current decisions

---

## Next: Make It Work

### For Developers (You)
1. **Test MemPalace CLI** → Verify indexing works
2. **Review MCP placeholders** → See where integration happens
3. **Test semantic search** → Does `mempalace search "quiz"` return right files?
4. **Plan MCP implementation** → Wire up actual tool calls

### For Claude (Future)
Once MCP is wired:
- Automatically activate project wing on session start
- Automatically pull recent session summaries
- Automatically suggest related projects/memory
- Naturally reference past decisions and patterns

---

## Summary

**MemPalace** is a **local, semantic memory system** that:

1. **Stores** all your vault files in a vector database (ChromaDB)
2. **Indexes** them for fast semantic search (not just keyword matching)
3. **Organizes** them into Wings (projects) → Rooms (categories) → Drawers (files)
4. **Serves** them to Claude via 29 MCP tools across sessions

**Result**: Claude remembers context across sessions and can intelligently retrieve relevant memory when needed.

**Status**: Installed & initialized. MCP integration TODO.

