# Cleanup Main Window Spec

## Objective

Simplify the main window by moving configuration and meeting controls into the right places, and reduce clutter during active use.

## Scope

- Main window UI changes only.
- Meeting list and meeting page routing.
- Settings entry point and profile dropdown.

## User Experience

- The three transcript settings move to the settings page.
- Settings button moves to the upper right and sits next to a profile dropdown.
- Start/Stop recording becomes a single toggle button that reflects current state.
- Meetings list shows all meetings, most recent first.
- If a meeting is in progress, it is pinned at the top and marked "in progress".
- Meeting-specific controls move to the meeting page:
  - Delete
  - Export to markdown
  - Change title
  - Other meeting-level controls
- Clicking a meeting in the list opens the meeting page for that meeting.
- Meeting list row is minimal: title + date/time only.
- Empty state is blank (no placeholder messaging).
- Title edits happen only on the meeting page.

## Open Questions

- None for current scope.

## Dependencies

- User login if the profile dropdown is active for auth state.
- Meeting mode routing must be stable (`/meeting?id=...`).

## Done Criteria

- Main window matches the new structure above.
- Meeting controls are removed from the main window and present on the meeting page.
- Recording toggle works and clearly shows current state.
