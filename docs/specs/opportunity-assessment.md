# Notetaker - Opportunity Assessment

## Objective

Build a local-first meeting notetaker that captures audio, transcribes it, and enables AI-powered summarization and action extraction. Runs on both Windows and Mac without requiring cloud connectivity, but leverages cloud services when available for better quality and sharing.

## Target Customer

Personal tool for Chee. Dev-friendly setup is acceptable. Optimized for one user's workflow.

## Success

- Can record any meeting (Zoom, Meet, Teams) with one click
- Get accurate transcripts with speaker identification
- Get useful summaries and action items automatically
- Works fully offline
- Better summaries when connected to cloud
- Can share meeting notes with others via link

## What I Believe

- Local-first is essential for privacy and offline capability
- Cross-platform (Windows + Mac) is a hard requirement
- Python local server with web frontend is the right architecture (similar to cold-local-llm-server)
- System audio loopback gives best transcription quality
- Local Whisper is good enough for transcription
- Cloud APIs (OpenAI/Anthropic) are noticeably better for summarization
- Read-only sharing is sufficient for v1, but architecture should support collaborative editing later

## What I Need to Research

- System audio capture: BlackHole (Mac), VB-Cable (Windows)
- Whisper local deployment options and speaker diarization
- Local LLM options for offline summarization (Ollama)
- Simple cloud sharing mechanism (signed URLs, simple hosting)

## Solution Direction

**Architecture: Python Server + Web UI**
- FastAPI backend
- Browser-based frontend (React/TypeScript/Tailwind or vanilla)
- User opens localhost in browser
- Similar pattern to cold-local-llm-server

---

# Detailed Spec

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         User's Machine                          │
│  ┌──────────────┐    ┌──────────────────────────────────────┐  │
│  │ Virtual Audio│    │           Notetaker Server           │  │
│  │   Device     │───▶│  ┌─────────┐  ┌─────────────────┐   │  │
│  │ (BlackHole/  │    │  │ Audio   │  │ Whisper         │   │  │
│  │  VB-Cable)   │    │  │ Capture │─▶│ Transcription   │   │  │
│  └──────────────┘    │  └─────────┘  │ + Diarization   │   │  │
│         ▲            │               └────────┬────────┘   │  │
│         │            │                        │            │  │
│  ┌──────┴──────┐     │               ┌────────▼────────┐   │  │
│  │ Meeting App │     │               │ LLM Processing  │   │  │
│  │ (Zoom/Meet/ │     │               │ (Local/Cloud)   │   │  │
│  │  Teams)     │     │               │ - Summary       │   │  │
│  └─────────────┘     │               │ - Actions       │   │  │
│                      │               └────────┬────────┘   │  │
│  ┌─────────────┐     │                        │            │  │
│  │  Browser    │◀────┼────────────────────────┘            │  │
│  │  (Web UI)   │     │               ┌─────────────────┐   │  │
│  └─────────────┘     │               │ SQLite Storage  │   │  │
│                      │               └─────────────────┘   │  │
│                      └──────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ When connected
                                ▼
                    ┌───────────────────────┐
                    │    Cloud Services     │
                    │  - OpenAI/Anthropic   │
                    │  - Sharing (CDN/S3)   │
                    └───────────────────────┘
