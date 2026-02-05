# Notetaker

Local-first meeting notetaker that records system audio, transcribes with speaker ID, summarizes, extracts action items, and supports read-only sharing. Runs on macOS + Windows. Offline works; cloud improves summaries and sharing.

## Current Status

**Phase 0 complete** — basic FastAPI skeleton.

**What works right now:**
- Server starts on localhost:8000
- Root endpoint returns a health message
- `/api/health` returns status JSON
- Audio devices listed via `/api/audio/devices`
- Start/stop recording via `/api/recording/start` and `/api/recording/stop`

**Try it:** `/Users/chee/projects/notetaker/notetaker.sh` → open http://localhost:6684

**Logs:** Each server run writes to `/Users/chee/projects/notetaker/logs/server_YYYY-MM-DD_HH-MM-SS.log`

**Version:** Stored in `VERSION.txt` (format: `v.major.minor.build`). Increment build number per deploy.

**Launcher logs:** `/Users/chee/projects/notetaker/logs/launcher_YYYY-MM-DD_HH-MM-SS.log`

**Next:** Phase 1 — audio capture foundation (verify + polish).

## Getting Started

1. Create a virtual environment
2. Install dependencies from `requirements.txt`
3. Run the server: `python -m uvicorn run:app --reload`

## Development

- Source of truth: `opportunity-assessment.md`
- Plan: `plan.md`
- Agent instructions: `AGENTS.MD`

## License

Private
