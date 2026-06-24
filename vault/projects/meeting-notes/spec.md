# Meeting Notes — Feature Spec (Varys)

**Owner:** Shoaib · **Status:** Draft / pre-build · **Author:** product-lead
**Last updated:** 2026-06-23

---

## 1. Problem & outcome

Shoaib sits in mixed English+Urdu meetings and walks away without a reliable record —
decisions and action items live only in memory. **Outcome:** every digital meeting on
his laptop produces a speaker-attributed transcript + a summary with action items,
delivered to Slack, with **zero manual effort** (auto-detected, auto-recorded,
auto-processed).

**North Star:** % of meetings that produce usable notes Shoaib actually reads.
**Guardrail:** zero meetings recorded that shouldn't be (privacy), and the laptop
never gets melted by transcription during a live meeting (resource contention).

Evidence base: first-principles + the constraint set Shoaib confirmed (CPU-only laptop,
mixed-language, digital meetings, wants speaker labels, Slack delivery, auto-detect).

---

## 2. Confirmed constraints (from scoping)

| Decision | Choice | Consequence |
|---|---|---|
| **Trigger** | Auto-detect (calendar + audio presence) | Heaviest path; privacy + false-positive risk — see §7 |
| **Output** | Summary + action items → **Slack thread** | LLM post-processing; Slack via `mcp__slack__*` (never CLI) |
| **Speaker labels** | **Yes — real names required** | pyannote diarization + voice enrollment for names; see §7.1 |
| **Audio source** | Google Meet (primary); physical → joins Meet or just mic | PipeWire `.monitor` (others) + mic (him) via ffmpeg; physical meeting = mic captures the room |
| **Queue** | Record always, never block; process FIFO one-at-a-time | Recording independent of processing; processing yields to active recording — §5.1 |
| **Hardware** | CPU-only | Processing ≈ 2–4× realtime; background queue mandatory |
| **Rate limits** | Rejected Groq free tier | Default = **full local** (faster-whisper + pyannote via WhisperX) |

---

## 3. How audio is captured (the core question)

**No bot joins the meeting.** Varys records the laptop's own audio locally while Shoaib
is in the meeting. All tooling already installed (`ffmpeg`, `pw-record`, `pactl`,
PipeWire 1.0.5).

Capture command (everyone else = speaker monitor; Shoaib = mic; mixed to one
16kHz mono FLAC, the format Whisper wants):

```bash
ffmpeg -f pulse -i default.monitor -f pulse -i default \
  -filter_complex amix=inputs=2:normalize=0 -ar 16000 -ac 1 -c:a flac meeting.flac
```

The recorder runs as a tracked background process; stop = SIGINT to finalize the file.

---

## 4. Detection: when does recording start/stop?

Pure audio-detection is **noisy** (a Chrome audio stream can't be distinguished from
YouTube by stream name alone). So detection is **calendar-primary, audio-confirmed:**

**START** when *either*:
- **Calendar** (Google Calendar MCP) shows an event in progress that has a Meet/Zoom
  link — high confidence, named, time-bounded; **and/or**
- **Audio presence** — a known meeting app is producing audio. Detect via
  `pactl list sink-inputs` filtered to: Zoom/Teams native processes (reliable by name),
  or a browser stream that coincides with a calendar meeting (browser alone is *not*
  sufficient — gated behind calendar match to avoid recording YouTube).

**STOP** when *any*:
- The meeting app's audio stream disappears (left the call) — cleanest signal; **or**
- Calendar event end time passes; **or**
- Sustained silence below threshold for N minutes (default 5).

**Consent guardrail (mandatory):** on auto-start, Varys posts to Slack:
`🎙️ Recording "<title>" — reply 'stop' to cancel.` Recording is **never silent**.
Plus a global kill-switch and a do-not-record list (titles/people).

A dedicated lightweight daemon (`meeting-watcher`, @reboot, ~20s poll) owns detection.
The 270s orchestrator tick is too coarse to catch a meeting start promptly.

---

## 5. Pipeline (end to end)

```
meeting-watcher (20s poll)
  detect start → ffmpeg capture (bg, PID tracked) → Slack consent notice
  detect stop  → finalize meeting.flac → enqueue job (file queue, like slack_queue)
        ↓
meeting-worker (one job at a time, low priority — never during a live recording)
  1. WhisperX: faster-whisper large-v3-turbo (int8) — transcribe, language=None (code-switch)
  2. pyannote diarization → speaker turns (SPEAKER_00/01/…)
  3. align transcript ↔ speaker turns → speaker-segmented transcript
  4. Claude summarize → summary + decisions + action items (mixed-language aware prompt)
  5. post to Slack thread via mcp__slack__slack_post_message
  6. store transcript + audio under vault/projects/meeting-notes/recordings/<date>/
```

**Tooling pick:** **WhisperX** — it wraps faster-whisper + pyannote + alignment in one
pipeline, which is exactly the transcribe+diarize+align combo this needs. Avoids
hand-wiring three libraries.

### 5.1 Queue & resource contention (confirmed design)

- **Recording is decoupled from processing.** ffmpeg capture is near-zero CPU (writes
  audio to disk), so a new recording **always starts on detection and always enqueues**,
  regardless of how many prior recordings are unprocessed. Back-to-back meetings are
  never dropped.
- **Worker drains the queue FIFO, one job at a time** (`recordings_queue/` ordered by
  timestamp — mirror the `slack_queue` pattern).
