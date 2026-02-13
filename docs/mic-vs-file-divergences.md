# Mic vs File Transcription: Code Path Divergences

This document enumerates all differences between microphone (live) and file transcription modes **after audio ingestion**, explaining whether each difference is inherent to the mode or an architectural choice that could be unified.

## Overview

| Aspect | File Mode | Mic Mode | Inherent or Choice? |
|--------|-----------|----------|---------------------|
| Meeting flag | `simulated: true` | `simulated: false` | **Choice** - could be removed |
| Recording ID | `recording_id: null` | `recording_id: <uuid>` | **Choice** - both could have IDs |
| Transcription driver | Backend thread only | Backend SSE + Frontend display | **Choice** - could unify |
| Audio source | File read via `sf.read()` | Live queue via `get_live_chunk()` | **Inherent** - fundamentally different sources |

---

## 1. Meeting Creation

### File Mode (`meeting_store.py:466-508`)
```python
def create_simulated_meeting(audio_path, samplerate, channels):
    meeting = {
        "simulated": True,           # ← File-only flag
        "recording_id": None,        # ← No recording ID
        "audio_path": audio_path,
        "samplerate": samplerate,
        "channels": channels,
        ...
    }
```

### Mic Mode (`meeting_store.py:377-464`)
```python
def create_from_recording(recording):
    meeting = {
        # "simulated" not set (defaults to falsy)
        "recording_id": recording.get("recording_id"),  # ← Has UUID
        "audio_path": recording.get("file_path"),
        "samplerate": recording.get("samplerate"),
        "channels": recording.get("channels"),
        ...
    }
```

### Analysis

| Field | Difference | Inherent or Choice? |
|-------|------------|---------------------|
| `simulated` flag | Only set for file mode | **Choice** - This flag exists purely to differentiate modes in frontend logic. Could be replaced with a `source_type` field or removed entirely if frontend behavior is unified. |
| `recording_id` | null vs UUID | **Choice** - File transcriptions could also generate a UUID. The null value is arbitrary; both modes create a meeting with an `id` field anyway. |

**Recommendation:** Unify meeting creation to use consistent fields. Replace `simulated: true` with `source_type: "file"` or `source_type: "mic"` for clarity, or eliminate the distinction if frontend behavior is unified.



---

## 2. Frontend Behavior Based on `simulated` Flag

### `meeting.js:887`
```javascript
if (isThisMeetingActive && meeting.status === "in_progress" && !meeting.simulated) {
  startLiveTranscript();  // ← Only for mic mode
} else {
  stopLiveTranscript();   // ← File mode takes this path
}
```

### What This Means

- **File mode**: Frontend does NOT connect to `/api/transcribe/live` SSE endpoint
- **Mic mode**: Frontend connects to `/api/transcribe/live` to receive real-time transcript segments

### Inherent or Choice?

**Choice** - This is an architectural decision, not an inherent requirement.

The `simulated` flag controls whether the frontend establishes an SSE connection for live transcript streaming. However:

- File mode COULD use SSE to push segments in real-time (backend would need to emit events as it processes)
- Mic mode COULD work without frontend SSE (backend saves to disk, frontend uses meeting SSE updates)

The current split creates two different user experiences and code paths. Unifying would mean either:
1. Both modes push segments via SSE (consistent real-time UX)
2. Neither mode uses `/api/transcribe/live`; both use meeting update SSE (simpler architecture)

---

## 3. Transcription Execution

### File Mode (`transcription.py:377-553`)

**Entry point:** `/api/transcribe/simulate` or `/api/transcribe/stream`

```python
def _run_simulated_transcription(meeting_id, audio_path, ...):
    # Runs in a dedicated background thread
    for chunk_result in pipeline.chunked_transcribe_and_format(audio_path, ...):
        segments.extend(chunk_result.segments)
        meeting_store.append_live_segment(meeting_id, segment)
```

**Characteristics:**
- Single backend thread reads file directly
- No queue contention possible
- Segments saved to disk incrementally

