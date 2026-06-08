---
title: MemPalace Integration Flows
description: Visual diagrams of how MemPalace integrates with personal-agent-v2
---

# MemPalace Integration Flows

## Flow 1: Writing Context (Sync to MemPalace)

```
You edit a file in vault/
        ↓
        │
        └─→ Write tool creates: vault/memory/user_profile.md
            
            new content: "Senior Backend Engineer, 10 years Python"
            ↓
        post-tool-use.py HOOK fires
            ↓
        Parses file path:
            vault/memory/user_profile.md
            ↓
        Derives wing+room:
            Wing: "workspace"
            Room: "memory"
            ↓
        (TODO: Call MemPalace MCP)
        mempalace_upsert(
          wing="workspace",
          room="memory",
          content="Senior Backend Engineer...",
          filepath="vault/memory/user_profile.md"
        )
            ↓
        MemPalace stores in ChromaDB:
            ✓ Text content indexed
            ✓ Embeddings created
            ✓ Stored in workspace/memory drawer
            ↓
        Next session:
            Claude can search: "What's my background?"
            MemPalace returns: workspace/memory/user_profile
            Claude: "You're a Senior Backend Engineer, 10 years Python..."
```

---

## Flow 2: Loading Project Context (Auto on Session Start)

```
New session starts
        ↓
        │
User working in: /your/project/path
        ↓
project-detect.py HOOK fires
        ↓
Resolves working directory:
    /your/project/path
    ↓
Matches to known project:
    Project name: "taleemabad-core"
    ↓
(TODO: Call MemPalace MCP)
mempalace_activate_wing("taleemabad-core")
        ↓
MemPalace loads entire wing:
    ✓ taleemabad-core/project/project.md
    ✓ taleemabad-core/architecture/architecture.md
    ✓ taleemabad-core/related/related.md
    ↓
Reads related.md:
    [[projects/taleemabad-cms]]
    [[projects/taleemabad-auth]]
    ↓
(TODO: Call MemPalace MCP)
mempalace_get_related("taleemabad-core")
        ↓
Returns related projects + their context
        ↓
Claude now knows (without asking):
    ✓ Current project: taleemabad-core (Django LMS)
    ✓ Related: taleemabad-cms (frontend), taleemabad-auth (JWT)
    ✓ Architecture: Models, views, Celery tasks, S3 integration
    ✓ Recent decisions from decisions.md
    ✓ Last 3 session summaries
```

---

## Flow 3: Semantic Search (Finding Relevant Memory)

```
User: "How do I fix quiz feedback bugs?"
        ↓
Claude uses MemPalace:
    mempalace_search(
        query="quiz feedback bug",
        wing="taleemabad-core"
    )
        ↓
MemPalace converts query to vector embedding:
    "quiz feedback bug"
    ↓
Searches against all embeddings in taleemabad-core wing:
    [Check similarity scores]
    ↓
Returns best matches:
    1. vault/projects/taleemabad-core/architecture.md
       (Section: Celery async feedback)
       Similarity: 0.92
       
    2. vault/logs/2026-04-28.md
       (Work-log: "Fixed quiz feedback timeout")
       Similarity: 0.87
       
    3. vault/memory/taleemabad_training_project.md
       (Describes quiz system + AI feedback)
       Similarity: 0.81
    ↓
Claude assembles answer from these sources:
    "I see you fixed a Celery timeout in quiz feedback.
     Looking at your architecture, the Celery task...
     [Pulls exact content from architecture.md]
     Your last session notes: [Pulls from work-log]
     System design: [Pulls from training_project.md]"
```

---

## Flow 4: Multi-Project Context Flow

```
Session 1: Working in taleemabad-core
    ↓
    [project-detect] loads taleemabad-core wing
    Claude: "I see the Django LMS backend"
    ↓
    User: "The CMS upload flow is timing out"
    Claude: (searches related.md)
    Claude: "Let me check taleemabad-cms context too"
    ↓
    (TODO: MCP call)
    mempalace_get_wing("taleemabad-cms")
    ↓
    Claude now has both projects:
        - Core: Django REST API, Celery tasks, S3 presigned URLs
        - CMS: React SPA, useS3Upload hook, file picker
    ↓
    Claude: "The issue is likely in the presigned URL endpoint
             Let me check core's timeout configuration...
             And verify CMS is sending correct headers..."
    
    (Context flows naturally between projects)

Session 2: Working in taleemabad-cms
    ↓
    [project-detect] loads taleemabad-cms wing
    (Also loads related: taleemabad-core context)
    ↓
    Claude: "Welcome back to taleemabad-cms.
             Related: taleemabad-core (API you consume)
             Last session: Fixed presigned URL timeout"
    ↓
    User: "The upload button is slow"
    Claude: (searches both wings)
    Claude: "I remember the core API timeout from last session.
             That's likely affecting CMS. Let's check:
             1. Core presigned URL response time
             2. CMS useS3Upload hook timeout"
```

---

## Flow 5: Domain Context Flow

```
User edits vault/domains/taleemabad/work-log.md
    ↓
post-tool-use.py fires:
    Wing: "taleemabad" (domain)
    Room: "work-log"
    ↓
MemPalace stores:
    taleemabad/work-log/2026-05-04.md
    ↓
Content: "Fixed quiz feedback bug in core API"
        "Started S3 bucket migration planning"
        "Met with Anam about NIETE sync"
    ↓
Indexed for semantic search:
    ✓ "quiz feedback" → links to taleemabad-core wing
    ✓ "S3 bucket" → links to taleemabad-cms (also uses it)
    ✓ "Anam" → links to contacts/people/anam_masood.md
    ↓
Later, Claude can query:
    "What work have I done on S3?"
    → Returns work-log entry + taleemabad-core + taleemabad-cms context
    
    "Tell me about Anam"
    → Returns people/anam_masood.md + all work-logs mentioning Anam
```

