---
name: linkedin-post
description: "End-to-end LinkedIn post pipeline: NotebookLM notebook → visual infographic → LinkedIn post. Use when user says 'post on LinkedIn', 'write a linkedin post about', or invokes /linkedin-post <topic>."
trigger: /linkedin-post
---

# /linkedin-post

Full pipeline: topic → NLM notebook → NLM infographic (visual, minimal text) → LinkedIn copy → post.

## Usage

```
/linkedin-post <topic>
```

Examples:
```
/linkedin-post Harness Engineering for AI Coding
/linkedin-post How to review PRs like a senior engineer
/linkedin-post Why context engineering beats prompt engineering
```

## What You Must Do — Step by Step

### Step 1: Extract topic from args

`args` is the topic string. If empty, ask the user for a topic and stop.

### Step 2: Check for existing NLM notebook

```bash
nlm notebook list --json 2>/dev/null
```

Search the list for a notebook whose title closely matches the topic. If found, reuse it (grab its `id`). If not, create one:

```bash
nlm notebook create "<topic>" --json
```

Save the notebook ID as `NB_ID`.

### Step 3: Add content source to notebook

If the notebook is newly created (source_count == 0), synthesize a rich, structured text source covering:
- What the topic is (definition, 1 paragraph)
- Why it matters (3–5 key reasons)
- How it works (the core mechanism or framework, numbered steps)
- Common mistakes / misconceptions
- How to start as a beginner (actionable first steps)
- Key insight / takeaway

Add it:
```bash
nlm source add "$NB_ID" --wait --title "<topic> — Core Concepts" --text "<your synthesized content>"
```

Wait for `--wait` to confirm the source is ready before moving on.

### Step 4: Generate NLM infographic

The infographic should be visual-first, minimal text. Big numbers, icons, short labels — not paragraphs.

```bash
nlm infographic create "$NB_ID" --orientation portrait --detail brief --confirm
```

Capture the Artifact ID from the output line `Artifact ID: <id>`. Save as `ART_ID`.

Poll until status is `completed`:
```bash
until nlm studio status "$NB_ID" --json 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
art = next((a for a in d if a['id'] == '$ART_ID'), None)
print(art['status'] if art else 'pending')
sys.exit(0 if art and art['status'] == 'completed' else 1)
"; do sleep 8; done
```

Download:
```bash
nlm download infographic "$NB_ID" --id "$ART_ID" --output /tmp/linkedin-infographic.png
```

Show the image to the user with Read so they can see it before posting.

### Step 5: Generate LinkedIn copy

Write the post using the notebook research as your substance. The voice is Shoaib — a senior engineer who ships real things under real constraints.

**Voice rules — these override everything else:**
- Write one specific story or observation. Not a summary. Not a list of tips.
- Short sentences. 1–2 sentences per paragraph. Break between every paragraph.
- Concrete: real numbers, tool names, named systems. Not "it was slow" → "847ms per request, fixed with one index".
- First person throughout. "I noticed", "We hit", "The fix embarrassed me".
- Opening line: a fact, surprising number, or admission. Never a question. Never hype.

**What AI-sounding looks like — don't write this:**
- "In today's fast-paced tech landscape, X is changing everything..."
- "Here's why this matters → ✅ Point 1 ✅ Point 2 ✅ Point 3"
- "🔥 Game changer alert: 5 things every engineer should know about..."
- "Excited to share that I've been exploring..."

**What senior-engineer LinkedIn actually looks like:**
- "I wasted 3 weeks on the wrong abstraction. Here's what I should have done from day 1."
- "We had 2000 active tenants hitting the same unindexed query. Fixing it was embarrassing in retrospect."
- "The thing nobody tells you about Django signals: they run synchronously in the same transaction."

**Structure (prose paragraphs, not a template):**
1. Para 1: one specific, surprising, or uncomfortable observation — 1–2 sentences
2. Para 2: what caused it / the actual situation you were dealing with
3. Para 3: what changed and what happened — the concrete payoff
4. Para 4 (optional): one principle distilled from it — not a listicle, one sentence
5. Closing question: specific and professional, not "agree?" or "thoughts?"
6. Hashtags: 3 max, last line only

**Length: 900–1400 characters. No bullet lists. No emoji headers.**
Handle: do NOT include @shoaibmughal in the post text itself.

### Step 6: Post to LinkedIn

```bash
python3 /home/shoaib/varys/.claude/hooks/linkedin_poster.py \
  --image /tmp/linkedin-infographic.png \
  --text "<post copy>"
```

On success, output looks like: `✅ Posted to LinkedIn | ID: urn:li:share:<id>`

### Step 7: Report back

Tell the user:
- Post ID / share URN
- Infographic was NLM-generated
- One-line summary of the post angle

## Error Handling

- `nlm source add` fails → retry once; if still fails, skip and proceed (NLM can still generate from an empty notebook using its own knowledge)
- `nlm infographic create` fails → tell the user and stop (do not fall back to image_generator.py — user wants NLM)
- `linkedin_poster.py` fails with auth error → tell user to run `python3 /home/shoaib/varys/.claude/hooks/linkedin_oauth.py` to re-auth, then retry
- Infographic poll times out after 3 minutes → tell user NLM is slow, share the notebook URL so they can check manually

## Notebook Registry

After a successful run, register the notebook in the Notion NLM Registry DB so it's findable next time:
- DB ID: from `.claude/rules/notebooklm.md` (`NOTION_NLM_REGISTRY_DB_ID`)
- Fields: alias (slug of topic), domain (infer: tech/content/fitness/freelance), notebook ID, when_to_use

Do this in the background — don't block the post on it.
