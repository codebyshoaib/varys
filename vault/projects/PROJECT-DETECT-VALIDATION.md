---
title: project-detect Hook Validation & Testing
tags: [infrastructure, hooks, testing, validation]
date: 2026-05-04
---

# project-detect Hook — Validation & Testing

**Purpose**: Auto-detect working directory on session start, load project context from MemPalace, surface related projects.

**Current Status**: ⚠️ Not yet fully validated — hooks need testing integration with Claude Code

---

## Expected Behavior

### Trigger
- **When**: Session start (pre-session hook)
- **Trigger**: First tool call in a new session
- **Input**: Current working directory (`$PWD`)

### Actions
1. **Detect project** — Match `$PWD` against known projects
2. **Load context** — Activate project wing in MemPalace
3. **Surface related** — Read `related.md`, extract sibling projects
4. **Display context** — Show to Claude for session awareness

### Example Flow

```
User opens terminal in /home/oye/Documents/taleemabad-core
  ↓
project-detect.py fires
  ↓
Detects: "taleemabad-core"
  ↓
Loads: MemPalace wing "taleemabad-core"
  ↓
Reads: vault/projects/taleemabad-core/related.md
  ↓
Extracts: [[projects/taleemabad-cms]], [[projects/taleemabad-auth]]
  ↓
Claude sees:
  - Current project: taleemabad-core (Django LMS backend)
  - Related: taleemabad-cms (frontend consumer), taleemabad-auth (JWT provider)
  - Session context automatically loaded
```

---

## Implementation Status

### ✅ Completed
- Script created: `.claude/hooks/project-detect.py`
- Project paths configured in script
- Related.md detection logic implemented
- MCP server configuration in `.claude/settings.json`

### ⚠️ Needs Testing
- [ ] Hook actually fires on session start (Claude Code integration)
- [ ] $PWD detection works in different contexts
- [ ] MemPalace wing activation (MCP call not yet implemented)
- [ ] Related.md parsing extracts all links correctly
- [ ] Context displayed to Claude properly

### ❌ Not Yet Implemented
- MemPalace MCP tool integration (currently logs intent only)
- Last 3 session summaries retrieval
- Actual context display to Claude

---

## Test Cases

### Test 1: taleemabad-core Detection
```bash
cd /home/oye/Documents/taleemabad-core
# Expected output (in session context):
# [project-detect] Detected project: taleemabad-core
# [project-detect] Context: {
#   "project": "taleemabad-core",
#   "related": ["taleemabad-cms", "taleemabad-auth"]
# }
```

**Status**: ⏳ Pending validation  
**Evidence**: None yet  
**Notes**: Need to verify hook fires and output appears

---

### Test 2: taleemabad-cms Detection
```bash
cd /home/oye/Documents/free_work/personal-agent/repos/taleemabad-cms
# Expected output:
# [project-detect] Detected project: taleemabad-cms
# [project-detect] Context: {
#   "project": "taleemabad-cms",
#   "related": ["taleemabad-core", "taleemabad-auth"]
# }
```

**Status**: ⏳ Pending validation  
**Evidence**: None yet

---

### Test 3: Unknown Directory Detection
```bash
cd /home/oye/Documents/some-random-folder
# Expected output:
# [project-detect] No project detected; loading workspace context
```

**Status**: ⏳ Pending validation  
**Evidence**: None yet

---

### Test 4: Related Projects Extraction
```
vault/projects/taleemabad-core/related.md contains:
  [[projects/taleemabad-cms]]
  [[projects/taleemabad-auth]]

Expected extraction: ["taleemabad-cms", "taleemabad-auth"]
```

**Status**: ⏳ Pending validation  
**Evidence**: None yet

---

### Test 5: Symlink Resolution
```
repos/taleemabad-core → /home/oye/Documents/taleemabad-core
cd repos/taleemabad-core
# Should still detect as: taleemabad-core
```

**Status**: ⏳ Pending validation  
**Evidence**: None yet

---

## Integration Checklist