---

## Flow 6: Session End (Stop Hook)

```
Session ends
        ↓
stop.py HOOK fires
        ↓
[1] Git commit
    git add -A && git commit -m "log: session 2026-05-04"
        ↓
[2] Update STANDUP.md
    Read vault/logs/2026-05-04.md
    Extract carry-overs:
        "Still pending: S3 migration review"
        "Still pending: Anam's feedback on NIETE sync"
    ↓
    Update STANDUP.md:
        ## Carry-Overs (Active from Prior Sessions)
        - [ ] Review S3 bucket migration plan
        - [ ] Get Anam feedback on NIETE sync
    ↓
[3] MemPalace full sync
    (TODO: MCP call)
    mempalace_sync_all(vault_dir)
        ↓
    Ensures all changed files indexed:
        ✓ work-log entry from this session
        ✓ project updates
        ✓ new contacts
        ↓
Next session:
    [project-detect] loads context
    Claude sees carry-overs: "S3 migration review pending"
    Claude: "Let's tackle the S3 migration review you noted"
```

---

## Flow 7: Knowledge Graph (Future Enhancement)

```
MemPalace indexes relationships:
    ↓
    Entities: taleemabad-core, taleemabad-cms, S3, Celery
    Relationships:
        taleemabad-core → (uses S3) → taleemabad-cms
        taleemabad-core → (uses Celery) → async feedback
        taleemabad-cms → (consumes API) → taleemabad-core
    ↓
Claude can query:
    "What uses S3?"
    → taleemabad-core (presigned URLs), taleemabad-cms (uploads)
    
    "What's the dependency chain for quiz feedback?"
    → User submits in CMS → calls core API → Celery task queues
    → Claude generates feedback → returns to CMS
```

---

## Data Flow: Complete Picture

```
┌──────────────────────────────────────────────────────────────────┐
│                      Your Workflow                               │
│                                                                  │
│  Session 1              Session 2              Session 3         │
│  └─ Edit files          └─ Edit files          └─ Edit files   │
│     in vault               in vault               in vault      │
│     ↓                      ↓                      ↓             │
│  [post-tool-use]        [post-tool-use]        [post-tool-use]│
│     ↓                      ↓                      ↓             │
│  Syncs to ←────────────────┼────────────────────→ Syncs to    │
│  MemPalace                  │                     MemPalace    │
│                             │                                  │
│                             ↓                                  │
│                    ┌────────────────────┐                      │
│                    │  MemPalace Store   │                      │
│                    │ (ChromaDB + vectors)                      │
│                    │                    │                      │
│                    │ Wings:             │                      │
│                    │ • workspace        │                      │
│                    │ • taleemabad-core  │                      │
│                    │ • taleemabad-cms   │                      │
│                    │ • taleemabad-auth  │                      │
│                    │ • taleemabad       │                      │
│                    │ • portfolio-*      │                      │
│                    └────────────────────┘                      │
│                             ↑                                  │
│                    [project-detect]                            │
│                    [post-tool-use]                             │
│                    [stop]                                      │
│                   (MCP tools)                                  │
│                             │                                  │
│  Session N                  │                                  │
│  └─ cd taleemabad-core      │                                  │
│  └─ [project-detect]────────┘                                  │
│  └─ Load context                                               │
│  └─ Claude: "I remember..."                                    │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## Summary: The Loop

```
You work       →  Files change  →  Hooks fire  →  MemPalace updates
   ↑                                                     ↓
   │                                            Stores embeddings
   │                                                     ↓
   │                                          Semantic search ready
   │                                                     ↓
Next session   ←  [project-detect]  ←  Load context  ←  MCP tools
   ↓
Claude knows context
   ↓
Work with full memory
```

---

## Key Insight: Why Semantic Search Matters

**Keyword Search** (Bad):
```
User asks: "How do I upload files?"
Search for: "upload"
Results: Only files with word "upload"
Missing: "S3", "presigned", "browser-direct"
```

**Semantic Search** (Good):
```
User asks: "How do I upload files?"
Search for semantic similarity to: "file upload mechanism"
Results: 
  • S3 bucket configuration
  • presigned URL endpoint
  • useS3Upload hook
  • AssetForm component
  • vault/domains/taleemabad/work-log entries about uploads
Claude: "Ah, you use presigned URLs..."
```

MemPalace uses vector embeddings for semantic search, so Claude understands concepts, not just keywords.

---

## When All Hooks Are Integrated

```
Timeline:

0:00 - You start work
0:05 - Edit 3 files in vault/
       → post-tool-use fires 3 times
       → All 3 files indexed in MemPalace
       
1:30 - Ask Claude about past pattern
       → Claude searches MemPalace
       → Finds relevant precedent in work-log
       → Applies it to current problem
       
5:00 - Session ends
       → stop.py hook fires
       → Git commit created
       → STANDUP.md updated
       → Full MemPalace sync

Next Session:

0:00 - Open terminal in taleemabad-core
       → project-detect fires
       → Loads taleemabad-core wing from MemPalace
       → Shows last 3 sessions summary
       → Shows related projects (cms, auth)
       → Claude: "You were working on S3 migration..."
       
Claude has full context without being asked.
```

---

## Bottom Line

**MemPalace solves "Claude forgets" by**:
1. **Persisting** all vault files in a local vector database
2. **Indexing** them for semantic search (not keyword-only)
3. **Auto-loading** project context at session start
4. **Syncing** all changes as you make them
5. **Retrieving** relevant memory when Claude needs it

**Result**: Claude remembers your projects, decisions, patterns, and people across every session.

