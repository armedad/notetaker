# Auto Meeting Title Generation Plan

## Phase 1 — Data Model + Guardrails

### Goals
- Add title source tracking and timestamps.
- Prevent auto updates after user edits.

### Steps
1. Add `title_source` + `title_generated_at` to meeting model/storage.
2. Add helper to decide if auto title can run.
3. Ensure manual title edits set `title_source=manual`.

### Done Criteria
- Meetings persist title source + generated timestamp.
- Manual edits block auto updates.

## Phase 2 — Live Title Generation

### Goals
- Generate draft title early in meeting.
- Re-run at meeting end if still auto.

### Steps
1. Hook auto-title to summary refresh cadence (30s).
2. Generate first title after "meaningful summary" exists.
3. Generate final title on meeting end if still `title_source=auto`.

### Done Criteria
- Auto title appears during meeting when allowed.
- Final auto title set on meeting end if still auto.

## Phase 3 — UI + QA

### Goals
- Show placeholder until auto title available.
- Validate manual override behavior.

### Steps
1. UI placeholder state for title.
2. Manual title edit flow sets `title_source=manual`.
3. Add manual QA steps to `docs/testing/TESTING.md`.

### Done Criteria
- Title UX matches spec.
- Manual QA steps documented.
