---
name: slides
description: Generate AI full-bleed Google Slides decks via Kie.ai (nano-banana-pro) + Google Slides API. Invoke for slides/deck/presentation requests. Needs KIE_API_KEY + a Google service account with Domain-Wide Delegation to run.
---

# Google Workspace Slides Skill
*Invocation: `/slides`, `/presentation`, or `/deck`*
*Last updated: 2026-04-04*

---

## What This Skill Does

Creates professional Google Slides presentations powered by AI-generated full-bleed images via Kie.ai, uploaded through the Google Slides API. Every slide is a single full-bleed image — no text boxes, no layout engine. The AI generates everything: visuals, text, hierarchy.

The workflow is always:
```
Define slides (prompt + filename) → Generate PNGs via Kie.ai → Upload PNGs to Google Drive → Insert into Google Slides → Add speaker notes
```

---

## Visual Style Selection

When invoked, ask or infer which style the audience calls for. Different styles use a different `STYLE` constant appended to every image prompt.

### 1. Isometric — keyword: `isometric` / `isomorphic` / `board` / `rippleworks`

Used for: Board decks, investor presentations, data-heavy strategic content, Rippleworks DD, Town Halls.

Sample images: [example_isometric_rippleworks.png](style-samples/example_isometric_rippleworks.png) | [example_isometric_board.png](style-samples/example_isometric_board.png) | [17_pakistan_risk_isometric.png](style-samples/17_pakistan_risk_isometric.png)

