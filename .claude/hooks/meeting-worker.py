#!/usr/bin/env python3
"""
meeting-worker.py — Process a single meeting_queue job.

Usage:
    python3 meeting-worker.py --job-id <row_id>

Steps:
  1. Load job from meeting_queue
  2. Mark job processing
  3. Run WhisperX to transcribe + diarize
  4. Build speaker-segmented transcript string
  5. Call Claude via claude -p with a summarisation prompt
  6. Post summary to Slack origin thread
  7. Save transcript JSON + summary markdown
  8. Mark job done

Exit 0 = done. Exit 1 = failed.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
REPO  = HOOKS.parent.parent
sys.path.insert(0, str(HOOKS))

from varys_harness_db import (
    get_db,
    mark_meeting_processing,
    mark_meeting_done,
    mark_meeting_retry,
)
from agent_config import cfg
from varys_log import klog_error, klog_cron


def _load_bot_token() -> str:
    slack_cfg = Path.home() / ".claude" / "hooks" / ".slack"
    if slack_cfg.exists():
        for line in slack_cfg.read_text().splitlines():
            if line.startswith("BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("SLACK_BOT_TOKEN", "")


def _slack_post(token: str, channel: str, thread_ts: str, text: str) -> None:
    payload = json.dumps({"channel": channel, "thread_ts": thread_ts, "text": text}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        resp = json.loads(r.read())
    if not resp.get("ok"):
        raise RuntimeError(f"Slack post failed: {resp.get('error')}")


def _claude_bin() -> str:
    c = shutil.which("claude")
    if c:
        return c
    hits = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/claude")))
    return hits[-1] if hits else "claude"


def _check_whisperx() -> bool:
    """Return True if whisperx is importable via python3 -m whisperx."""
    result = subprocess.run(
        [sys.executable, "-m", "whisperx", "--help"],
        capture_output=True, timeout=10,
    )
    return result.returncode == 0


def _run_whisperx(audio_path: str, output_dir: str, hf_token: str) -> tuple[int, str]:
    """
    Run WhisperX on audio_path. Returns (returncode, stderr).
    Outputs a JSON file in output_dir matching the audio filename stem.
    """
    cmd = [
        sys.executable, "-m", "whisperx",
        audio_path,
        "--model", "large-v3-turbo",
        "--compute_type", "int8",
        "--language", "None",
        "--output_format", "json",
        "--output_dir", output_dir,
        "--diarize",
    ]
    if hf_token:
        cmd += ["--hf_token", hf_token]

    result = subprocess.run(
        cmd,
        capture_output=True, text=True,
        cwd=str(REPO), timeout=3600,  # 1hr hard cap — large files on CPU are slow
    )
    return result.returncode, result.stderr


def _build_transcript_string(whisperx_data: dict) -> str:
    """
    Convert WhisperX JSON output into a speaker-segmented string.
    WhisperX diarize output has segments with optional 'speaker' key.
    Falls back to 'UNKNOWN' if diarization was skipped.
    """
    lines = []
    for seg in whisperx_data.get("segments", []):
        speaker = seg.get("speaker", "UNKNOWN")
        text    = seg.get("text", "").strip()
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def _build_summary_prompt(meeting_name: str, date_str: str, transcript: str) -> str:
    return f"""You are Varys, Shoaib's personal AI agent. A meeting was just recorded.

Meeting name: {meeting_name}
Date: {date_str}

Below is a speaker-diarized transcript (SPEAKER_00, SPEAKER_01, etc.):

{transcript}

Write a meeting summary in this format:

## Summary
2-3 sentence overview of what was discussed.

## Decisions
- [decision 1]
- [decision 2]

## Action Items
- [ ] [what] — [who if mentioned]

## Notes
Any important context, concerns raised, or follow-ups.