```

## Core Components

### 1. Audio Capture Service
- Captures system audio via virtual audio device
- Mac: BlackHole (requires one-time install)
- Windows: VB-Cable (requires one-time install)
- Records to WAV/FLAC for processing
- Shows recording status (duration, levels)
- Start/stop via web UI

### 2. Transcription Engine
- **Modular provider interface** — easy to swap implementations
- Default: Local Whisper (faster-whisper for speed)
- Future: Deepgram, AssemblyAI, OpenAI Whisper API
- **Diarization options:**
  - WhisperX (batch, most accurate)
  - pyannote-audio (batch)
  - Diart (real-time, for live transcription)
- **Unified TranscriptionPipeline:** Centralizes all post-audio processing (transcription, diarization, meeting store updates, summarization)
- **Simulated transcription:** File-based transcription that mimics live recording flow
- **Cancellation support:** Transcription jobs can be stopped mid-processing
- Outputs timestamped transcript with speaker labels
- Provider selection via config (not hardcoded)

### 3. LLM Processing
- **Unified model selection:** User picks one model in Settings > AI Models, used for all LLM tasks
- **Supported providers:**
  - OpenAI (GPT-4o, GPT-5.x, etc.)
  - Anthropic (Claude 3.x, 4.x)
  - Google Gemini
  - xAI Grok
  - Ollama (local models)
  - LMStudio (local models)
- **Dynamic configuration:** Model selection stored in `config.json` under `models.selected_model` (format: `provider:model_id`)
- **Provider credentials:** API keys and base URLs stored in `config.json` under `providers.<provider_name>`
- User can force local-only mode (Ollama/LMStudio)
- Generates:
  - Meeting summary (key points, decisions)
  - Action items (who, what, when if mentioned)
  - Auto-generated meeting titles
  - Optional: topic segmentation
  - Optional: AI-powered attendee name suggestions

### 4. Storage
- SQLite database for meetings, transcripts, summaries
- File storage for audio recordings (optional retention)
- Markdown export for each meeting
- All data stays local by default

### 5. Web UI
- Dashboard: list of past meetings
- Recording view: start/stop, live audio levels, status
- Meeting view: transcript, summary, action items
- Settings: audio device selection, LLM preferences, API keys
- Share: generate shareable link (when connected)

### 6. Sharing Service
- Generate read-only HTML snapshot of meeting notes
- Upload to simple cloud storage (S3, Cloudflare R2, or similar)
- Return shareable URL
- No account required for viewers
- Designed to support collaborative editing later (data model supports it)

## Data Model

```
Meeting
├── id (uuid)
├── title (auto-generated or user-edited)
├── created_at
├── duration_seconds
├── audio_path (optional, if retained)
├── transcript_segments[]
│   ├── id
│   ├── speaker_id
│   ├── start_time
│   ├── end_time
│   └── text
├── summary (markdown)
├── action_items[]
│   ├── id
│   ├── assignee (extracted or null)
│   ├── description
│   └── due_date (extracted or null)
├── share_url (null if not shared)
└── settings_snapshot (LLM used, etc.)
```

## Key User Flows

### Recording a Meeting
1. User opens web UI (localhost:8000)
2. Clicks "Start Recording"
3. Server begins capturing from virtual audio device
4. Live indicator shows recording status and duration
5. User clicks "Stop Recording"
6. Server processes audio → transcript → summary → actions
7. Meeting appears in dashboard with all outputs

### Viewing a Meeting
1. User clicks meeting from dashboard
2. Sees: transcript (with speaker labels), summary, action items
3. Can edit title, copy text, export to markdown
4. Can regenerate summary with different LLM

### Sharing a Meeting
1. User clicks "Share" on a meeting
2. Server generates static HTML snapshot
3. Uploads to cloud storage
4. Returns shareable URL
5. User copies/sends link
6. Recipients view read-only notes (no login required)

## Technical Requirements

### Platform Support
- macOS 12+ (Apple Silicon and Intel)
- Windows 10/11
- Python 3.10+

### Dependencies (Key)
- FastAPI (web server)
- faster-whisper or whisper.cpp (transcription)
- pyannote-audio (speaker diarization)
- Ollama (local LLM)
- SQLite (storage)
- sounddevice or pyaudio (audio capture)
- boto3 or equivalent (cloud upload for sharing)

### Performance Targets
- Transcription: Process 1 hour of audio in <10 minutes on M1 Mac
- Summary generation: <30 seconds for typical meeting
- UI: Responsive, no blocking during processing

### Security
- API keys stored in local config file (not in DB)
- Shared links use unguessable UUIDs
- No authentication for local access (single-user)
- HTTPS for cloud uploads

## AI Agent Self-Sufficiency Features

### Logging
- All components log to single unified log file
- Log viewer endpoint in web UI for easy access
- Structured logging (JSON) for easy parsing
- Log levels: DEBUG for development, INFO for production

### Testing Without Audio
- Dev mode: can load sample audio files instead of live capture
- Test fixtures for transcript → summary pipeline
- Health check endpoints for all services
- Curl-testable API endpoints

### Status Dashboard
- /api/health — overall system health
- /api/status — current recording state, processing queue
- Shows: Whisper model loaded, Ollama connected, cloud connectivity

## Out of Scope (Parking Lot)

- Collaborative real-time editing
- Team workspaces / multi-user
- Task tool integrations (Todoist, Asana, Linear)
- Zapier integration
- Cloud transcription providers (architecture supports it, not implemented in v1)
- Mobile apps
- Calendar integration (auto-detect meetings)
- Video recording

## Recently Implemented

- **Live transcription:** Real-time microphone transcription with Diart diarization support
- **Unified model selection:** Single model choice in Settings applies to all LLM tasks
- **Multi-provider LLM support:** OpenAI, Anthropic, Gemini, Grok, Ollama, LMStudio
- **Interactive attendee management:** Rename speakers, AI-powered name suggestions
- **Cancellable transcription:** Stop mid-processing with proper finalization
- **Transcription finalization:** Summarization and title generation on stop

## Open Questions Resolved

| Question | Decision |
|----------|----------|
| Platform | Python server + web UI |
| Audio capture | System audio loopback |
| Transcription | Local Whisper (modular, can swap to cloud later) |
| Summarization | Cloud when connected, local fallback |
| Speaker ID | Yes, via diarization |
| Sharing | Read-only links, cloud-hosted |
| Collaboration | Deferred, but data model supports it |
