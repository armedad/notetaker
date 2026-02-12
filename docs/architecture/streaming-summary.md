# Real-Time Event Architecture

This document describes the SSE-based real-time event system used in the Notetaker application for all meeting updates, including streaming summaries.

## Overview

The application uses Server-Sent Events (SSE) for **all** real-time updates between backend and frontend. This eliminates polling and provides immediate updates for:
- Summary generation (progressive, like ChatGPT)
- Transcript updates (new segments, speaker changes)
- Meeting status changes
- Title updates
- Attendee changes
- Finalization progress

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              BACKEND                                     │
│                                                                          │
│  ┌──────────────────────┐    ┌──────────────────────────────────────┐   │
│  │ Transcription        │    │ Manual Summarize Button              │   │
│  │ Finalization         │    │ (POST /api/meetings/{id}/summarize)  │   │
│  └──────────┬───────────┘    └──────────────────┬───────────────────┘   │
│             │                                    │                       │
│             └──────────────┬─────────────────────┘                       │
│                            │                                             │
│                            v                                             │
│              ┌─────────────────────────────┐                            │
│              │   Summarization Service     │                            │
│              │   summarize_stream()        │                            │
│              └─────────────┬───────────────┘                            │
│                            │                                             │
│                            v                                             │
│              ┌─────────────────────────────┐                            │
│              │   LLM Provider              │                            │
│              │   _call_api_stream()        │                            │
│              │   (Ollama/OpenAI/Anthropic) │                            │
│              └─────────────┬───────────────┘                            │
│                            │                                             │
│                            │ yields tokens                               │
│                            v                                             │
│              ┌─────────────────────────────┐                            │
│              │   MeetingStore              │                            │
│              │   publish_event()           │                            │
│              └─────────────┬───────────────┘                            │
│                            │                                             │
│                            │ Events:                                     │
│                            │ - summary_start                             │
│                            │ - summary_token {text: "accumulated..."}   │
│                            │ - summary_complete {text: "final..."}      │
│                            v                                             │
│              ┌─────────────────────────────┐                            │
│              │   SSE Endpoint              │                            │
│              │   GET /api/meetings/events  │                            │
│              └─────────────┬───────────────┘                            │
│                            │                                             │
└────────────────────────────┼────────────────────────────────────────────┘
                             │
                             │ Server-Sent Events (SSE)
                             │
┌────────────────────────────┼────────────────────────────────────────────┐
│                            v                              FRONTEND       │
│              ┌─────────────────────────────┐                            │
│              │   EventSource               │                            │
│              │   subscribeToMeetingEvents()│                            │
│              └─────────────┬───────────────┘                            │
│                            │                                             │
│                            v                                             │
│              ┌─────────────────────────────┐                            │
│              │   handleMeetingEvent()      │                            │
│              │                             │                            │
│              │   summary_start:            │                            │
│              │     → Clear summary boxes   │                            │
│              │                             │                            │
│              │   summary_token:            │                            │
│              │     → Update text display   │                            │
│              │     → Auto-scroll           │                            │
│              │                             │                            │
│              │   summary_complete:         │                            │
│              │     → Finalize display      │                            │
│              │     → Refresh meeting       │                            │
│              └─────────────────────────────┘                            │
│                                                                          │
│              ┌─────────────────────────────┐                            │
│              │   UI Elements               │                            │
│              │   - #manual-summary         │  ← Debug panel textarea    │
│              │   - #summary-output         │  ← Main summary display    │
│              └─────────────────────────────┘                            │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

## Event Flow

### 1. Summary Generation Starts

When transcription finalizes or user clicks summarize:

```python
# Backend emits start event
meeting_store.publish_event("summary_start", meeting_id)
```

Frontend receives and clears the summary display areas.

### 2. Tokens Stream Progressively

As the LLM generates each token:

```python
# Backend accumulates and emits
accumulated_summary += token
meeting_store.publish_event(
    "summary_token",
    meeting_id,
    {"text": accumulated_summary}
)
```

Frontend updates the display with the accumulated text, providing real-time feedback.

### 3. Summary Completes

When generation finishes:

```python
# Backend emits completion and saves
meeting_store.publish_event(
    "summary_complete",
    meeting_id,
    {"text": final_summary}
)
meeting_store.add_summary(meeting_id, summary=final_summary, ...)
```

Frontend finalizes the display and refreshes the meeting data.

## Key Design Decisions

### Single Flow, Not Dual

There is only ONE summarization code path. The backend always:
1. Generates the summary (streaming from LLM)
2. Emits events as tokens arrive
3. Saves the final result

The frontend is a passive observer - it subscribes to events and displays them if connected.

