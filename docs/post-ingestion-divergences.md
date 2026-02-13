# AudioDataSource Architecture — Source-Agnostic Transcription

This document defines the architecture for audio source abstraction and catalogs the historical divergences that were unified.

## Core Principle

**The transcription pipeline must be completely opaque to audio source type.** File mode exists purely to test the same code path that mic mode uses. After the `AudioDataSource` is created, all processing code must be identical.

## Architecture Invariants (DO NOT VIOLATE)

### 1. No Source Type Checks in Processing Code

After audio ingestion begins, code must NOT check whether audio comes from mic or file:
- NO `if source_type == "mic"`
- NO `if isinstance(audio_source, FileAudioSource)`
- NO `if audio_source.get_metadata().source_type == "file"`

### 2. Single Transcription Function

There is ONE `_run_transcription()` function that works with any `AudioDataSource`. Do NOT create separate functions for different source types.

### 3. Unified Stop Mechanism

To stop transcription, call `audio_source.stop()`. The implementation handles source-specific cleanup internally:
- `MicAudioSource.stop()` → signals capture stopped AND stops recording device
- `FileAudioSource.stop()` → sets stopped flag and interrupts playback delays

### 4. No Source Type in Data Structures

These must NOT contain source_type fields:
- `AudioMetadata` dataclass
- `transcription_jobs` registry
- API responses
- Meeting metadata

### 5. Source-Agnostic APIs

- `GET /api/transcribe/active` — works for both mic and file
- `POST /api/transcribe/stop/{meeting_id}` — works for both mic and file

### 6. Source-Agnostic Frontend

Frontend must NOT check source type to decide behavior.

## Allowed Differences (Audio Acquisition ONLY)

The ONLY place where mic vs file may differ is the **audio acquisition layer**:
- `/api/transcribe/start` — starts mic transcription (creates `MicAudioSource`)  
- `/api/transcribe/simulate` — starts file transcription (creates `FileAudioSource`)

After the `AudioDataSource` is created, all code paths are identical.

---

## Historical Divergence Audit

This section documents divergences that existed and how they were resolved.

---

## Divergence Summary

| # | Location | Divergence | Status |
|---|----------|------------|--------|
| 1 | `transcription.py` | Two separate transcription functions | FIXED |
| 2 | `transcription.py` | File mode bypasses `AudioDataSource` | FIXED |
| 3 | `transcription.py` | `cancel_event` only for file mode | FIXED |
| 4 | `transcription.py` | Stop logic branches on `source_type` | FIXED |
| 5 | `transcription.py` | Job registry has different fields | FIXED |
| 6 | `meeting.js` | Frontend checks `source_type !== "file"` | FIXED |
| 7 | `transcription_pipeline.py` | `chunked_transcribe_and_format()` reads file directly | FIXED |

---

## Detailed Analysis

### 1. Separate Transcription Functions [FIXED]

**Location**: `app/routers/transcription.py`

**Previous State**:
- `_run_live_transcription(meeting_id, audio_source, model_size)` for mic
- `_run_file_transcription(job_id, meeting_id, audio_path, model_size, cancel_event)` for file

**Resolution**: Merged into single `_run_transcription(meeting_id, audio_source, model_size)` function that works with any `AudioDataSource`. Both mic and file modes now use this unified function.

---

### 2. File Mode Bypasses AudioDataSource [FIXED]

**Location**: `app/routers/transcription.py`

**Previous State**: `FileAudioSource` was created but the file path was passed directly to `_run_file_transcription` which bypassed the abstraction.

**Resolution**: File mode now passes `FileAudioSource` to the unified `_run_transcription()` function, using the same `AudioDataSource` interface as mic mode.

---

### 3. cancel_event Only for File Mode [FIXED]

**Location**: `app/routers/transcription.py`

**Previous State**: File mode used `threading.Event()` for cancellation while mic mode used `AudioDataSource.stop()`.

**Resolution**: Both modes now use `AudioDataSource.stop()` exclusively. The unified transcription loop checks `audio_source.is_complete()` for termination. The `cancel_event` is no longer stored in the job registry.