### Mic Mode (`transcription.py:1107-1444`)

**Entry point:** `/api/transcribe/live` (SSE endpoint)

```python
def event_stream():
    audio_service.enable_live_tap()
    while True:
        chunk = audio_service.get_live_chunk(timeout=0.5)
        # Transcribe and yield segments via SSE
```

**Characteristics:**
- SSE streaming response
- Pulls audio from shared `_live_queue`
- Multiple SSE connections could compete for same queue

### Inherent or Choice?

| Aspect | Inherent or Choice? | Explanation |
|--------|---------------------|-------------|
| Audio source (file vs queue) | **Inherent** | File exists on disk; mic audio arrives in real-time. This is a fundamental difference. |
| Thread vs SSE architecture | **Choice** | File mode could use SSE to push results. Mic mode could use a backend thread that saves to disk (like file mode) with meeting SSE for updates. |
| Queue-based audio delivery | **Inherent for real-time** | Mic audio must be buffered somehow. A queue is a reasonable choice, but the single-consumer design is a **choice**. |

**Recommendation:** After audio is captured/converted to a standard format (WAV), both modes could use identical transcription pipelines. The queue vs file-read difference is inherent, but everything downstream could be unified.

---

## 4. Real-time Diarization Instance

**Status: UNIFIED** (Feb 2026)

### Before (Divergent)

**File Mode:**
```python
# Creates NEW instance per file transcription
sim_rt_diar = RealtimeDiarizationService(realtime_diar_cfg)
```

**Mic Mode (OLD):**
```python
# Used SHARED router-level instance - BUG!
realtime_diarization = RealtimeDiarizationService(realtime_diar_cfg)  # at router init
```

### After (Unified)

Both modes now create per-session diarization instances:

```python
# In event_stream() - creates per-session instance
session_rt_diarization = RealtimeDiarizationService(realtime_diar_cfg)
rt_diarization_active = session_rt_diarization.start(samplerate, channels)
```

### Changes Made

| File | Change |
|------|--------|
| `app/routers/transcription.py` | Removed shared `realtime_diarization` instance at router level |
| `app/routers/transcription.py` | `event_stream()` now creates `session_rt_diarization` per session |
| `app/routers/transcription.py` | `process_audio_chunk()` takes `rt_diarization` parameter |
| `app/routers/transcription.py` | Settings endpoint updates config for future sessions only |

---

## 5. Stop/Cancel Mechanism

**Status: UNIFIED** (Feb 2026)

### Before (Divergent)

**File Mode:**
```python
job["cancel"].set()  # threading.Event checked at chunk boundaries
audio_source.stop()  # Interrupt playback delays
```

**Mic Mode:**
```python
audio_service.signal_capture_stopped()  # Immediate signal
audio_service.stop_recording()          # Stop audio capture
```

### After (Unified)

Both modes now use `AudioDataSource.stop()` as the primary stop mechanism:

```python
# In stop_transcription_by_meeting():
job = transcription_jobs.get(meeting_id)
if job:
    audio_source = job.get("audio_source")
    if audio_source:
        audio_source.stop()  # Unified interface for both modes
    
    # File mode also has cancel_event for transcription loop
    if job.get("cancel"):
        job["cancel"].set()
    
    # Mic mode also needs to stop the recording device
    if job.get("source_type") == "mic":
        audio_service.stop_recording()
```

### Changes Made

| File | Change |
|------|--------|
| `app/routers/transcription.py` | Added `transcription_jobs` unified registry with lock |
| `app/routers/transcription.py` | `event_stream()` registers mic jobs with `MicAudioSource` |
| `app/routers/transcription.py` | `stop_transcription_by_meeting()` uses unified lookup and `audio_source.stop()` |
| `app/services/audio_source.py` | `MicAudioSource.stop()` calls `signal_capture_stopped()` |
| `app/services/audio_source.py` | `FileAudioSource.stop()` sets stopped flag and interrupts delays |

### How It Works