### Backend Independence

The backend does NOT depend on the frontend being connected:
- If frontend is open: User sees progressive updates
- If frontend is closed: Summary still generates and saves
- User can reopen the page later and see the completed summary

### No Race Conditions

Previous approaches had race conditions with:
- Frontend "claiming" summarization
- Backend waiting for frontend
- Timeouts and flag checks

This architecture eliminates all of that - backend just works, frontend just listens.

### No Polling

The frontend no longer polls the backend for updates. Instead:
- On page load: Subscribe to SSE, do one initial fetch
- During meeting: All updates come via SSE events
- No periodic `setInterval` refreshes
- Lower server load, instant updates, better UX

## Files Involved

### Backend

| File | Purpose |
|------|---------|
| `app/services/llm/base.py` | Base class with `prompt_stream()` abstract method |
| `app/services/llm/ollama_provider.py` | Ollama streaming implementation |
| `app/services/llm/openai_provider.py` | OpenAI streaming implementation |
| `app/services/llm/anthropic_provider.py` | Anthropic streaming implementation |
| `app/services/summarization.py` | `summarize_stream()` method |
| `app/services/meeting_store.py` | `publish_event()` with data payload |
| `app/services/transcription_pipeline.py` | Finalization flow using streaming |
| `app/routers/meetings.py` | SSE endpoint `/api/meetings/events` |

### Frontend

| File | Purpose |
|------|---------|
| `app/static/meeting.js` | `subscribeToMeetingEvents()`, `handleMeetingEvent()` |

## SSE Event Format

Events are JSON objects sent via Server-Sent Events:

### Summary Events
```javascript
// Summary start - clears summary display
{"type": "summary_start", "meeting_id": "abc123", "timestamp": "..."}

// Summary token (sent many times) - progressive update
{"type": "summary_token", "meeting_id": "abc123", "data": {"text": "The meeting discussed..."}, "timestamp": "..."}

// Summary complete - finalizes display
{"type": "summary_complete", "meeting_id": "abc123", "data": {"text": "The meeting discussed project timelines..."}, "timestamp": "..."}
```

### Status Events
```javascript
// Meeting status changed
{"type": "status_updated", "meeting_id": "abc123", "data": {"status": "completed", "ended_at": "2024-..."}, "timestamp": "..."}

// Title updated (manual or auto-generated)
{"type": "title_updated", "meeting_id": "abc123", "data": {"title": "Q4 Planning Meeting", "source": "auto"}, "timestamp": "..."}

// Attendees list changed
{"type": "attendees_updated", "meeting_id": "abc123", "data": {"attendees": [...]}, "timestamp": "..."}
```

### Transcript Events
```javascript
// New transcript segment added
{"type": "transcript_segment", "meeting_id": "abc123", "data": {"segment": {"start": 0.0, "end": 5.0, "text": "Hello...", "speaker": "SPEAKER_00"}}, "timestamp": "..."}

// Full transcript update (after diarization)
{"type": "transcript_updated", "meeting_id": "abc123", "data": {"segments": [...]}, "timestamp": "..."}
```

### Finalization Events
```javascript
// Finalization progress
{"type": "finalization_status", "meeting_id": "abc123", "status_text": "Analyzing speakers...", "progress": 0.3, "timestamp": "..."}
```

### General Events
```javascript
// Catch-all for any other update - triggers full refresh
{"type": "meeting_updated", "meeting_id": "abc123", "timestamp": "..."}
```

## LLM Provider Streaming

Each LLM provider implements `_call_api_stream()`:

### Ollama
```python
response = requests.post(url, json={"stream": True}, stream=True)
for line in response.iter_lines():
    data = json.loads(line)
    yield data.get("response", "")
```

### OpenAI
```python
response = requests.post(url, json={"stream": True}, stream=True)
for line in response.iter_lines():
    # Parse SSE format: data: {...}
    data = json.loads(line[6:])
    yield data["choices"][0]["delta"].get("content", "")
```

### Anthropic
```python
response = requests.post(url, json={"stream": True}, stream=True)
for line in response.iter_lines():
    # Parse SSE format with event types
    data = json.loads(line[6:])
    if data["type"] == "content_block_delta":
        yield data["delta"]["text"]
```

## Testing

1. **With frontend open**: Start a recording, stop it, watch summary stream in
2. **Without frontend**: Start recording, close browser, stop via API, reopen - summary should be saved
3. **Manual trigger**: Click "Summarize" button in debug panel, watch streaming

## Future Enhancements

- [ ] Streaming for title generation
- [ ] Progress indicator showing token count
- [ ] Ability to cancel in-progress summarization
- [ ] Retry logic for failed streams