---

### 4. Stop Logic Branches on source_type [FIXED]

**Location**: `app/routers/transcription.py`

**Previous State**: Stop endpoint had `if source_type == "mic"` branch to call `audio_service.stop_recording()`.

**Resolution**: 
- `MicAudioSource.stop()` now calls `audio_service.stop_recording()` internally
- Stop endpoint just calls `audio_source.stop()` for both modes - no branching needed
- `FileAudioSource.stop()` sets stopped flag and interrupts any playback delays

---

### 5. Job Registry Has Different Fields [FIXED]

**Location**: `app/routers/transcription.py`

**Previous State**: Mic and file jobs had different fields (`cancel`, `thread` only in file mode).

**Resolution**: Job registry now standardized to:
```python
{
    "meeting_id": str,
    "source_type": str,  # For API responses only
    "audio_source": AudioDataSource,
    "audio_path": str,
    "original_audio_path": str,  # Optional, file mode only for deduplication
}
```

---

### 6. Frontend Checks source_type [FIXED]

**Location**: `app/static/meeting.js`

**Previous State**: Frontend checked `meeting.source_type !== "file"` or `active.type === "mic"` to decide whether to trigger transcription start.

**Resolution**: Frontend now calls `startBackendTranscription()` unconditionally for any in-progress meeting:
```javascript
if (meeting.status === "in_progress") {
  await startBackendTranscription();
}
```

The API (`/api/transcribe/start`) now handles all cases gracefully:
- Returns `"already_running"` if transcription is already active
- Returns `"not_applicable"` if this is a file transcription (which auto-starts from `/api/transcribe/simulate`)
- Returns `"started"` if this is a mic recording that needs transcription triggered

The frontend no longer needs to know the source type.

---

### 7. chunked_transcribe_and_format() Reads File Directly [FIXED]

**Location**: `app/services/transcription_pipeline.py`

**Previous State**: This method read audio files directly, bypassing `AudioDataSource`.

**Resolution**: Method deleted. File mode now uses `FileAudioSource.get_chunk()` through the unified `_run_transcription()` function, same as mic mode.

---

## Current Architecture (Unified)

```
┌─────────────────┐     ┌─────────────────┐
│  MicAudioSource │     │ FileAudioSource │
└────────┬────────┘     └────────┬────────┘
         │                       │
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  AudioDataSource      │
         │  (abstract interface) │
         │  - get_chunk()        │
         │  - get_metadata()     │
         │  - is_complete()      │
         │  - stop()             │
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  _run_transcription() │
         │  (single function)    │
         └───────────────────────┘
```

All divergences have been resolved:
- One transcription function (`_run_transcription`) for both modes
- Stop logic: just `audio_source.stop()` - no branching
- **`source_type` completely removed** from:
  - `AudioMetadata` - no longer exposes source type
  - Job registry - doesn't track source type
  - API responses - doesn't return source type
  - Meeting metadata - doesn't store source type
- `MicAudioSource.stop()` handles hardware shutdown internally
- `FileAudioSource.stop()` interrupts playback delays
- Frontend calls `startBackendTranscription()` unconditionally - API handles all cases

## Stop Endpoint Unification

**Unified stop endpoint**: `POST /api/transcribe/stop/{meeting_id}`
- Works for both mic and file transcriptions
- Just calls `audio_source.stop()` on the registered job
- Returns `{"status": "stopping", "meeting_id": "..."}`

**Backwards compatibility**: `POST /api/transcribe/simulate/stop?audio_path=...`
- Thin shim that looks up meeting_id from audio_path and delegates to unified stop
- Kept for backwards compatibility only; new code should use unified endpoint

## Status Endpoint Unification

**Unified status endpoint**: `GET /api/transcribe/active`
- Returns currently active transcription (if any) for both mic and file
- Response: `{"active": true/false, "meeting_id": "...", "audio_path": "..."}`
- Frontend uses this for all status checks

The file-specific `GET /api/transcribe/simulate/status` endpoint has been removed - use `/api/transcribe/active` instead.
