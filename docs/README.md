# Notetaker

Local-first meeting notetaker that records system audio, transcribes with speaker ID, summarizes, extracts action items, and supports read-only sharing. Runs on macOS + Windows. Offline works; cloud improves summaries and sharing.

## Current Status

**Phase 0 complete** — basic FastAPI skeleton.

**What works right now:**
- Server starts on localhost:6684
- Root endpoint returns a health message + version
- `/api/health` returns status JSON
- Audio devices listed via `/api/audio/devices`
- Start/stop recording via `/api/recording/start` and `/api/recording/stop`
- Local transcription via `/api/transcribe` (faster-whisper)
- Optional diarization via config (WhisperX or pyannote)
- JSON meeting storage via `/api/meetings`
- Meeting summarization via `/api/meetings/{id}/summarize`
- Markdown export via `/api/meetings/{id}/export`

**Try it:** `/Users/chee/projects/notetaker/notetaker.sh` → open http://localhost:6684

**Logs:** Each server run writes to `/Users/chee/projects/notetaker/logs/server_YYYY-MM-DD_HH-MM-SS.log`

**Version:** Stored in `VERSION.txt` (format: `v.major.minor.build`). Increment build number per deploy.

**Launcher logs:** `/Users/chee/projects/notetaker/logs/launcher_YYYY-MM-DD_HH-MM-SS.log`

**Next:** Continue Phase 8 — full meeting UI + polish (cleanup main window complete).

## Getting Started

1. Create a virtual environment
2. Install dependencies from `requirements.txt`
3. Run the server: `python -m uvicorn run:app --reload`

## Development

- Source of truth: `docs/specs/opportunity-assessment.md`
- Plan: `docs/plans/plan.md`
- Agent instructions: `docs/AGENTS.MD`

## License

Public
