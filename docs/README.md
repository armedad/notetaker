# Notetaker

Local-first meeting notetaker that records system audio, transcribes with speaker ID, summarizes, extracts action items, and supports read-only sharing. Runs on macOS + Windows. Offline works; cloud improves summaries and sharing.

## Current Status

**What works right now:**
- Server starts on localhost:6684
- Root endpoint returns a health message + version
- `/api/health` returns status JSON
- Audio devices listed via `/api/audio/devices`
- Start/stop recording via `/api/recording/start` and `/api/recording/stop`
- Local transcription via `/api/transcribe` (faster-whisper)
- Simulated transcription from file via `/api/transcribe/simulate`
- Live transcription with real-time diarization (Diart)
- Cancellable transcription with proper finalization
- Diarization via WhisperX, pyannote, or Diart (configurable)
- JSON meeting storage via `/api/meetings`
- Meeting summarization via `/api/meetings/{id}/summarize`
- Auto-title generation on meeting completion
- Markdown export via `/api/meetings/{id}/export`
- **Unified LLM model selection:** Settings > AI Models picks one model for all tasks
- **Multi-provider support:** OpenAI, Anthropic, Gemini, Grok, Ollama, LMStudio
- Interactive attendee list with rename and AI-powered name suggestions

**Try it:** `/Users/chee/projects/notetaker/notetaker.sh` → open http://localhost:6684

**Logs:** Each server run writes to `/Users/chee/projects/notetaker/logs/server_YYYY-MM-DD_HH-MM-SS.log`

**Version:** Stored in `VERSION.txt` (format: `v.major.minor.build`). Increment build number per deploy.

**Launcher logs:** `/Users/chee/projects/notetaker/logs/launcher_YYYY-MM-DD_HH-MM-SS.log`

**Settings > AI Models:** Configure API keys and select which model to use for summarization, titles, and other LLM features. Format: `provider:model_id` (e.g., `openai:gpt-4o`).

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
