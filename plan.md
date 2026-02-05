# Notetaker Implementation Plan

Reference: `opportunity-assessment.md` for full spec and architecture.

---

## Phase 0: Environment Setup

**Goal:** Verify development environment, install dependencies, confirm we can run a basic FastAPI server.

**Files to create:**
- `requirements.txt`
- `run.py` (entry point)
- `app/__init__.py`
- `app/main.py` (FastAPI app)
- `config.json` (settings template)

**Done means:**
- Server starts on localhost:8000
- Browser shows "Notetaker API running" at root
- `/api/health` returns `{"status": "ok"}`

**Test it:**
1. Run the server
2. Open http://localhost:8000 in browser — see welcome message
3. Open http://localhost:8000/api/health — see JSON health response

---

## Phase 1: Audio Capture Foundation

**Goal:** Capture audio from virtual audio device and save to file. This is the core input mechanism.

**Prerequisites:** User has BlackHole (Mac) or VB-Cable (Windows) installed. Add setup instructions to README.

**Files to create/modify:**
- `app/services/audio_capture.py` — audio recording service
- `app/routers/recording.py` — API endpoints for start/stop
- `app/main.py` — register router
- `README.md` — add audio device setup instructions
- `data/recordings/` — directory for audio files

**Done means:**
- Can list available audio devices via API
- Can start recording from selected device
- Can stop recording and save WAV file
- Recording status visible via API

**Test it:**
1. Start server
2. Call `/api/audio/devices` — see list including virtual audio device
3. Play audio on computer (YouTube, music, etc.)
4. Call `/api/recording/start` with device selection
5. Wait 10 seconds
6. Call `/api/recording/stop`
7. Verify WAV file exists in `data/recordings/`
8. Play the WAV file — hear the captured audio

---

## Phase 2: Basic Web UI

**Goal:** Browser interface to control recording and see status. Replace API-only testing with visual interface.

**Files to create:**
- `app/static/index.html` — main page
- `app/static/app.js` — frontend logic
- `app/static/styles.css` — styling
- `app/main.py` — serve static files

**Done means:**
- Web UI shows at localhost:8000
- Can select audio device from dropdown
- Start/stop recording buttons work
- Recording status and duration display live
- Audio level meter shows input levels

**Test it:**
1. Open http://localhost:8000
2. See device dropdown populated
3. Select virtual audio device
4. Play audio on computer
5. Click "Start Recording" — see status change, duration counting, levels moving
6. Click "Stop Recording" — see confirmation
7. Recording saved (verify file exists)

---

## Phase 3: Whisper Transcription

**Goal:** Transcribe recorded audio using local Whisper. Modular provider interface for future swapping.

**Files to create/modify:**
- `app/services/transcription/__init__.py`
- `app/services/transcription/base.py` — abstract provider interface
- `app/services/transcription/whisper_local.py` — faster-whisper implementation
- `app/routers/transcription.py` — API endpoints
- `app/main.py` — register router
- `config.json` — add transcription settings (model size, etc.)

**Done means:**
- Can transcribe a WAV file via API
- Returns timestamped transcript segments
- Model size configurable (tiny/base/small/medium/large)
- Progress indication during transcription
- Provider interface allows easy addition of new providers

**Test it:**
1. Use a recording from Phase 2 (or provide test audio file)
2. Call `/api/transcribe` with audio file path
3. See progress updates (or poll status endpoint)
4. Receive transcript with timestamps
5. Verify transcript accuracy against audio content

---

## Phase 4: Speaker Diarization

**Goal:** Identify different speakers in the transcript. Add speaker labels to segments.

**Files to create/modify:**
- `app/services/diarization.py` — speaker identification service
- `app/services/transcription/whisper_local.py` — integrate diarization
- `app/routers/transcription.py` — include speaker info in response

**Done means:**
- Transcript segments include speaker labels (Speaker 1, Speaker 2, etc.)
- Different speakers correctly identified in multi-speaker audio
- Diarization can be disabled via config (faster processing)

**Test it:**
1. Record or use audio with multiple speakers (podcast, meeting recording)
2. Transcribe via API
3. Verify different speakers labeled correctly
4. Check speaker changes align with actual speaker changes in audio

---

## Phase 5: SQLite Storage & Meeting Model

**Goal:** Persist meetings, transcripts, and metadata. Foundation for dashboard and history.

**Files to create/modify:**
- `app/models.py` — SQLAlchemy models (Meeting, TranscriptSegment)
- `app/database.py` — database setup, session management
- `app/services/meeting_service.py` — CRUD operations
- `app/routers/meetings.py` — API endpoints
- `app/main.py` — register router, init database
- `data/notetaker.db` — SQLite database file

**Done means:**
- Meetings saved to database after recording + transcription
- Can list all meetings via API
- Can retrieve single meeting with full transcript
- Can update meeting title
- Can delete meeting

