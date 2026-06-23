# Meeting Notes v0 — Live Test Runbook

**Branch:** `feat/varys-meeting-notes-v0`
**Scope:** Manual trigger only (`start recording` / `stop recording` via Slack DM)

Run each layer in order. Don't skip ahead — each layer validates the foundation the next one depends on.

---

## Prerequisites

| Thing | Check command | Expected |
|---|---|---|
| ffmpeg | `ffmpeg -version \| head -1` | `ffmpeg version 6.x` |
| PulseAudio / PipeWire | `pactl list sources short` | sources listed |
| WhisperX | `python3 -m whisperx --help` | usage printed |
| HF_TOKEN in config | `python3 -c "import json,pathlib; d=json.loads((pathlib.Path.home()/'.agent-config.json').read_text()); print(d.get('HF_TOKEN','MISSING'))"` | `hf_...` |
| Slack listener running | `pgrep -af varys-slack-listener` | PID listed |

If WhisperX is missing:
```bash
pip install whisperx
# Then accept gated models on HuggingFace (one-time, browser):
#   hf.co/pyannote/speaker-diarization-3.1  → Accept
#   hf.co/pyannote/segmentation-3.0         → Accept
```

If HF_TOKEN is missing:
```bash
python3 -c "
import json
from pathlib import Path
cfg = Path.home() / '.agent-config.json'
d = json.loads(cfg.read_text())
d['HF_TOKEN'] = 'hf_PASTE_YOUR_TOKEN_HERE'
cfg.write_text(json.dumps(d, indent=2))
print('saved')
"
```

---

## Layer 1 — Queue unit tests (no deps)

```bash
cd /home/shoaib/varys
python3 tests/test_meeting_queue.py
```

**Pass:** `7 passed, 0 failed`
**Fail:** check that `varys_harness_db.py` has the `meeting_queue` table and all 5 queue functions.

---

## Layer 2 — Audio capture (ffmpeg only)

Validates that the PipeWire sources are active and ffmpeg can write a FLAC.

```bash
OUTDIR="/home/shoaib/varys/vault/projects/meeting-notes/recordings/test-$(date +%Y-%m-%d_%H-%M)"
mkdir -p "$OUTDIR"
AUDIO="$OUTDIR/test.flac"

# Record 15 seconds — play something or talk while this runs
ffmpeg \
  -f pulse -i alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__hw_sofhdadsp__sink.monitor \
  -f pulse -i alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__hw_sofhdadsp__source \
  -filter_complex amix=inputs=2:normalize=0 -ar 16000 -ac 1 -c:a flac \
  -t 15 "$AUDIO"

# Verify
ffprobe "$AUDIO" 2>&1 | grep -E "Duration|flac|16000"
```

**Pass:** duration ~15s, codec `flac`, sample rate `16000 Hz`

**If sources are SUSPENDED** (no audio playing), PipeWire parks them. Start any audio (a YouTube tab, `speaker-test -t sine -f 440 -l 1`) and retry.

**Note:** the exact source names above match this machine. If they change, run `pactl list sources short` and update the `-i` args.

---

## Layer 3 — Transcription (WhisperX alone, no diarization)

Use the FLAC from Layer 2. Start without diarization to verify the base model works before adding pyannote.

```bash
OUTDIR="/home/shoaib/varys/vault/projects/meeting-notes/recordings/test-$(date +%Y-%m-%d_%H-%M)"
# Use the dir from Layer 2 if it still exists, or re-record

python3 -m whisperx "$AUDIO" \
  --model large-v3-turbo \
  --compute_type int8 \
  --language None \
  --output_format json \
  --output_dir "$OUTDIR"

# Inspect output
cat "$OUTDIR/test.json" | python3 -m json.tool | head -40
```

**Pass:** JSON file written, `segments` array populated with text

**Slow?** Expected — large-v3-turbo on CPU is 2–4× realtime. A 15s clip takes 30–60s. For a quick smoke test use `--model tiny` instead.

---

## Layer 4 — Full transcription with diarization

Adds pyannote speaker labels. Requires HF_TOKEN and accepted gated models.

```bash
HF_TOKEN=$(python3 -c "import json,pathlib; print(json.loads((pathlib.Path.home()/'.agent-config.json').read_text()).get('HF_TOKEN',''))")

python3 -m whisperx "$AUDIO" \
  --model large-v3-turbo \
  --compute_type int8 \
  --language None \
  --diarize \
  --hf_token "$HF_TOKEN" \
  --output_format json \
  --output_dir "$OUTDIR"

# Check for speaker labels
python3 -c "
import json
data = json.load(open('$OUTDIR/test.json'))
for seg in data['segments'][:5]:
    print(seg.get('speaker','NO_SPEAKER'), ':', seg['text'][:60])
"
```

