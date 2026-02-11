# Implementation Plan: Responsive Audio Capture with Model-Specific Chunk Sizes

**Created:** 2026-02-10
**Status:** Planned
**Related Bug:** Bug 2 - Hard to stop transcription

## Problem Statement

When a user presses "Stop" during live transcription, there is significant delay before the transcription actually stops. This is because:

1. **Fixed 5-second chunk accumulation** regardless of model capabilities
2. **Whisper always pads to 30 seconds** - the encoder processes a full 30-second window regardless of input size
3. **Stop blocks on transcription** - user presses stop, but must wait for Whisper inference to complete (~1-2 seconds)
4. **Coupled architecture** - audio capture and transcription are tightly coupled in the same loop

## Root Cause Analysis

### Whisper's Architecture Constraint

Whisper processes audio in fixed 30-second windows due to its transformer architecture:
- The encoder has fixed positional encodings for 30 seconds
- Smaller inputs are **padded with silence** to 30 seconds
- The encoder runs on the full 30-second spectrogram regardless of actual content

This means sending 5-second chunks provides no latency benefit - the encoder work is constant.

### Current Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Live Transcription Loop (tightly coupled)                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  while True:                                                                 │
│      chunk = get_live_chunk()      # Get audio from queue                   │
│      buffer.extend(chunk)                                                    │
│                                                                              │
│      if len(buffer) >= 5 seconds:                                           │
│          transcribe(buffer)         # BLOCKS for ~1-2 seconds               │
│          buffer.clear()             # Cancel only checked after this        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

When stop is pressed during `transcribe()`, the user must wait for it to complete.

## Target Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AUDIO CAPTURE (unchanged)                             │
│  Microphone ──► callback ──┬──► _audio_queue ──► disk writer                │
│                            └──► _live_queue  ──► live transcription         │
└────────────────────────────────┼────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AUDIO ACCUMULATOR (new component)                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Accumulates audio until model-specific threshold OR stop signal    │    │
│  │  • Whisper: 30 seconds (no benefit from smaller)                    │    │
│  │  • Parakeet: configurable (default 2s)                              │    │
│  │  • Vosk: ~500ms                                                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                 │                                            │
│  On STOP signal:               │                                            │
│  1. Stop accepting new audio    │                                            │
│  2. Flush remaining buffer      │                                            │
│  3. Signal "final chunk"        │                                            │
│                                 ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  TRANSCRIPTION QUEUE                                                 │    │
│  │  • Pending chunks waiting for transcription                         │    │
│  │  • Each chunk tagged: {audio, is_final: bool}                       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└────────────────────────────────────┼────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    TRANSCRIPTION WORKER (background thread)                  │
│  • Pulls chunks from queue                                                   │
│  • Transcribes each chunk (blocking Whisper call)                           │
│  • Emits segments via callback/queue                                        │
│  • On is_final=True: finish up and exit                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Model-Specific Chunk Sizes

```python
# New config structure in config.json
"transcription": {
    "provider": "whisper",  # or "parakeet", "vosk"
    "providers": {
        "whisper": {
            "chunk_seconds": 30.0,  # Whisper's native window, no padding waste
            "model_size": "base"
        },
        "parakeet": {
            "chunk_seconds": 2.0,   # Parakeet's configurable chunk
            "model_name": "parakeet-tdt-0.6b"
        },
        "vosk": {
            "chunk_seconds": 0.5,   # Vosk's streaming chunk
            "model_path": "/path/to/model"
        }
    }
}
```

### 2. Decoupled Capture and Transcription

**Current (coupled):**
```python
while True:
    chunk = get_live_chunk()  # Get audio
    buffer.extend(chunk)
    if len(buffer) >= threshold:
        transcribe(buffer)     # BLOCKS here
        buffer.clear()
```

**Proposed (decoupled):**
```python
# Accumulator thread
while not stop_requested:
    chunk = get_live_chunk()
    buffer.extend(chunk)
    if len(buffer) >= model_chunk_size:
        transcription_queue.put({"audio": buffer, "is_final": False})
        buffer = bytearray()
        
# On stop: flush remaining
transcription_queue.put({"audio": buffer, "is_final": True})

# Transcription worker thread (separate)
while True:
    item = transcription_queue.get()
    segments = transcribe(item["audio"])  # BLOCKS but doesn't hold up capture
    emit_segments(segments)
    if item["is_final"]:
        break
```