- [ ] `.claude/settings.json` has `pre-session` hook configured
- [ ] Hook script is executable (`chmod +x .claude/hooks/project-detect.py`)
- [ ] Claude Code recognizes hook on session start
- [ ] Output appears in stderr/logs
- [ ] MemPalace MCP integration wired up
- [ ] Related.md files exist for all 5 projects
- [ ] Wikilinks in related.md are parseable

---

## What Needs to Happen Next

### Phase 1: Hook Execution Validation
1. **Open new terminal** in personal-agent-v2
2. **Navigate to taleemabad-core**: `cd /home/oye/Documents/taleemabad-core`
3. **Run Claude Code** or open new session
4. **Check logs** for `[project-detect]` messages
5. **Verify**: "taleemabad-core" detected correctly

**Success Criteria**: See detection message in session logs

---

### Phase 2: MCP Integration
1. **Install MemPalace MCP server** in Claude Code settings
2. **Update project-detect.py** to call MemPalace `upsert` tool
3. **Test context loading**: Verify MemPalace wing activated
4. **Test related projects**: Check if surface properly

**Success Criteria**: Claude mentions related projects when in taleemabad-core

---

### Phase 3: Full End-to-End
1. **Session start** in taleemabad-core
2. **Claude auto-loads** project context
3. **Claude mentions** related projects (cms, auth)
4. **Ask Claude**: "What project am I in?" → Should correctly identify
5. **Ask Claude**: "What's related to this?" → Should list cms, auth

**Success Criteria**: Natural context awareness without manual prompting

---

## Known Issues / Gaps

### Issue 1: Hook Not Firing
**Problem**: pre-session hook may not be recognized by Claude Code  
**Impact**: Context never loaded  
**Solution**: Verify hook configuration in `.claude/settings.json`

---

### Issue 2: MemPalace MCP Not Wired
**Problem**: Script logs intent but doesn't call MemPalace MCP  
**Impact**: No semantic memory activation  
**Solution**: Implement actual MCP call once MemPalace MCP server available

---

### Issue 3: Related.md Parsing
**Problem**: Regex may miss wikilink variants  
**Current**: Looks for `[[projects/name]]`  
**Edge case**: What if someone writes `[[projects/name | display text]]`?  
**Solution**: Improve regex to handle display text

---

### Issue 4: Symlink Resolution
**Problem**: `Path.resolve()` follows symlinks; may resolve to actual path  
**Impact**: May not match symlink-based detection  
**Solution**: Test with symlinks; adjust if needed

---

## Validation Log

### Session 2026-05-04
- ✅ Script created and committed
- ✅ Configuration added to settings.json
- ✅ Related.md files created for all 5 projects
- ⏳ **Next**: Hook execution test (when Claude Code is running)

### Session [TBD]
- [ ] Hook fires on session start?
- [ ] Output visible in logs?
- [ ] Related projects detected?
- [ ] MemPalace integration working?

---

## How to Update This Document

Every time you test:
1. Note **what you tested** (which project, what happened)
2. Record **expected vs actual** behavior
3. Update the relevant **Test Case** section
4. Mark ✅ (passed) or ❌ (failed)
5. Log **findings** under "Validation Log"

Example:
```markdown
### Session 2026-05-05
- ✅ Tested taleemabad-core detection
  - Expected: "Detected project: taleemabad-core"
  - Actual: ✅ Matches
  - Output appeared in stderr
- ❌ Related projects not extracted
  - Expected: ["taleemabad-cms", "taleemabad-auth"]
  - Actual: [] (empty)
  - Issue: Regex not matching `[[projects/...]]` wikilinks
  - Fix needed: Improve regex pattern
```

---

## Success Criteria (Final Validation)

✅ **COMPLETE** when:
1. Hook fires on session start (visible in logs)
2. Project detected correctly for 5 test cases
3. Related.md parsed correctly
4. MemPalace MCP integration working
5. Claude mentions related context naturally
6. No false positives (unknown dirs don't break)
7. Symlinks resolved correctly

---

## Notes for Kamal

This hook is the **nervous system** for context. When it works:
- You won't have to manually tell Claude what project you're in
- Related work surfaces automatically (cms context when in core, etc.)
- Lost context problem **solved**

Status: Ready for testing. Run a session and check the logs.
