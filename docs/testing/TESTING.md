# Testing

## Phase 0 — Server Skeleton

1. Start the server: `/Users/chee/projects/notetaker/notetaker.sh`
2. Open http://localhost:6684  
   Expected: `{"message":"Notetaker API running"}`
3. Open http://localhost:6684/api/health  
   Expected: `{"status":"ok"}`

## Phase 1 — Audio Capture (API)

1. Start the server: `/Users/chee/projects/notetaker/notetaker.sh`
2. List devices:
   - `curl -s http://127.0.0.1:6684/api/audio/devices`
   - Find your virtual audio device index (BlackHole or VB-Cable)
3. Start recording:
   - `curl -s -X POST http://127.0.0.1:6684/api/recording/start -H "Content-Type: application/json" -d '{"device_index": <INDEX>}'`
4. Play audio on your computer for ~10 seconds
5. Stop recording:
   - `curl -s -X POST http://127.0.0.1:6684/api/recording/stop`
6. Verify a WAV file appears under `data/recordings/` and plays back with the recorded audio

## Phase 3 — Transcription (API)

1. Start the server: `/Users/chee/projects/notetaker/notetaker.sh`
2. Record a short clip (Phase 1 steps) to produce a WAV file.
3. Transcribe:
   - `curl --max-time 120 -s -X POST http://127.0.0.1:6684/api/transcribe -H "Content-Type: application/json" -d '{"audio_path": "/Users/chee/projects/notetaker/data/recordings/<FILENAME>.wav"}'`
4. Expected:
   - JSON response with `segments` and timestamps

## Phase 4 — Live Transcription (Planned)

1. Start the server: `/Users/chee/projects/notetaker/notetaker.sh`
2. Start recording with live transcription enabled.
3. Speak and verify transcript updates within a few seconds.
4. Stop recording and confirm final transcript completeness.

## Phase 5 — Speaker Diarization (Optional)

1. Add Hugging Face token to `config.json` under `diarization.hf_token`.
2. Set `diarization.enabled` to `true`.
3. Use a multi-speaker audio file and run `/api/transcribe`.
4. Expected:
   - Transcript segments include `speaker` labels.

## UI — Diarization (WhisperX)

1. Open http://localhost:6684/settings
2. In Diarization settings:
   - Select provider "whisperx"
   - Choose CPU or CUDA (CUDA should be disabled if unavailable)
   - Adjust performance slider (Faster ↔ More accurate)
3. Save settings.
4. Run a multi-speaker transcription and confirm speaker labels appear.

## Phase 6 — JSON Meetings (API)

1. Start the server: `/Users/chee/projects/notetaker/notetaker.sh`
2. Record a short clip and stop (Phase 1).
3. Confirm meeting created:
   - `curl -s http://127.0.0.1:6684/api/meetings`
4. Transcribe the recording.
5. Confirm transcript stored in meeting:
   - `curl -s http://127.0.0.1:6684/api/meetings/<MEETING_ID>`

## Phase 7 — Summarization

1. Ensure you have a meeting with transcript.
2. If using Ollama, start it locally.
3. Summarize:
   - `curl -s -X POST http://127.0.0.1:6684/api/meetings/<MEETING_ID>/summarize -H "Content-Type: application/json" -d '{"provider": "ollama"}'`
4. Expected:
   - JSON response with `summary` and `action_items`

## Phase 9 — Markdown Export

1. Select a meeting with transcript.
2. Export markdown:
   - `curl -s http://127.0.0.1:6684/api/meetings/<MEETING_ID>/export`
3. Expected:
   - Markdown with title, date, summary, actions, transcript

## UI — Auto Meeting Title

1. Start a meeting and let transcript + summary update at least once.
2. Confirm title stays default until summary is meaningful.
3. Confirm auto title appears once summary is meaningful.
4. Manually edit title on meeting page and save.
5. Wait for another summary refresh; confirm title does not change.
6. End meeting and confirm final auto title re-runs only if title source is auto.

## UI — Smart Real-Time Summary Parsing

1. Start a meeting and keep it running for > 1 minute.
2. Click "Debug summary parsing" in meeting page.
3. Confirm streaming text fills first, then draft grows in full sentences.
4. Confirm summarized summary grows as topics complete.
5. Confirm interim summary reflects the most recent topic.
6. Confirm debug panes auto-scroll as text updates.

## UI — Cleanup Main Window

1. Open http://localhost:6684
2. Header shows Settings button and Profile dropdown on the right.
3. Click Settings -> navigates to /settings.
4. Profile dropdown opens and shows login/logout placeholder.
5. Recording uses a single toggle button (Start/Stop).
6. Meetings list rows show only title + date/time.
7. In-progress meeting shows "In progress" in the row metadata.
8. Empty meeting list shows no placeholder text.
9. Clicking a meeting row opens `/meeting?id=...`.
10. Meeting title is editable only on the meeting page.
