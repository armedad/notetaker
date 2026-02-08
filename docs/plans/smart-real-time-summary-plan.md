# Smart Real-Time Summary Parsing Plan

## Phase 1 — Data Model + API

### Goals
- Persist `summary_state` on meeting object.
- Expose `summary_state` in meeting API.

### Steps
1. Extend meeting store schema to include `summary_state`.
2. Backfill default empty `summary_state` for existing meetings.
3. Ensure `GET /api/meetings/{id}` returns `summary_state`.

### Done Criteria
- Summary state fields visible in meeting JSON.
- No errors on existing meetings.

## Phase 2 — Summary Engine

### Goals
- Implement 30s tick processor.
- LLM cleanup + topic segmentation pipeline.

### Steps
1. Build sentence extraction (streaming → draft) without partial sentences.
2. Add LLM prompt for cleanup (transcription correction).
3. Add LLM prompt for topic segmentation + per-topic summary.
4. Apply topic transitions to move text/summary into done/summarized.

### Done Criteria
- End-to-end processing updates summary_state.
- No overlapping ticks (skip if in-flight).

## Phase 3 — UI Debug Panel

### Goals
- Add debug button + panel on meeting page.
- Show live text streams and summaries.

### Steps
1. Add button + panel layout.
2. Auto-refresh panel from meeting data.
3. Auto-scroll to bottom.

### Done Criteria
- Debug panel mirrors state updates in real time.

## Phase 4 — QA + Docs

### Goals
- Manual QA steps.
- Update README status.

### Steps
1. Add steps to `docs/testing/TESTING.md`.
2. Update `docs/README.md` Current Status.

### Done Criteria
- Clear manual QA instructions.
