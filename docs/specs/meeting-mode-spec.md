# Meeting Mode Spec

## Objective

Deliver a dedicated meeting view that supports live, in-progress meetings and completed meetings with a running summary and live transcript.

## Decisions (from user)

- Meeting is **in progress** when recording is active.
- Running summary updates **every 30 seconds**.
- Transcript updates **live as segments arrive**.

## User Experience

### Meeting Page

- One page per meeting: `/meeting?id={meeting_id}`.
- Top: attendees list (editable, names map to speaker IDs).
- Left column: running summary (auto-refresh every 30s while recording).
- Right column: transcript (live streaming while recording).
- Title auto-generation:
  - Generate once after the first meaningful summary is available.
  - Do not overwrite a user-edited title.
  - Optionally re-generate on meeting end (if still auto).
- Status indicators:
  - Recording state: In progress / Completed
  - Summary status: last updated timestamp
  - Transcript status: live / completed

### In-Progress Behavior

- Transcript streams live, appended in order.
- Summary refresh every 30s during recording.
- When recording stops, summary and transcript stop auto-refreshing.

## Data Model Changes

- Meeting object should include:
  - `status`: `in_progress` | `completed`
  - `summary.updated_at`
  - `transcript.updated_at`
  - `transcript.segments` (append-only while live)
  - `title_source`: `default` | `auto` | `manual`
  - `title_generated_at` (timestamp, set on auto-title)

## Backend

### Endpoints

- `GET /api/meetings/{id}` returns `status` and timestamps.
- `GET /api/meetings/{id}/live` (optional) for live transcript SSE, or reuse existing live stream with meeting id.
- `POST /api/meetings/{id}/summarize` supports live summary refresh (no new meeting creation).

### Scheduler

- While recording: schedule summary job every 30s.
- Stop scheduler on recording stop.
- Avoid overlapping summary jobs; skip if previous still running.

## Frontend

- Meeting page polls meeting data every 5s for metadata (status, summary timestamps).
- Transcript stream starts when `status=in_progress`.
- Summary refresh timer every 30s while in progress.

## Error Handling

- If summary fails: show error banner, keep last summary.
- If transcript stream fails: show error and retry on next poll.

## Done Criteria

- In-progress meeting shows live transcript.
- Summary auto-refreshes every 30s while recording.
- Completed meeting stops refreshing.
- Attendee name edits update speaker display.