### 3. Stop Behavior Comparison

| Action | Current | Proposed |
|--------|---------|----------|
| User presses Stop | Waits for current Whisper call | Audio capture stops immediately |
| Remaining buffer | Discarded or waits | Queued as final chunk |
| Transcription | Blocks stop response | Continues in background |
| UI feedback | Delayed | Immediate "stopping..." |

## Files to Change

### 1. `app/services/audio_capture.py`
- Add `drain_live_queue()` method to get all remaining audio on stop
- Add `stop_capture_only()` that stops mic but doesn't clear queue

### 2. `app/services/transcription/base.py` (new)
- Define `TranscriptionProvider` protocol with `get_chunk_size()` method
- Each provider reports its optimal chunk size

### 3. `app/services/transcription/whisper_local.py`
- Add `get_chunk_size() -> float` returning 30.0

### 4. `app/services/live_transcription.py` (new)
- `LiveTranscriptionService` class
- Manages accumulator thread and transcription worker thread
- Handles start/stop lifecycle
- Emits segments via callback or queue

### 5. `app/routers/transcription.py`
- Refactor `/api/transcribe/live` to use `LiveTranscriptionService`
- Stop endpoint returns immediately, transcription finishes in background

### 6. `config.json`
- Add per-provider chunk size configuration

## Implementation Steps

### Phase 1: Refactor Audio Capture (Low Risk)
1. Add `drain_live_queue()` method
2. Add `is_capture_stopped` flag separate from `is_recording`
3. Test: stop capture, verify queue drains properly

### Phase 2: Create LiveTranscriptionService (Medium Risk)
1. Create new service with accumulator + worker architecture
2. Wire up to existing Whisper provider
3. Test: verify segments still emit correctly

### Phase 3: Implement Responsive Stop (Medium Risk)
1. Stop returns immediately with "stopping" status
2. Background worker finishes transcription
3. Add `/api/transcribe/live/status` to poll completion
4. Test: stop latency < 500ms

### Phase 4: Model-Specific Chunk Sizes (Low Risk)
1. Add `get_chunk_size()` to provider interface
2. Configure Whisper at 30s
3. Test: verify no padding waste

### Phase 5: Add Alternative Providers (Future)
1. Add Parakeet provider with 2s chunks
2. Add Vosk provider with 500ms chunks
3. Allow runtime provider switching

## API Changes

### New Endpoint: `/api/transcribe/live/status`
```json
GET /api/transcribe/live/status/{meeting_id}
Response:
{
    "status": "transcribing" | "finishing" | "complete",
    "segments_pending": 2,
    "capture_stopped": true
}
```

### Modified Stop Response
```json
POST /api/transcribe/stop/{meeting_id}
Response:
{
    "status": "stopping",        // Immediate response
    "capture_stopped": true,     // Audio capture stopped
    "transcription_pending": true // Still processing queued audio
}
```

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Race conditions in queue | Lost audio | Use thread-safe queues, careful locking |
| Memory growth if transcription backs up | OOM | Limit queue size, drop oldest if full |
| UI confusion ("stopping" vs "stopped") | UX | Clear status indicators, polling |
| Breaking existing behavior | Regression | Feature flag, gradual rollout |

## Alternative Approaches Considered

### 1. Use Streaming-Native Models (Parakeet, Vosk)
- **Pros:** True sub-second latency, interruptible at any point
- **Cons:** Different accuracy characteristics, additional dependencies
- **Decision:** Support as alternative providers, not replacement

### 2. Run Whisper in Subprocess (Killable)
- **Pros:** Can force-terminate mid-inference
- **Cons:** IPC complexity, resource overhead, may corrupt model state
- **Decision:** Too risky, prefer queue-based approach

### 3. Accept Current Latency
- **Pros:** No code changes
- **Cons:** Poor UX, user frustration
- **Decision:** Not acceptable for production use

## Success Criteria

1. Stop button returns within 500ms
2. All captured audio is transcribed (no loss)
3. UI clearly indicates "stopping" vs "stopped" states
4. No regression in transcription quality
5. Memory usage remains bounded under load
