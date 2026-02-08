# Cleanup Main Window Plan

## Phase 1 — UX Decisions (Resolved)

### Goals
- Lock the UI decisions that affect layout and scope.

### Decisions
- Profile dropdown: single item that toggles login/logout based on auth state.
- Meeting list rows: minimal, title + date/time only.
- Empty state: blank (no placeholder).
- Title edits: only on meeting page.

### Done Criteria
- All open questions answered and recorded in spec.

## Phase 2 — Main Window Layout

### Goals
- Simplify main window layout.
- Remove meeting-level controls from the main screen.

### Steps
1. Move transcript settings to settings page.
2. Add profile dropdown + settings button in top right.
3. Replace start/stop with single recording toggle.

### Done Criteria
- Main window matches spec.

## Phase 3 — Meetings List + Navigation

### Goals
- Chronological meeting list with in-progress pin.
- Click-through to meeting page.

### Steps
1. Render meetings list (most recent first).
2. Pin in-progress meeting at top with status badge.
3. Route click to meeting page (`/meeting?id=...`).

### Done Criteria
- Meeting list is functional and navigable.

## Phase 4 — QA + Docs

### Goals
- Verify behavior and document QA.

### Steps
1. Add manual QA steps to `docs/testing/TESTING.md`.
2. Update `docs/README.md` Current Status.

### Done Criteria
- QA steps documented.
