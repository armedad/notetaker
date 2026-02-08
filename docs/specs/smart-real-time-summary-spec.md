# Smart Real-Time Summary Parsing Spec

## Objective

Provide a stable, continuously improving summary during live meetings by separating transcript streams and summary states, and by only finalizing topics once discussion has moved on.

## Scope

- Live meetings only (recording in progress).
- Adds server-side state to track streaming/draft/done transcript plus interim/summarized summary.
- Adds a debug panel in the meeting UI to inspect all streams in real time.

## Decisions

- Summary cadence: every 30 seconds.
- Do not split sentences; only whole sentences move from streaming → draft.
- LLM used twice per cycle:
  1) cleanup transcription text
  2) topic segmentation + per-topic summaries

## Data Model

Add to meeting object (persisted in meeting store):

- `summary_state`:
  - `streaming_text` (string)
  - `draft_text` (string)
  - `done_text` (string)
  - `interim_summary` (string)
  - `summarized_summary` (string)
  - `last_processed_segment_index` (int)
  - `updated_at` (timestamp)

## Workflow (Each 30s Tick)

1. Append new live transcript segments to `streaming_text`.
2. Extract full sentences from the top of `streaming_text`; keep remainder in streaming.
3. Send extracted text to LLM for cleanup (transcription error correction).
4. Append cleaned text to `draft_text`.
5. Send `draft_text` to LLM to detect topic boundaries and summarize each topic.
6. For each topic except the last (in-progress topic):
   - Move its transcript from `draft_text` → `done_text`.
   - Move its summary from `interim_summary` → `summarized_summary`.
7. Keep the last topic in `draft_text` and its summary in `interim_summary`.

## UI

Meeting page debug panel (toggle by button at bottom):

- Left column: `done`, `draft`, `streaming`
- Right column: `summarized`, `interim`
- Auto-scroll to bottom while updating

## API

- Add `summary_state` to `GET /api/meetings/{id}` response.
- Add `POST /api/meetings/{id}/summary-state/step` (optional) to run one tick.

## Error Handling

- If LLM cleanup fails: skip update, keep streaming/draft unchanged.
- If topic segmentation fails: keep `draft_text` as-is and do not move any topics.

## Done Criteria

- Summary state persists across refreshes.
- Live summary updates every 30s without sentence breaks.
- Debug panel shows all streams updating.