**Test it:**
1. Complete a recording and transcription
2. Verify meeting appears in `/api/meetings`
3. Get meeting details via `/api/meetings/{id}`
4. Update title via PATCH
5. Verify persistence across server restart

---

## Phase 6: LLM Summarization

**Goal:** Generate meeting summary and action items. Cloud when connected, local fallback.

**Files to create/modify:**
- `app/services/llm/__init__.py`
- `app/services/llm/base.py` — abstract provider interface
- `app/services/llm/ollama_provider.py` — local Ollama
- `app/services/llm/openai_provider.py` — OpenAI API
- `app/services/llm/anthropic_provider.py` — Anthropic API
- `app/services/summarization.py` — orchestrates LLM calls
- `app/routers/summarization.py` — API endpoints
- `app/models.py` — add summary, action_items to Meeting
- `config.json` — LLM provider settings, API keys

**Done means:**
- Can generate summary from transcript
- Can extract action items with assignee/description
- Automatic provider selection: cloud if connected + configured, else local
- Can force specific provider via API
- Summary and actions saved to meeting record

**Test it:**
1. Have Ollama running locally (or configure cloud API keys)
2. Take a meeting with transcript
3. Call `/api/meetings/{id}/summarize`
4. Receive summary and action items
5. Verify quality of output
6. Test with cloud disabled — falls back to local
7. Test with cloud enabled — uses cloud provider

---

## Phase 7: Full Meeting UI

**Goal:** Complete web interface for viewing and managing meetings.

**Files to modify:**
- `app/static/index.html` — add dashboard and meeting views
- `app/static/app.js` — add meeting management
- `app/static/styles.css` — polish styling

**Done means:**
- Dashboard shows list of past meetings (title, date, duration)
- Click meeting to view details
- Meeting view shows: transcript with speaker labels, summary, action items
- Can edit meeting title inline
- Can delete meeting
- Can trigger re-summarization
- Can copy transcript/summary to clipboard
- Responsive, clean design

**Test it:**
1. Create several test meetings
2. See all meetings in dashboard
3. Click through to meeting detail
4. Verify transcript displays with speaker labels
5. Verify summary and action items display
6. Edit title — persists
7. Copy to clipboard — works
8. Delete meeting — removed from dashboard

---

## Phase 8: Markdown Export

**Goal:** Export meeting notes to markdown file for use outside the app.

**Files to create/modify:**
- `app/services/export.py` — markdown generation
- `app/routers/meetings.py` — add export endpoint
- `app/static/app.js` — add export button

**Done means:**
- Can export meeting to markdown via API
- Markdown includes: title, date, summary, action items, full transcript
- Download button in UI triggers file download
- Clean, readable markdown format

**Test it:**
1. Open a meeting in UI
2. Click "Export to Markdown"
3. File downloads
4. Open in text editor — verify format and content

---

## Phase 9: Cloud Sharing

**Goal:** Generate shareable read-only links for meeting notes.

**Files to create/modify:**
- `app/services/sharing.py` — HTML generation, cloud upload
- `app/routers/sharing.py` — API endpoints
- `app/models.py` — add share_url to Meeting
- `app/static/app.js` — add share button
- `config.json` — cloud storage settings (S3/R2 credentials)
- `app/static/share-template.html` — template for shared page

**Done means:**
- Can generate shareable link for a meeting
- Link opens read-only HTML page with meeting notes
- Page is self-contained (no external dependencies)
- Link uses unguessable UUID
- Share URL saved to meeting record
- Works with S3, Cloudflare R2, or similar

**Test it:**
1. Configure cloud storage credentials
2. Open a meeting in UI
3. Click "Share"
4. Receive shareable URL
5. Open URL in incognito browser — see meeting notes
6. Verify no edit capabilities on shared page

---

## Phase 10: Polish & Robustness

**Goal:** Error handling, edge cases, logging, and overall polish.

**Files to modify:**
- All service files — add proper error handling
- `app/services/logging.py` — unified logging setup
- `app/routers/*.py` — consistent error responses
- `app/static/app.js` — error states in UI
- `README.md` — complete setup and usage documentation

**Done means:**
- Graceful handling of: no audio device, transcription failure, LLM timeout, cloud upload failure
- Clear error messages in UI
- Unified log file at `data/logs/notetaker.log`
- Log viewer at `/api/logs` for debugging
- README covers: installation, audio setup, configuration, usage

**Test it:**
1. Disconnect network — verify local-only mode works
2. Remove audio device — verify clear error
3. Kill Ollama — verify error message, not crash
4. Check logs capture all operations
5. Follow README from scratch on clean machine

---

## Future Phases (Not Planned Yet)

These are in the parking lot, to be planned when needed:

- Live transcription during recording
- Cloud transcription providers
- Collaborative editing
- Team workspaces
- Task tool integrations
- Zapier integration
- Calendar integration
