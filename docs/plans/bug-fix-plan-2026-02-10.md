# Bug Fix Plan - 2026-02-10

This document contains systematic debugging analysis and fix plans for three bugs identified in the todo file.

---

## Bug 1: Summarization Streams Not Working

**Symptom:** Nothing showing in summarized & interim text boxes in the debug panel.

### Hard Evidence (from server logs)

```
[13:48:21] Topic segmentation failed: Topic segmentation response is not a list
[13:49:09] Topic segmentation failed: Topic segmentation response is not a list
[13:50:00] Topic segmentation failed: Topic segmentation response is not a list
... (repeated many times)
```

### Root Cause Analysis

The `segment_topics` LLM call in `openai_provider.py` returns a response that isn't being parsed as a list. The code at lines 230-238 attempts to extract topics:

```python
# Handle JSON object wrapper (response_format: json_object returns {"topics": [...]})
if isinstance(parsed, dict):
    if "topics" in parsed:
        parsed = parsed["topics"]
    elif len(parsed) == 1:
        parsed = list(parsed.values())[0]

if not isinstance(parsed, list):
    raise LLMProviderError("Topic segmentation response is not a list")
```

The LLM is returning JSON, but in a format that doesn't match our expected structure. Possibilities:
1. The LLM returns `{"result": [...]}` or another key name
2. The LLM returns nested structure
3. The LLM returns a dict with multiple keys (so `len(parsed) == 1` fails)

### Fix Plan

**Phase 1: Add Diagnostic Logging**
1. Add logging to capture the raw LLM response before parsing
2. Deploy and trigger a summary step
3. Examine what the LLM actually returns

**Phase 2: Fix the Parsing Logic**
1. Based on evidence from Phase 1, update the parsing logic to handle the actual response format
2. Consider more flexible extraction: look for any key that contains a list value
3. Add fallback: if a dict has only one key with a list value, use that

**Phase 3: Verify**
1. Trigger summary step via API
2. Confirm `summarized_summary` and `interim_summary` fields are populated
3. Check debug panel shows content

### Files to Modify
- `app/services/llm/openai_provider.py` (segment_topics method)

---

## Bug 2: Hard to Stop Transcription

**Symptom:** When hitting stop, transcription continues processing for a long time before actually stopping.

### Hard Evidence (from server logs)

```
[14:27:56] Stopped file transcription: meeting_id=6c16a22b-9395-4c7b-aafe-d639b049c789
[14:27:59] Stopped file transcription: meeting_id=6c16a22b-9395-4c7b-aafe-d639b049c789
[14:29:04] Transcription cancelled during streaming  <-- 68 seconds after first stop!
[14:29:04] Stopped file transcription: meeting_id=6c16a22b-9395-4c7b-aafe-d639b049c789
[14:29:06] Simulated transcription finished: meeting_id=... cancelled=False segments=28
```

### Root Cause Analysis

The current implementation:
1. Sets `cancel_event.set()` when stop is requested
2. Checks `cancel_event.is_set()` AFTER each segment is yielded by faster-whisper
3. faster-whisper internally batches audio processing and yields segments in bursts

The problem: faster-whisper's `model.transcribe()` generator processes audio in large chunks (often 30-second windows) before yielding segments. During this internal processing, our code cannot check the cancel event.

### Fix Plan

**Phase 1: Immediate UI Feedback**
1. Update frontend to show "Stopping..." state immediately
2. Disable stop button after first click to prevent spam-clicking

**Phase 2: Interrupt-capable Transcription** (requires investigation)

Option A: Use VAD (Voice Activity Detection) preprocessing
- Split audio into smaller chunks based on silence detection
- Process each chunk separately, checking cancel between chunks
- Tradeoff: More overhead, but responsive cancellation

Option B: Use threaded timeout approach
- Run transcription in separate thread
- Main thread monitors cancel_event
- Forcefully terminate transcription thread if cancelled
- Tradeoff: May leave resources in bad state

Option C: Accept current behavior, improve UX
- Add "Transcription is finishing current batch..." message
- Show progress indicator
- Document that cancellation has latency

**Phase 3: Verify**
1. Start transcription on a long audio file
2. Hit stop
3. Measure time from stop click to actual stop
4. Target: <5 seconds response time

### Files to Modify
- `app/services/transcription_pipeline.py` (stream_transcribe_and_format)
- `app/static/meeting.js` (stop button UX)
- Potentially `app/services/transcription/whisper_local.py` (if implementing Option A)

---

## Bug 3: No Attendees Detected (Diarization Not Working)

**Symptom:** Attendees list is always empty, no speakers detected in transcript segments.

### Hard Evidence (from server logs)

```
[14:29:04] WhisperX diarization start: device=cpu performance=0.50
Could not download 'pyannote/speaker-diarization-3.1' pipeline.
   >>> Pipeline.from_pretrained('pyannote/speaker-diarization-3.1',
visit https://hf.co/pyannote/speaker-diarization-3.1 to accept the user conditions.
[14:29:04] Diarization failed: WhisperX diarization failed
```

### Root Cause Analysis

The HuggingFace pyannote models require license acceptance before download:
1. `pyannote/speaker-diarization-3.1` - requires user to accept terms at https://hf.co/pyannote/speaker-diarization-3.1
2. Even with a valid `HF_TOKEN`, the license must be accepted via the HuggingFace web interface

The diarization config shows `hf_token` is set, but the license hasn't been accepted.

### Fix Plan

**Phase 1: License Acceptance (Manual Step)**
1. Visit https://huggingface.co/pyannote/speaker-diarization-3.1
2. Log in with HuggingFace account
3. Accept the license terms
4. May also need to accept: https://huggingface.co/pyannote/segmentation-3.0

**Phase 2: Verify Token and Permissions**
1. Test token with curl:
   ```bash
   curl -s -H "Authorization: Bearer $HF_TOKEN" \
     https://huggingface.co/api/models/pyannote/speaker-diarization-3.1
   ```
2. If 401/403, token is invalid or lacks permissions

**Phase 3: Test Diarization**
1. Run a transcription on a multi-speaker audio file
2. Check logs for "Diarization complete: speakers=X"
3. Verify segments have speaker labels
4. Verify attendees list is populated

**Phase 4: Improve Error Handling**
1. Add clearer error message in UI when diarization fails due to license
2. Add health check endpoint to verify diarization setup
3. Consider fallback behavior (continue without speakers rather than failing silently)

### Files to Modify
- No code changes required for Phase 1-3 (configuration fix)
- `app/services/diarization/providers/whisperx_provider.py` (for Phase 4 error messaging)
- `app/routers/settings.py` (for health check endpoint)

---

## Summary

| Bug | Root Cause | Complexity | Priority |
|-----|-----------|------------|----------|
| Bug 1: Summary streams | LLM response format mismatch | Low | High |
| Bug 2: Hard to stop | faster-whisper batch processing | Medium | Medium |
| Bug 3: No diarization | HuggingFace license not accepted | Low (config) | High |

### Recommended Order of Work

1. **Bug 3** - Quick config fix, just needs license acceptance
2. **Bug 1** - Code fix to handle LLM response format
3. **Bug 2** - UX improvement first, deeper fix later if needed