**Pass:** segments show `SPEAKER_00`, `SPEAKER_01`, etc.
**Fail with 401:** HF_TOKEN invalid or gated models not accepted in browser.
**Fail with missing model:** run with `--min-speakers 1 --max-speakers 2` to help pyannote.

---

## Layer 5 — meeting-worker.py end-to-end (no Slack)

Manually inject a job into the queue and run the worker directly, bypassing Slack entirely.

```bash
# Step 1: inject a test job using the FLAC + dir from Layer 4
python3 -c "
import sys, uuid
from pathlib import Path
sys.path.insert(0, '.claude/hooks')
from varys_harness_db import get_db, enqueue_meeting

# Replace these with your actual test values
AUDIO   = '$AUDIO'
OUTDIR  = '$OUTDIR'
CHANNEL = 'REPLACE_WITH_YOUR_DM_CHANNEL_ID'   # e.g. D0XXXXXXX — find via Slack URL
THREAD  = '0000000000.000000'                  # fake ts — reply goes to channel root

db = get_db()
job_id = enqueue_meeting(db, 'test-meeting', AUDIO, OUTDIR, CHANNEL, THREAD)
print('Enqueued:', job_id)
"

# Step 2: run the worker directly
python3 .claude/hooks/meeting-worker.py --job-id <paste-job-id-from-above>
```

**Pass:** summary posted to Slack (or a Slack API error if channel/ts is fake), `test_summary.md` written to OUTDIR.

**Finding your DM channel ID:** open Slack in browser, go to your DM with Varys bot, the URL contains `/im/D0XXXXXXX` — that's the channel ID.

---

## Layer 6 — Full Slack round-trip

The real thing. Make sure the drain loop is running in a separate terminal first.

### Terminal 1 — drain loop
```bash
cd /home/shoaib/varys
bash varys-meeting-drain-loop.sh
```

### Terminal 2 — watch the queue
```bash
watch -n 2 'python3 -c "
import sys; sys.path.insert(0,\".claude/hooks\")
from varys_harness_db import get_db
db = get_db()
rows = db.execute(\"SELECT id, meeting_name, status, enqueued_at FROM meeting_queue ORDER BY enqueued_at DESC LIMIT 5\").fetchall()
for r in rows: print(r)
"'
```

### Slack (DM to Varys)

```
start recording layer-6-test
```

Expected reply: `🎙️ Recording *layer-6-test* started. Reply 'stop recording' to finish.`

Talk for 30–60 seconds (mixed English/Urdu if you want to test code-switching), then:

```
stop recording
```

Expected reply: `✅ Recording stopped. Transcription queued — I'll post the summary here when done. (~2–4× realtime on CPU so be patient 🐢)`

Watch Terminal 1 — the worker will start. After processing (2–4× the recording length), Varys replies in the same thread with the summary.

### What to verify in the summary

- [ ] Summary paragraph makes sense
- [ ] Decisions section populated (even if empty / "none identified")
- [ ] Action items section present
- [ ] Speaker labels present (`SPEAKER_00`, etc.) — names are a v2 feature
- [ ] Mixed Urdu handled gracefully (not garbled or dropped)

### Files written to vault
```bash
ls -la /home/shoaib/varys/vault/projects/meeting-notes/recordings/
```
Should contain: `.flac`, `_transcript.json`, `_summary.md`

---

## Failure triage

| Symptom | Likely cause | Fix |
|---|---|---|
| `start recording` not detected by Varys | Listener not running / job stuck in slack_queue | `pgrep -af varys-slack-listener`; check `~/.varys-harness/harness.db` slack_queue |
| ffmpeg exits immediately | PipeWire sources suspended | Play audio first; check source names with `pactl list sources short` |
| WhisperX OOM / killed | Too many threads on CPU | Add `--threads 4` to the `_run_whisperx` call in `meeting-worker.py` |
| pyannote 401 | HF_TOKEN wrong or gated model not accepted | Re-accept at hf.co/pyannote/speaker-diarization-3.1 |
| `No module named whisperx` in worker | WhisperX not on system Python | `pip install whisperx`; verify with `python3 -m whisperx --help` |
| Summary not posted to Slack | Slack post failed | Check `meeting_queue` status column; `failure_context` column has the error |
| `Already recording` on `start recording` | Stale `active_recording.json` from a crash | `rm ~/.varys-harness/active_recording.json` |

---

## Checking job status at any point

```bash
python3 -c "
import sys; sys.path.insert(0, '.claude/hooks')
from varys_harness_db import get_db
db = get_db()
rows = db.execute('''
    SELECT id, meeting_name, status, retry_count, failure_context, enqueued_at
    FROM meeting_queue ORDER BY enqueued_at DESC LIMIT 10
''').fetchall()
for r in rows:
    print(r)
"
```