Notes:
- The meeting is in mixed English and Urdu (including Roman Urdu). Handle gracefully — summarize in English.
- If a speaker isn't named, use their label (SPEAKER_00, etc.) and note that names can be assigned via Slack reply.
- Keep it concise. Shoaib will glance at this, not read it carefully.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()

    t0 = time.time()
    db  = get_db()
    row = db.execute(
        "SELECT id, meeting_name, audio_path, output_dir, channel, thread_ts, "
        "retry_count, failure_context "
        "FROM meeting_queue WHERE id=? AND status IN ('pending', 'processing')",
        (args.job_id,),
    ).fetchone()

    if not row:
        print(f"[meeting-worker] job {args.job_id} not found", file=sys.stderr)
        return 1

    (row_id, meeting_name, audio_path, output_dir,
     channel, thread_ts, retry_count, failure_context) = row

    mark_meeting_processing(db, row_id)

    bot_token = _load_bot_token()
    hf_token  = cfg("HF_TOKEN", "")

    if not hf_token:
        print(
            "[meeting-worker] WARNING: HF_TOKEN not set — diarization will be skipped by WhisperX",
            file=sys.stderr,
        )

    # ── Step 1: verify WhisperX is available ──────────────────────────────────
    if not _check_whisperx():
        msg = "WhisperX not installed. Run: pip install whisperx"
        print(f"[meeting-worker] {msg}", file=sys.stderr)
        if bot_token:
            try:
                _slack_post(bot_token, channel, thread_ts, msg)
            except Exception:
                pass
        mark_meeting_retry(db, row_id, failure_context=msg)
        return 1

    # ── Step 2: verify audio file exists ──────────────────────────────────────
    if not Path(audio_path).exists():
        msg = f"Audio file not found: {audio_path}"
        print(f"[meeting-worker] {msg}", file=sys.stderr)
        klog_error("meeting_worker_no_audio", component="meeting-worker",
                   exc=FileNotFoundError(msg))
        mark_meeting_retry(db, row_id, failure_context=msg)
        return 1

    # ── Step 3: run WhisperX ──────────────────────────────────────────────────
    print(f"[meeting-worker] transcribing {audio_path} …")
    try:
        rc, stderr = _run_whisperx(audio_path, output_dir, hf_token)
    except subprocess.TimeoutExpired:
        msg = "WhisperX timed out after 1 hour"
        klog_error("meeting_worker_whisperx_timeout", component="meeting-worker",
                   exc=TimeoutError(msg))
        mark_meeting_retry(db, row_id, failure_context=msg)
        if bot_token:
            try:
                _slack_post(bot_token, channel, thread_ts,
                            f"Transcription of *{meeting_name}* timed out. Will retry.")
            except Exception:
                pass
        return 1
    except Exception as exc:
        klog_error("meeting_worker_whisperx_run", exc, component="meeting-worker")
        mark_meeting_retry(db, row_id, failure_context=str(exc)[:500])
        return 1

    if rc != 0:
        msg = f"WhisperX exited with code {rc}: {stderr[:500]}"
        klog_error("meeting_worker_whisperx_nonzero", component="meeting-worker",
                   exc=RuntimeError(msg))
        mark_meeting_retry(db, row_id, failure_context=msg)
        if bot_token:
            try:
                _slack_post(bot_token, channel, thread_ts,
                            f"Transcription of *{meeting_name}* failed (whisperx rc={rc}). "
                            "Will retry.")
            except Exception:
                pass
        return 1

    # ── Step 4: parse WhisperX JSON ───────────────────────────────────────────
    audio_stem = Path(audio_path).stem
    transcript_json_path = Path(output_dir) / f"{audio_stem}.json"

    if not transcript_json_path.exists():
        msg = f"WhisperX did not produce expected output: {transcript_json_path}"
        klog_error("meeting_worker_no_transcript_json", component="meeting-worker",
                   exc=FileNotFoundError(msg))
        mark_meeting_retry(db, row_id, failure_context=msg)
        return 1

    try:
        whisperx_data = json.loads(transcript_json_path.read_text())
    except Exception as exc:
        klog_error("meeting_worker_parse_json", exc, component="meeting-worker")
        mark_meeting_retry(db, row_id, failure_context=str(exc)[:500])
        return 1

    transcript_str = _build_transcript_string(whisperx_data)
    if not transcript_str.strip():
        transcript_str = "(no speech detected)"

    # ── Step 5: summarise via Claude ──────────────────────────────────────────
    date_str = datetime.now().strftime("%Y-%m-%d")
    prompt   = _build_summary_prompt(meeting_name, date_str, transcript_str)

    # Write prompt to temp file to avoid shell-quoting issues with mixed-language text
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as pf:
        pf.write(prompt)
        prompt_path = pf.name

    try:
        summary_result = subprocess.run(
            [_claude_bin(), "--dangerously-skip-permissions", "--print", "-p", prompt],
            capture_output=True, text=True,
            cwd=str(REPO), timeout=120,
            env={**os.environ, "VARYS_CONTENT_AGENT": "1"},
        )
    except Exception as exc:
        klog_error("meeting_worker_claude_run", exc, component="meeting-worker")
        Path(prompt_path).unlink(missing_ok=True)
        mark_meeting_retry(db, row_id, failure_context=str(exc)[:500])
        return 1
    finally:
        Path(prompt_path).unlink(missing_ok=True)

    if summary_result.returncode != 0 or not summary_result.stdout.strip():
        msg = (summary_result.stderr.strip() or "no output")[:500]
        klog_error("meeting_worker_claude_failed", component="meeting-worker",
                   exc=RuntimeError(msg))
        mark_meeting_retry(db, row_id, failure_context=msg)
        return 1

    summary_text = summary_result.stdout.strip()

    # ── Step 6: save outputs ──────────────────────────────────────────────────
    # transcript JSON is already at transcript_json_path from whisperx
    summary_md_path = Path(output_dir) / f"{audio_stem}_summary.md"
    try:
        summary_md_path.write_text(
            f"# Meeting: {meeting_name}\n\nDate: {date_str}\n\n{summary_text}\n",
            encoding="utf-8",
        )
    except Exception as exc:
        klog_error("meeting_worker_save_summary", exc, component="meeting-worker")
        # Non-fatal — we still post to Slack

    # ── Step 7: post to Slack ─────────────────────────────────────────────────
    if bot_token:
        try:
            slack_body = (
                f"*Meeting summary: {meeting_name}* ({date_str})\n\n"
                f"{summary_text}"
            )
            _slack_post(bot_token, channel, thread_ts, slack_body)
        except Exception as exc:
            klog_error("meeting_worker_slack_post", exc, component="meeting-worker")
            # Non-fatal — summary saved to disk

    # ── Step 8: mark done ─────────────────────────────────────────────────────
    mark_meeting_done(db, row_id)
    duration_ms = round((time.time() - t0) * 1000)
    klog_cron("meeting-worker", status="ok", duration_ms=duration_ms,
              items=1, meeting_name=meeting_name)
    print(f"[meeting-worker] done: {row_id} ({meeting_name}) in {duration_ms}ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