```js
const STYLE = `
Isometric illustration style. 3D isometric perspective (30-degree angle).
Detailed miniature world-building with clean vector graphics and soft shadows.
Color palette: navy (#1B365D) for primary elements, teal (#2DD4BF) for accents and positive indicators,
coral/orange (#F97316) for highlights and emphasis, warm cream (#FAFAF8) background,
golden yellow (#FBBF24) for callouts, sage green (#22C55E) for success.
Professional, clean, modern. Game-like clarity and precision.
Typography: bold, clean, modern sans-serif — all text embedded legibly in the image.
CRITICAL: All text MUST be large, sharp, and perfectly readable. No blurry or small text.
No border, no frame. Full bleed edge-to-edge design. 16:9 aspect ratio.
DO NOT include any meta-labels, zone names, scene numbers, layout instructions, or structural labels
in the output image. Only render real content text that the audience should read.`;
```

**With logo reference** (Rippleworks variant — adds org logos to bottom corners):
```js
const STYLE = `
Isometric illustration style. 3D isometric perspective (30-degree angle).
...same as above...
Small "taleem abad" logo (blue rounded text with green dot above 'i') in BOTTOM-RIGHT corner.
Small "rippleworks" logo (navy text, teal dot above 'i') in BOTTOM-LEFT corner.
DO NOT include any meta-labels, zone names, scene numbers, layout instructions, or structural labels
in the output image. Only render real content text.`;
```

**Prompt-writing rules for Isometric:**
- Describe scenes as miniature 3D worlds ("an isometric school building", "floating 3D research cards", "interlocking gears")
- Name specific numbers/data inside the scene ("A large golden badge reading '70%'", "price tag reads '$3/child'")
- Never use zone directions ("LEFT ZONE", "RIGHT AREA") — they bleed into the generated image. Instead describe spatial layout naturally: "arranged side by side", "floating above", "connecting with an arrow at the bottom"
- Describe what each cluster, bar, or gear represents directly

---

### 2. TED-Ed — keyword: `ted-ed` / `offsite` / `story`

Used for: Offsites, culture sessions, emotional storytelling, internal company narrative presentations.

Sample images: [example_teded_offsite.png](style-samples/example_teded_offsite.png) | [example_teded_offsite_2.png](style-samples/example_teded_offsite_2.png)

```js
const TED_ED_STYLE = `
TED-Ed animation style: warm illustrated educational aesthetic.
Flat vector illustration with soft textures and organic shapes.
Warm color palette: cream/off-white background, teal (#2DD4BF), coral (#F97316),
golden yellow (#FBBF24), soft accents.
Hand-drawn feel with clean bold lines and rounded edges.
Playful but professional, engaging visual metaphors.
Simple bold typography, highly readable.
16:9 aspect ratio.`;
```

**Prompt-writing rules for TED-Ed:**
- One idea per slide — don't crowd it
- Use emotional visual metaphors ("broken chain link", "compass pointing steadily through fog")
- Minimal text in the image itself — heavy lifting in speaker notes
- Soft and organic — avoid geometric precision language
- Good for: acknowledgment slides, big questions ("This year has been hard."), era timelines

---

### 3. Townhall Isometric — keyword: `townhall` / `internal`

Identical visual style to Isometric but **without logos** and slightly more accessible tone.

```js
const STYLE = `
Isometric illustration style. 3D isometric perspective (30-degree angle).
Detailed miniature world-building like a premium video game or architectural model.
Clean vector graphics with soft shadows and subtle gradients.
Color palette: navy (#1B365D), teal (#2DD4BF), coral (#F97316), warm cream (#FAFAF8) background,
golden yellow (#FBBF24), sage green (#22C55E), soft gray for depth.
Professional but approachable. Game-like clarity and precision.
Typography is bold, clean, modern sans-serif — embedded in the image.
16:9 aspect ratio. No border, no frame. Full bleed edge-to-edge design.
CRITICAL: All text must be large, legible, and perfectly readable.
DO NOT include logos, meta-labels, zone names, or structural labels. Only real content text.`;
```

---

## Fun / Outrageous Style Explorations

When you want to try unconventional aesthetics — for a pitch, creative brief, or just to explore — these 10 styles produce striking results. Style explorations were used for the March 2026 Board Deck (Slide 17: Pakistan Risk Barrier). All 10 generated outputs are in [style-samples/](style-samples/).

Use the same `SLIDE_CONCEPT` prompt but swap in a different `STYLE` block:

| Style | Keyword | Sample | Visual DNA |
|---|---|---|---|
| **Saul Bass** | `saul-bass` | [view](style-samples/17_pakistan_risk_saul_bass.png) | Bold geometry, 2-3 colors, film poster energy, hand-cut paper feel |
| **Bauhaus** | `bauhaus` | [view](style-samples/17_pakistan_risk_bauhaus.png) | Primary colors, grid-based, constructivist, sans-serif integrated into shapes |
| **Wes Anderson** | `wes-anderson` | [view](style-samples/17_pakistan_risk_wes_anderson.png) | Perfect bilateral symmetry, muted pastels, dollhouse diorama |
| **Ukiyo-e** | `ukiyo-e` | [view](style-samples/17_pakistan_risk_ukiyo_e.png) | Japanese woodblock, flat color planes, bold black outlines, flowing organic lines |
| **Art Deco** | `art-deco` | [view](style-samples/17_pakistan_risk_art_deco.png) | Gold/black/emerald, radiating sunbursts, 1920s glamour, luxury |
| **Soviet Constructivism** | `constructivism` | [view](style-samples/17_pakistan_risk_constructivism.png) | Red/black/cream, diagonal composition, revolutionary energy, bold angles |
| **Risograph** | `risograph` | [view](style-samples/17_pakistan_risk_risograph.png) | Fluorescent ink layers, visible overlap color, paper grain, zine aesthetic |
| **Isometric (reference)** | `isometric` | [view](style-samples/17_pakistan_risk_isometric.png) | The standard isometric style above — for comparison |
| **Paper Cut** | `paper-cut` | [view](style-samples/17_pakistan_risk_paper_cut.png) | Layered paper planes with shadows, craft aesthetic, warm earth tones |
| **David Hockney** | `hockney` | [view](style-samples/17_pakistan_risk_hockney.png) | Pop art, flat bright colors, California optimism, bold outlines |

Style exploration workflow: pick one slide concept, run all 10 styles, choose the winner, then apply it to the full deck.

---

## Full Pipeline (Node.js)

The standard pattern used across all decks. Copy this shell and adapt `STYLE`, `SLIDES`, and output path.

```js
#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

const KIE = process.env.KIE_API_KEY || 'YOUR_KEY_HERE';
const OUT = path.join(__dirname, 'slides');
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });

// ── Paste one of the STYLE blocks from above ──
const STYLE = `...`;

// ── Optional: upload a reference image for logo seeding ──
async function uploadFile(filePath, uploadName, uploadPath) {
  const buffer = fs.readFileSync(filePath);
  const base64 = 'data:image/png;base64,' + buffer.toString('base64');
  const res = await fetch('https://kieai.redpandaai.co/api/file-base64-upload', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${KIE}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ base64Data: base64, fileName: uploadName, uploadPath })
  });
  const data = await res.json();
  return data?.data?.downloadUrl || null;
}

// ── Main image generation ──
async function generateImage(prompt, outPath, imageInputUrls) {
  const basename = path.basename(outPath);
  if (fs.existsSync(outPath)) {
    console.log(`  ${basename} — exists, skipping`);
    return 'exists';
  }
  process.stdout.write(`  ${basename}...`);

  const input = {
    prompt: prompt + STYLE,   // ← STYLE is always appended
    output_format: 'png',
    aspect_ratio: '16:9',
    resolution: '1K'
  };
  if (imageInputUrls?.length) input.image_input = imageInputUrls;  // ← reference images

  const res = await fetch('https://api.kie.ai/api/v1/jobs/createTask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${KIE}` },
    body: JSON.stringify({ model: 'nano-banana-pro', input })
  });
  const taskId = (await res.json()).data?.taskId;
  if (!taskId) { console.log(' FAILED'); return null; }

  // Poll until done (90 attempts × 3s = 4.5 minutes max)
  for (let i = 0; i < 90; i++) {
    await new Promise(r => setTimeout(r, 3000));
    const poll = await fetch(`https://api.kie.ai/api/v1/jobs/recordInfo?taskId=${taskId}`, {
      headers: { 'Authorization': `Bearer ${KIE}` }
    });
    const pdata = await poll.json();
    if (pdata.data?.state === 'success') {
      const url = JSON.parse(pdata.data.resultJson)?.resultUrls?.[0];
      const img = await fetch(url);
      fs.writeFileSync(outPath, Buffer.from(await img.arrayBuffer()));
      console.log(' OK');
      return url;
    }
    if (pdata.data?.state === 'fail') { console.log(' FAILED:', pdata.data?.failMsg); return null; }
    process.stdout.write('.');
  }
  console.log(' TIMEOUT');
  return null;
}

// ── Slide definitions ──
const SLIDES = [
  {
    filename: '01_title.png',
    prompt: `Title slide. [Describe the scene naturally here, no zone labels]`
  },
  // ... more slides
];

// ── Runner ──
async function main() {
  // Optional: upload logo for reference seeding
  // const logoUrl = await uploadFile('./path/to/logo.png', 'logo.png', 'my-deck');
  // const imageInputs = [logoUrl];

  for (const slide of SLIDES) {
    const outPath = path.join(OUT, slide.filename);
    await generateImage(slide.prompt, outPath /*, imageInputs */);
    await new Promise(r => setTimeout(r, 1000)); // rate limit buffer
  }
  console.log('\nDone.');
}

main().catch(console.error);
```

---

## Progressive Reveals

For presenter decks where content builds up slide-by-slide: generate the **final state** first, then generate intermediate states with elements progressively removed. Name files with letter suffixes:

```
04a_four_eras.png   ← Era 1 only
04b_four_eras.png   ← Era 1 + 2
04c_four_eras.png   ← Era 1 + 2 + 3
04d_four_eras.png   ← Final (all 4 eras)
```

Compile two PPTX versions: READABLE (final states only) and PRESENTER (with all reveal steps). The `compile-presentations.js` pattern uses `pptxgenjs`.

---

## Uploading to Google Slides (Python)

After PNGs are generated, compile them into a Google Slides deck:

```python
#!/usr/bin/env python3
import os, time, warnings
warnings.filterwarnings('ignore')

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ── Credentials ──
CREDS_PATH = '/path/to/your/service_account.json'
IMPERSONATE_EMAIL = 'you@yourdomain.com'
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/presentations']

SLIDE_WIDTH_EMU  = 9_144_000
SLIDE_HEIGHT_EMU = 5_143_500

def get_services():
    creds = service_account.Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    delegated = creds.with_subject(IMPERSONATE_EMAIL)
    slides_svc = build('slides', 'v1', credentials=delegated)
    drive_svc  = build('drive',  'v3', credentials=delegated)
    return slides_svc, drive_svc

def upload_image_to_drive(drive_svc, filepath, folder_id=None):
    """Upload PNG → Drive → make public → return URL."""
    fname    = os.path.basename(filepath)
    metadata = {'name': fname, 'mimeType': 'image/png'}
    if folder_id:
        metadata['parents'] = [folder_id]
    media   = MediaFileUpload(filepath, mimetype='image/png')
    f       = drive_svc.files().create(body=metadata, media_body=media, fields='id').execute()
    file_id = f['id']
    drive_svc.permissions().create(
        fileId=file_id,
        body={'type': 'anyone', 'role': 'reader'}
    ).execute()
    return f'https://drive.google.com/uc?id={file_id}', file_id

def create_presentation(slides_svc, drive_svc, slides_metadata, slides_dir):
    """Create a Slides deck with full-bleed images and speaker notes."""
    # 1. Create blank presentation
    pres    = slides_svc.presentations().create(body={'title': 'My Presentation'}).execute()
    pres_id = pres['presentationId']
    default_slide_id = pres['slides'][0]['objectId']

    requests = []
    slide_ids = []

    # 2. Build slide insert requests
    for i, slide in enumerate(slides_metadata):
        slide_id = f'slide_{i:03d}'
        slide_ids.append(slide_id)
        requests.append({'createSlide': {
            'objectId': slide_id,
            'insertionIndex': i,
            'slideLayoutReference': {'predefinedLayout': 'BLANK'}
        }})

    # 3. Delete the default slide
    requests.append({'deleteObject': {'objectId': default_slide_id}})

    slides_svc.presentations().batchUpdate(
        presentationId=pres_id,
        body={'requests': requests}
    ).execute()

    # 4. Upload images and insert into slides
    for i, (slide, slide_id) in enumerate(zip(slides_metadata, slide_ids)):
        filepath = os.path.join(slides_dir, slide['filename'])
        print(f'  Uploading {slide["filename"]}...')
        img_url, _ = upload_image_to_drive(drive_svc, filepath)

        slides_svc.presentations().batchUpdate(
            presentationId=pres_id,
            body={'requests': [{
                'createImage': {
                    'objectId': f'img_{slide_id}',
                    'url': img_url,
                    'elementProperties': {
                        'pageObjectId': slide_id,
                        'size': {
                            'width':  {'magnitude': SLIDE_WIDTH_EMU,  'unit': 'EMU'},
                            'height': {'magnitude': SLIDE_HEIGHT_EMU, 'unit': 'EMU'}
                        },
                        'transform': {
                            'scaleX': 1, 'scaleY': 1,
                            'translateX': 0, 'translateY': 0,
                            'unit': 'EMU'
                        }
                    }
                }
            }]}
        ).execute()

    return pres_id

def add_speaker_notes(slides_svc, pres_id, slide_ids, slides_metadata):
    """Add speaker notes to each slide."""
    pres = slides_svc.presentations().get(presentationId=pres_id).execute()
    
    for slide_data, slide_page in zip(slides_metadata, pres['slides']):
        notes_page_id = slide_page['slideProperties']['notesPage']['objectId']
        notes_shape   = next(
            s for s in slide_page['slideProperties']['notesPage']['pageElements']
            if s.get('shape', {}).get('shapeType') == 'TEXT_BOX'
        )
        notes_shape_id = notes_shape['objectId']
        
        slides_svc.presentations().batchUpdate(
            presentationId=pres_id,
            body={'requests': [
                {'deleteText': {'objectId': notes_shape_id, 'textRange': {'type': 'ALL'}}},
                {'insertText': {'objectId': notes_shape_id, 'text': slide_data.get('notes', ''), 'insertionIndex': 0}}
            ]}
        ).execute()
        time.sleep(0.3)  # avoid rate limit


# ── Usage ──
slides_metadata = [
    {'filename': '01_title.png',    'notes': 'Welcome. Agenda overview...'},
    {'filename': '02_hard_year.png','notes': 'Acknowledge difficulty before moving forward.'},
    # ...
]

slides_svc, drive_svc = get_services()
pres_id = create_presentation(slides_svc, drive_svc, slides_metadata, './slides')
add_speaker_notes(slides_svc, pres_id, [], slides_metadata)
print(f'https://docs.google.com/presentation/d/{pres_id}/edit')
```

---

## Speaker Notes: How to Write Them

Speaker notes are the hidden layer that makes a presentation actually deliverable. Every slide should have notes that do three things:

1. **What you're seeing** — orient the audience/presenter to what's on the slide
2. **The key insight** — the one thing they must take away
3. **The board/audience ask** (if applicable) — the specific question or action

**Example from the Board Deck (Slide 11 — Islamabad Cliff):**
```
What you're seeing: Our single largest revenue source expires in 3 months.

Context: Islamabad is $2.6M of our annual revenue — a 3-year contract expiring June 2026.
Planning Minister has given verbal go-ahead for renewal. Documentation started.
Outside ICT: only smaller contracts ($400K/6mo, $100K/2mo). The cliff is real.

QUESTION FOR DAVID: How do we move from project-mode contracts to a permanent government
budget head? How did the Shahbaz government do this circa 2011-2015?
```

**Pattern:**
```python
# In slides_metadata, write notes like this:
{'filename': '11_cliff.png', 'notes': """What you're seeing: [1-sentence orientation]

[2-3 sentences of essential context — what the audience needs to know]

QUESTION: [The specific ask, if any]"""}
```

---

## Reference Image Seeding

Use `image_input` to maintain visual consistency across a deck — pass an uploaded logo or character reference to ensure the AI uses consistent brand elements.

```js
// 1. Upload reference image
const logoUrl = await uploadFile('./logo.png', 'logo.png', 'my-deck-2026');

// 2. Pass as image_input to all generation calls
await generateImage(prompt, outPath, [logoUrl]);
```

Kie.ai upload endpoint (different from the generation endpoint):
- `POST https://kieai.redpandaai.co/api/file-base64-upload`
- Body: `{ base64Data: 'data:image/png;base64,...', fileName: '...', uploadPath: '...' }`
- Returns `data.downloadUrl`

---

## Custom Page Sizes

The Google Slides API silently ignores `pageSize` — all API-created presentations default to 16:9 (10" × 5.625"). For non-standard dimensions (A4, portrait, etc.), use the python-pptx workaround:

```python
from pptx import Presentation
from pptx.util import Inches

prs = Presentation()
prs.slide_width  = Inches(10)    # custom width
prs.slide_height = Inches(5.625) # custom height
prs.save('/tmp/custom.pptx')

# Then upload to Drive with mimeType conversion:
drive_svc.files().create(
    body={'name': 'My Deck', 'mimeType': 'application/vnd.google-apps.presentation'},
    media_body=MediaFileUpload('/tmp/custom.pptx',
        mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation',
        resumable=True, chunksize=5*1024*1024)
).execute()
```
The converted Slides file preserves the custom page size. Keep PPTX under 100MB (compress images first).

---

## EMU Reference

```
Full slide width:  9,144,000 EMU = 10.0 inches
Full slide height: 5,143,500 EMU = 5.625 inches
1 inch:              914,400 EMU
1 point:              12,700 EMU
```

Alignment values: `START` / `CENTER` / `END` — **not** LEFT / RIGHT.  
Object IDs: must be ≥ 5 characters.

---

## Credentials

### Google Drive / Slides

You need a Google service account with Domain-Wide Delegation (DWD) on your Google Workspace domain.

```python
import os

CREDS_PATH        = '/path/to/your/service_account.json'   # your service account key file
IMPERSONATE_EMAIL = 'you@yourdomain.com'                    # the Drive user to impersonate

# CRITICAL: DWD must authorize the full 'drive' scope.
# Do NOT use drive.readonly or presentations.readonly — they will 403.
SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/presentations'
]
```

To set up:
1. Create a service account in Google Cloud Console → IAM
2. Enable Drive API and Slides API for the project
3. Enable Domain-Wide Delegation on the service account
4. In your Google Admin console, authorize the service account's client ID with the two scopes above
5. Download the JSON key → that's your `CREDS_PATH`

### Kie.ai

Set as environment variable:
```bash
export KIE_API_KEY=your_key_here
```

Or hardcode in dev scripts. Sign up at [kie.ai](https://kie.ai) for an API key. The `nano-banana-pro` model is what produces the style samples shown here.

---

## Prompting Anti-Patterns

| Don't | Do instead |
|---|---|
| `"LEFT ZONE: hero image"` | `"On the left side, a detailed isometric school building"` |
| `"SCENE 1: show a wall"` | `"A large stone wall labeled 'PAKISTAN RISK' in the center"` |
| `"Section A / Section B"` | Natural spatial language: "above", "below", "connecting to", "floating" |
| Vague colors: `"green"` | Specific hex: `"sage green (#22C55E)"` |
| Long paragraphs of bullet text | Embed key numbers directly: `"A floating badge reads '0.28 SD'"` |

Zone/layout labels literally appear in the generated image. Describe content, not structure.

---

## Script Patterns

The Node.js generation script and Python compile script are embedded in full above. Copy them as your starting point and adapt to your slide set. The embedded scripts are based on production presentations and represent the full working pipeline.
