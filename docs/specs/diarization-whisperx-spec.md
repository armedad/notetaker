# Diarization with WhisperX Spec

## Objective

Add speaker diarization using WhisperX to label speakers in transcripts.

## Scope

- Replace or augment existing diarization pipeline with WhisperX.
- Update install script and dependencies.
- Expose speaker labels in transcript segments.

## User Experience

- Transcript shows speaker labels (Speaker 1, Speaker 2, etc.).
- Speaker changes appear at the right timestamps.
- Settings includes a slider to adjust performance vs accuracy.
- Settings includes a GPU/CPU choice when available.
  - Detect GPU capability.
  - If GPU is not capable, gray out the GPU option.
- Target: diarization output stays within ~10 seconds behind live.

## Backend

- Add WhisperX dependency and setup.
- Integrate diarization into transcription pipeline.
- Add config slider value to tune accuracy/performance tradeoff.
- Detect GPU capability for WhisperX and expose availability to UI.

## Open Questions

- None for current scope.

## Decision

- Allow GPU/CPU choice when available.
- Detect GPU capability; gray out GPU option if not capable.
- Prioritize accuracy, within a bounded time limit.
- Start with diarization <= 10 seconds behind live.
- Provide a settings slider for performance vs accuracy.

## Done Criteria

- WhisperX installed via install script.
- Speaker labels included in transcript segments.
- Diarization toggle works.