1. **Both modes register in `transcription_jobs`** with their `AudioDataSource`
2. **Stop endpoint looks up by meeting_id** - no mode-specific branching needed
3. **Calls `audio_source.stop()`** which handles mode-specific details internally
4. **Additional cleanup** happens based on source_type (e.g., `stop_recording()` for mic)

---

## 6. Job Tracking

### File Mode
```python
simulate_jobs = {}  # Dict keyed by meeting_id
```

### Mic Mode
```python
status = audio_service.current_status()  # Queries audio service state
```

### What This Means

- **File mode**: Jobs tracked in a dictionary with metadata (thread, cancel event, paths)
- **Mic mode**: "Job" state is implicit in the audio service's recording state

### Inherent or Choice?

**Choice** - Both could use the same tracking mechanism.

The different approaches exist because file mode can have multiple queued/concurrent jobs (though currently limited to one), while mic mode assumes only one recording at a time. This assumption could change.

**Recommendation:** Unify job tracking into a single registry that handles both modes.

---

## 7. Transcript Streaming Architecture

**Status: UNIFIED** (Feb 2026)

### Before (Divergent)

**File Mode:** Used `/api/meetings/events` SSE with `transcript_segment` events
**Mic Mode:** Used dedicated `/api/transcribe/live` SSE endpoint with `yield` statements

This caused:
- Different frontend code paths (`handleMeetingEvent()` vs `streamLiveTranscript()`)
- Multiple browser windows competing for audio chunks in mic mode
- Extra state management (`state.liveController`, `state.liveStreaming`)

### After (Unified)

Both modes now use the same architecture:

```
Backend (both modes)             Frontend
----------------                 --------
_run_live_transcription()        meeting.js
or _run_simulated_transcription()     |
      |                               v
      v                          subscribeToMeetingEvents()
meeting_store.append_live_segment()   |
      |                               |
      v                               v
meeting_store.publish_event() --> /api/meetings/events (SSE)
      |                               |
      | "transcript_segment"          | handleMeetingEvent()
      v                               v
   (done)                        update UI
```

### Changes Made

| File | Change |
|------|--------|
| `app/routers/transcription.py` | Added `_run_live_transcription()` background thread function |
| `app/routers/transcription.py` | Added `POST /api/transcribe/start` endpoint to start background transcription |
| `app/routers/transcription.py` | Marked `POST /api/transcribe/live` as deprecated |
| `app/static/meeting.js` | Replaced `startLiveTranscript()`, `stopLiveTranscript()`, `streamLiveTranscript()` with `startBackendTranscription()` |
| `app/static/meeting.js` | Removed `state.liveController`, `state.liveStreaming` |
| `app/static/meeting.js` | Removed `!state.liveStreaming` checks in `handleMeetingEvent()` |

### New API

**POST /api/transcribe/start**
```json
{
  "meeting_id": "uuid-here"
}
```

Starts a background transcription thread that:
1. Reads audio from mic via `MicAudioSource`
2. Transcribes chunks using the pipeline
3. Saves segments via `meeting_store.append_live_segment()` (publishes events)
4. Finalizes meeting when recording stops

### Benefits

- **Multiple windows work:** All subscribers to `/api/meetings/events` receive segments
- **Simpler frontend:** No dedicated SSE connection management for mic mode
- **Consistent behavior:** Both modes publish through the same event system
- **Decoupled lifecycle:** Transcription continues even if browser disconnects

---

## 7b. Active Transcription Detection (`/api/transcribe/active`)

```python
def get_active_transcription():
    if simulate_jobs:
        return {"active": True, "type": "file", ...}
    if status.get("recording"):
        return {"active": True, "type": "live", ...}
    return {"active": False, ...}
```

### What This Means

The API returns different `type` values to distinguish modes. Frontend uses this plus the `source_type` field to determine behavior (e.g., whether to call `/api/transcribe/live`).

### Inherent or Choice?

**Choice** - The distinction exists to support different frontend behavior, which itself is a choice.

