# Notetaker Specification

> **Note:** The detailed spec is in `docs/specs/opportunity-assessment.md`. This file provides a quick reference.

## Problem Statement

Meeting notes are tedious to take manually. Existing tools require cloud connectivity or lack speaker identification. Need a local-first solution that captures audio, transcribes with speaker ID, and generates summaries automatically.

## Target User

Personal tool for Chee. Dev-friendly setup is acceptable.

## Core Features (Implemented)

- **Audio capture:** Record system audio from virtual audio devices (BlackHole, ZoomAudioDevice)
- **Transcription:** Local Whisper via faster-whisper
- **Diarization:** Speaker identification via WhisperX, pyannote, or Diart (real-time)
- **Summarization:** LLM-powered meeting summaries and action items
- **Auto-titles:** AI-generated meeting titles based on content
- **Unified model selection:** One model choice for all LLM tasks
- **Multi-provider LLM:** OpenAI, Anthropic, Gemini, Grok, Ollama, LMStudio
- **Meeting management:** List, view, edit, export meetings
- **Interactive attendees:** Rename speakers, AI-powered name suggestions

## Technical Stack

- Backend: Python + FastAPI
- Storage: JSON file-based (meetings.json)
- Transcription: faster-whisper
- Diarization: WhisperX, pyannote-audio, Diart
- LLM: Dynamic provider selection via config
- Frontend: Vanilla JS web UI

## Config Structure

```json
{
  "models": {
    "selected_model": "openai:gpt-4o",
    "registry": [...]
  },
  "providers": {
    "openai": { "api_key": "...", "base_url": "..." },
    "anthropic": { "api_key": "...", "base_url": "..." },
    ...
  }
}
```

## Success Criteria

- Can record any meeting with one click
- Get accurate transcripts with speaker identification
- Get useful summaries and action items automatically
- Works offline (with Ollama/LMStudio)
- Better summaries when connected to cloud providers
