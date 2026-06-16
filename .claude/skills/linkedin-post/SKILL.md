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

```bash
nlm infographic create "$NB_ID" --orientation portrait --detail detailed --confirm
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

Write the post directly — do NOT use a template. The copy must:

**Structure (4-part viral):**
1. **Hook** — 1–2 lines. Provocative, specific, relatable. No "I'm excited to share". No "Great news". Start with a surprising claim or a direct challenge.
2. **Problem / Insight** — 2–3 lines. Why the conventional approach fails or what most people miss.
3. **Solution / Framework** — The core breakdown. Use short paragraphs or emoji-prefixed bullets (one per key point). Each point: bold label + 1-sentence explanation. Max 6 points.
4. **CTA** — 1 question to drive comments. End with relevant hashtags (3–5 max, on their own line).

**Rules:**
- Total length: 1200–1800 characters
- Line breaks after every 2–3 sentences — LinkedIn rewards white space
- No jargon without a one-sentence plain-language explanation
- Beginner-friendly framing even for advanced topics
- Closing line before CTA: one punchy sentence that crystallizes the whole post
- Handle: do NOT include @shoaibmughal in the post text itself

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