- **Processing yields to active recording.** While a recording is live, the worker
  pauses (or, if the machine proves capable, runs `nice`d with limited threads). Reason:
  WhisperX maxing all cores on a CPU-only laptop can lag the live Meet call and cause
  ffmpeg to drop samples → corrupt the in-progress recording. Queue persists across the
  pause; nothing is lost. Default = pause; make it a config flag.

---

## 6. Phasing — ship incrementally (strong recommendation)

| Phase | Scope | Why this order |
|---|---|---|
| **v0** (build first) | **Manual** `@Varys start/stop` → capture → WhisperX transcribe+diarize → summary → Slack | **Validate transcript+diarization quality on REAL mixed-Urdu meetings before building anything else.** If quality fails here, auto-detect is wasted effort. |
| **v1** | Add auto-detect (calendar + audio), consent notice, kill-switch, auto-stop | Only worth building once v0 proves the notes are usable |
| **v2** | Speaker → real names (voice enrollment or Slack rename), Notion Meetings DB, search across past meetings | Polish + memory integration |

**The product call:** do NOT build auto-detect first. Auto-detecting meetings into
garbage transcripts is negative value. Prove quality with manual trigger (a few real
meetings), *then* automate the trigger.

---

## 7. Risks & honest pushback

### 7.1 Real names — the hard one (Shoaib requires names)

Meet will **not** hand an external recorder a name↔voice mapping. Options, ranked:

| Approach | Real names? | Catch |
|---|---|---|
| Meet native transcript (Workspace) | Yes | Single-language only → **mangles English+Urdu code-switching**. Defeats the purpose. ❌ |
| **Voice enrollment** (one ~30s sample per recurring person → stored embedding) | Yes, automatic forever | One-time setup per person; language-agnostic, offline, robust. **← recommended** |
| Active-speaker DOM capture (browser extension logs Meet's active-speaker highlight + timestamp) | Yes, most accurate | Real engineering; fragile to Meet UI changes |
| Manual rename in Slack (`00=Ali, 01=Sara`) | Per-meeting | Cluster IDs unstable across meetings → re-map each time. Stopgap only. |

**Plan:** v1 ships `SPEAKER_00` + Slack-reply rename (stopgap). **v2 = voice enrollment**
— the only path that gives automatic real names *and* survives the mixed-language
requirement. Accept that automatic naming is a v2 capability, not free in v1.

2. **CPU performance.** WhisperX + diarization on CPU ≈ 2–4× realtime. A 1-hour meeting
   = 2–4 hours of processing. Notes land *well after* the meeting. Mitigations: turbo
   model + INT8 + VAD; one job at a time; processing yields to active recording (§5.1).
   **Escape hatch if too slow:** hybrid — transcribe on Groq (fast), diarize locally,
   align locally. Cuts the heaviest step but reintroduces the rate limit you rejected.
   Default stays full-local; revisit if v0 processing time is intolerable.

3. **Urdu word-alignment may be weak.** WhisperX forced-alignment uses language-specific
   phoneme models; Urdu coverage is poor/absent. Fallback: segment-level speaker
   assignment (slightly coarser than word-level). Acceptable for notes; flag if it
   smears speaker boundaries on rapid back-and-forth.

4. **Code-switching accuracy.** Even large-v3-turbo mis-segments at English↔Urdu
   boundaries; Roman-Urdu (Latin script) is worse than native script. `language=None`
   auto-detect per segment is the best lever. Set expectations: not verbatim; good
   enough for summary + action items, glance-check important meetings.

5. **Privacy / consent (legal-compliance flag).** Recording others can require consent
   in two-party-consent contexts. Mitigations in §4 (visible notice, kill-switch,
   do-not-record list). Worth a quick legal-compliance pass before v1 auto-record ships.

6. **Always-on watcher footprint.** A daemon polling audio streams every 20s is light,
   but it's another @reboot process. Reuse the existing daemon/queue patterns
   (varys-listener, slack_queue) rather than inventing new infra.

---

## 8. Architecture fit with Varys

- **New:** `meeting-watcher.py` (detection daemon, @reboot), `meeting-worker.py`
  (transcription queue worker). Mirror existing `varys-slack-listener` + `slack_queue`
  patterns — don't invent new infra.
- **Reuse:** Slack output via `mcp__slack__*` (per project memory — never CLI scripts).
  Google Calendar MCP for detection. Claude for summarization.
- **Storage v1:** flat files under `vault/projects/meeting-notes/recordings/<date>/`
  (audio + transcript + summary). Notion "Meetings" DB is v2.
- **New dependency:** `whisperx` (pulls faster-whisper + pyannote + torch, CPU build).
  pyannote needs a HuggingFace token + one-time gated-model acceptance. ~1.5GB model
  download (turbo) cached after first run.

---

## 9. Out of scope (v1)

- Bot-joins-meeting model (Recall.ai / headless browser) — explicitly rejected
- In-person / room recording (digital only for now)
- Real-time / live transcript during the meeting (batch only)
- Speaker → real-name mapping (v2)
- Notion Meetings DB + cross-meeting search (v2)
- Non-laptop capture (phone, conference hardware)

---

## 10. Open decision for Shoaib

**Build v0 (manual trigger) first to validate quality, or go straight at v1 auto-detect?**
Recommendation: v0 first — it's ~1 day, de-risks the entire feature, and tells us
whether mixed-Urdu transcripts + diarization are even good enough before we invest in
the auto-detect machinery.