If frontend behavior were unified (see #7 above), this endpoint could simply return `{"active": true/false}` without type distinction.

### After Unification

With unified job registry (`transcription_jobs`), this could be simplified:
```python
def get_active_transcription():
    with transcription_jobs_lock:
        if transcription_jobs:
            job = next(iter(transcription_jobs.values()))
            return {"active": True, "meeting_id": job.get("meeting_id")}
    return {"active": False}
```

---

## 8. Model/Device Configuration

### File Mode
```python
pipeline = get_pipeline(model_size, final_device, final_compute)  # Always final
```

### Mic Mode
```python
# Real-time: optimized for speed
pipeline = get_pipeline(model_size, live_device, live_compute)

# Finalization: optimized for quality
pipeline = get_pipeline(model_size, final_device, final_compute)
```

### What This Means

- **File mode**: Uses "final" (higher quality) settings throughout since there's no real-time constraint
- **Mic mode**: Uses "live" (faster) settings for real-time, then "final" settings for post-processing

### Inherent or Choice?

**Partly inherent, partly choice.**

| Aspect | Inherent or Choice? | Explanation |
|--------|---------------------|-------------|
| Real-time speed requirement | **Inherent** | Mic mode must keep up with audio input; file mode has no time pressure. |
| Two-pass processing (live + final) | **Choice** | Mic mode could use only final settings (would lag behind audio). File mode could use live settings (would be faster but lower quality). |
| Different device allocation | **Choice** | Could use same device for both if resources allow. |



**Choice** - unify both paths.  always use the faster setting during the ingestion of the audio.  then always do the final_compute at the end for both modes.


---

## 9. Finalization Path

**Status: UNIFIED** (Feb 2026)

### Before (Divergent)

**File Mode:** Single finalization at end of `_run_simulated_transcription` thread

**Mic Mode:** Multiple potential triggers:
- Stop endpoint spawning background thread
- SSE stream `finally` block
- Risk of double finalization and race conditions

### After (Unified)

Both modes now have a single finalization trigger at the end of their transcription thread:

| Mode | Finalization Location |
|------|----------------------|
| File | End of `_run_simulated_transcription()` |
| Mic | End of `_run_live_transcription()` |

### Changes Made

| File | Change |
|------|--------|
| `app/services/transcription_pipeline.py` | Added guard in `finalize_meeting_with_diarization()` to prevent double finalization |
| `app/routers/transcription.py` | Removed finalization from deprecated `/api/transcribe/live` `finally` block |
| `app/routers/transcription.py` | Stop endpoint (`/api/transcribe/stop`) no longer triggers finalization directly |

### Guard Against Double Finalization

```python
# In finalize_meeting_with_diarization():
meeting = self._meeting_store.get_meeting(meeting_id)
if meeting:
    current_status = meeting.get("status")
    finalization_status = meeting.get("finalization_status")
    
    # Skip if already completed
    if current_status == "completed" and finalization_status.get("step") == "complete":
        return meeting.get("summary")
    
    # Skip if currently processing
    if current_status == "processing":
        return None
```

### Flow

```
Recording Stop
      │
      ▼
AudioDataSource.stop() ← signals stop
      │
      ▼
Transcription loop exits naturally
      │
      ▼
Single finalization point
      │
      ▼
finalize_meeting_with_diarization()
      │
      ├─► (guard: skip if already finalized)
      │
      ▼
Diarization → Summarization → Complete
```



---

## 10. Audio Processing Flow

### File Mode
```
Audio File
    │
    ▼ convert_to_wav() [if not WAV]
    │
    ▼ sf.read() chunks directly from file
    │
    ▼ pipeline.chunked_transcribe_and_format()
    │
    ▼ Segments saved to disk
    │
    ▼ finalize_meeting_with_diarization()
```

### Mic Mode
```
Microphone (sounddevice)
    │
    ├──▶ _audio_queue → WAV file (disk backup)
    │
    └──▶ _live_queue → event_stream() SSE
              │
              ▼ buffer accumulation
              │
              ▼ _write_temp_wav() → transcribe_chunk()
              │
              ▼ Segments via SSE + saved to disk
              │
              ▼ finalize_meeting_with_diarization()
```

### What This Means

- **File mode**: Linear flow from file to transcription
- **Mic mode**: Parallel flows - one writes to disk, one streams to transcription

### Inherent or Choice?

| Aspect | Inherent or Choice? | Explanation |
|--------|---------------------|-------------|
| File read vs live capture | **Inherent** | Fundamental difference in audio source. |
| Dual queue (disk + live) | **Choice** | Could have single queue that both writes to disk AND feeds transcription. Current design allows independent operation. |
| Temp WAV creation | **Choice** | Mic mode creates temp WAV files for each chunk. Could potentially process in-memory if transcription API supports it. |

**Recommendation:** After initial capture, both modes could feed into an identical pipeline. The "convert to WAV chunks → transcribe → save segments" flow could be shared.

---

## 11. Error Handling

**Status: UNIFIED** (Feb 2026)

### Before (Divergent)

**File Mode:** Errors caught silently, no real-time notification to frontend

**Mic Mode:** Errors yielded via dedicated SSE: `{"type": "error", "message": "..."}`

### After (Unified)

Both modes now publish `transcription_error` events via meeting SSE:

```python
# In both _run_live_transcription() and _run_simulated_transcription():
meeting_store.publish_event("transcription_error", meeting_id, {
    "message": f"Transcription error: {exc}",
    "error_type": "internal_error",  # or "provider_error"
})
```

Frontend handles in `handleMeetingEvent()`:
```javascript
case "transcription_error":
  setTranscriptStatus(`Error: ${event.data.message}`);
  setGlobalError(`Transcription error: ${event.data.message}`);
  break;
```

### Changes Made

| File | Change |
|------|--------|
| `app/routers/transcription.py` | `_run_live_transcription()` publishes `transcription_error` on exceptions |
| `app/routers/transcription.py` | `_run_simulated_transcription()` publishes `transcription_error` on exceptions |
| `app/static/meeting.js` | `handleMeetingEvent()` handles `transcription_error` events |

### Benefits

- Consistent error UX for both modes
- Errors appear in real-time regardless of source type
- All browser windows viewing the meeting see the error

---

## Summary: Classification of Differences

### Inherent Differences (Cannot Be Unified)

| Difference | Reason |
|------------|--------|
| Audio source (file vs microphone) | Fundamental - one is pre-recorded, one is live |
| Real-time processing requirement | Mic must keep up with audio; file has no time pressure |
| Initial audio delivery (read vs capture) | Different I/O mechanisms required |

### Architectural Choices (Could Be Unified)

| Difference | Current State | Unified Approach | Status |
|------------|---------------|------------------|--------|
| `simulated` flag | ~~Exists for file mode only~~ | `source_type` field | **DONE** |
| `recording_id` | ~~null for file mode~~ | `session_id` for both | **DONE** |
| **Transcript SSE streaming** | ~~File: `/api/meetings/events`<br>Mic: `/api/transcribe/live`~~ | Both use `/api/meetings/events` | **DONE** |
| Frontend SSE handling | ~~File: `handleMeetingEvent()`<br>Mic: `streamLiveTranscript()`~~ | Single handler | **DONE** |
| Diarization instance | ~~Shared (mic) vs per-session (file)~~ | Per-session for both | **DONE** |
| Stop/Cancel mechanism | ~~Different APIs~~ | `AudioDataSource.stop()` | **DONE** |
| Job tracking | ~~Different mechanisms~~ | `transcription_jobs` registry | **DONE** |
| Finalization triggers | ~~Multiple for mic~~ | Single trigger point + guard | **DONE** |
| Error handling | ~~File: silent<br>Mic: SSE errors~~ | Both via `transcription_error` events | **DONE** |
| Function/variable naming | ~~`simulated` terminology~~ | `file` terminology | **DONE** |

---

## Recommendations for Unification

### High Priority (Architecture)
1. ~~**Per-session diarization instances** for mic mode to prevent state corruption~~ **DONE**
2. ~~**Unified transcript SSE streaming** - Migrate mic mode to publish via `meeting_store.publish_event("transcript_segment", ...)`~~ **DONE**
3. ~~**Single finalization trigger** to prevent race conditions in mic mode~~ **DONE** (single trigger + guard)
4. ~~**Remove duplicate SSE connections** (already fixed - removed `startLiveTranscription()` from app.js)~~ **DONE**

### Medium Priority (Architecture Cleanup)
5. ~~**Unified meeting creation** with consistent fields (`source_type` instead of `simulated`)~~ **DONE**
6. ~~**Unified job tracking** registry for both modes~~ **DONE** (implemented as `transcription_jobs`)
7. ~~**Unified error handling** via meeting SSE events for both modes~~ **DONE** (`transcription_error` events)
8. ~~**Deprecate `/api/transcribe/live`** endpoint~~ **DONE** (marked deprecated, kept for backwards compatibility)
9. ~~**Simplify frontend** - Remove `streamLiveTranscript()`, `startLiveTranscript()`, `state.liveController`, `state.liveStreaming`~~ **DONE**

### Low Priority (Nice to Have)
10. **Shared transcription pipeline** after audio ingestion point

---

## Implementation: AudioDataSource Abstraction

**Status: IMPLEMENTED** (Feb 2026)

### Design Decisions

The following design decisions were made through collaborative discussion:

#### 1. Chunk Delivery: Blocking with Timeout
- **Decision**: `get_chunk()` blocks up to `timeout_sec` waiting for data
- **Rationale**: Backend threads handle the blocking; frontend is not affected
- **Mic mode**: Blocks until audio available (naturally real-time)
- **File mode**: Returns chunks immediately (no artificial delay by default)

#### 2. File Playback Speed: User-Configurable
- **Decision**: `speed_percent` parameter controls delay between chunks
- **Values**:
  - `0` = no delay (as fast as possible)
  - `100` = real-time (wait full chunk duration)
  - `300` = 3x faster (wait 1/3 of chunk duration) **[DEFAULT]**
- **Implementation**: Uses `threading.Event.wait(timeout=delay)` so `stop()` can interrupt

#### 3. Location: Dedicated Module
- **Decision**: New file at `app/services/audio_source.py`
- **Contains**: `AudioDataSource` (ABC), `AudioMetadata`, `MicAudioSource`, `FileAudioSource`

### Files Changed

| File | Change |
|------|--------|
| `app/services/audio_source.py` | **NEW** - AudioDataSource abstraction |
| `app/services/meeting_store.py` | Replaced `simulated: bool` with `source_type: str`, added `session_id` |
| `app/routers/transcription.py` | Uses `FileAudioSource` for `/api/transcribe/simulate`, added `speed_percent` param |
| `app/static/meeting.js` | Changed `!meeting.simulated` to `meeting.source_type !== "file"` |

### API Changes

**`POST /api/transcribe/simulate`** now accepts:
```json
{
  "audio_path": "/path/to/audio.mp3",
  "model_size": "small",
  "speed_percent": 300  // NEW: 0 = no delay, 100 = real-time, default 300
}
```

### Meeting Data Changes

Old format:
```json
{
  "simulated": true,
  "recording_id": null
}
```

New format:
```json
{
  "source_type": "file",  // or "mic"
  "session_id": "uuid-string"
}
```

### Class Diagram

```
AudioDataSource (ABC)
├── get_chunk(timeout_sec) -> bytes | None
├── get_metadata() -> AudioMetadata
├── is_complete() -> bool
└── stop() -> None

MicAudioSource(AudioDataSource)
├── Wraps AudioCaptureService
├── Reads from _live_queue
└── session_id from recording_id

FileAudioSource(AudioDataSource)
├── Reads from file via soundfile
├── speed_percent controls inter-chunk delay
└── session_id auto-generated (UUID)
```
