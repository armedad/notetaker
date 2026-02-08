# Diarization with WhisperX Plan

## Phase 1 — Dependency + Install

### Goals
- Add WhisperX to install flow.
- Document setup requirements.

### Steps
1. Update install script to include WhisperX.
2. Add notes on GPU/CPU expectations in README.

### Done Criteria
- WhisperX installs successfully.
- README updated with requirements.

## Phase 2 — Pipeline Integration

### Goals
- Integrate diarization into transcription pipeline.
- Add config slider for accuracy/performance tradeoff.
- Add GPU/CPU selection with capability detection.

### Steps
1. Wire WhisperX diarization into transcription flow.
2. Add settings slider to tune accuracy/performance.
3. Detect GPU capability and expose availability to settings.
4. Add GPU/CPU selection and gray out GPU when unavailable.
5. Ensure speaker labels attached to segments.

### Done Criteria
- Speaker labels present in transcript output.
- Toggle works as expected.

## Phase 3 — QA + Docs

### Goals
- Validate diarization on multi-speaker audio.
- Document manual QA steps.

### Steps
1. Test with multi-speaker recordings.
2. Add steps to `docs/testing/TESTING.md`.

### Done Criteria
- QA steps documented.
