# Meeting Mode — Implementation Plan

## Phase 0 — Baseline Checks
- Confirm existing meeting page loads with meeting id.
- Verify transcript and summary render for completed meetings.
- Capture current behavior in `docs/testing/TESTING.md` if missing.

## Phase 1 — Meeting Status + Timestamps
- Add `status` field to meeting model (`in_progress` | `completed`).
- Add `summary.updated_at` and `transcript.updated_at`.
- Ensure these are updated when summaries/transcripts change.
- Update meeting API to return new fields.

## Phase 2 — Live Transcript in Meeting Page
- If meeting is in progress, start live transcript streaming.
- Append segments to transcript output in real time.
- Fall back to polling if stream errors.

## Phase 3 — Running Summary Refresh
- While recording, refresh summary every 30s.
- Ensure no overlapping summary jobs (skip if in-flight).
- On stop recording, cancel summary refresh.

## Phase 3.5 — Auto-Title Generation
- Trigger after the first meaningful summary is available (summarized + interim).
- Only if `title_source` is `default` or `auto`.
- Generate once per meeting unless manually reset.
- Do not overwrite manual titles.
- Optionally re-generate on meeting end if still auto.

## Phase 4 — Attendees + Speaker Mapping
- Ensure attendee edits update speaker display in meeting view.
- Keep JSON attendee list as source of speaker names.

## Phase 5 — UI Status + Error Handling
- Add “in progress” indicators for transcript + summary.
- Show last updated timestamp for summary.
- Preserve last summary on errors, show warning.

## Phase 6 — QA + Docs
- Add manual QA steps in `docs/testing/TESTING.md`.
- Update `docs/README.md` current status.
- Verify against the spec’s done criteria.
