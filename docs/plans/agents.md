# Notetaker Planner — Agent Notes

Role: Product + Delivery Coach (focus: scope clarity, sequencing, shipping)

## Objective

Read all notetaker todo items, triage by type/size, define specs/plans where needed, surface open questions and conflicts, and make work ready for implementation without coding.

## Specs/Plans Created

- `docs/specs/auto-meeting-title-spec.md`
- `docs/plans/auto-meeting-title-plan.md`
- `docs/specs/smart-real-time-summary-spec.md`
- `docs/plans/smart-real-time-summary-plan.md`
- `docs/specs/user-login-spec.md`
- `docs/plans/user-login-plan.md`
- `docs/specs/cleanup-main-window-spec.md`
- `docs/plans/cleanup-main-window-plan.md`
- `docs/specs/diarization-whisperx-spec.md`
- `docs/plans/diarization-whisperx-plan.md`

## Triage Summary (by todo item)

- **Auto meeting title generation**: new feature, medium; spec + plan created.
- **Smart real time summary parsing**: new feature, large; spec + plan exists.
- **Smart real time summary debug UI**: new feature, small; covered by smart-real-time summary spec/plan.
- **User login**: new feature, large; spec + plan created.
- **Cleanup main window**: new feature, medium; spec + plan updated with decisions.
- **Meeting mode**: implemented; no action.
- **Settings page**: implemented; no action.
- **AI model specification**: implemented; no action.
- **Set live transcript default on**: implemented; no action.
- **Diarization with WhisperX**: new feature, large; spec + plan created.

## Conflicts / Dependencies

- **Settings control placement conflicts**:
  - Cleanup task says move settings button to upper-right next to profile dropdown.
  - Need a single decision on profile dropdown contents and settings placement.
- **Login depends on storage layout**: user login requires per-user storage structure; will affect meeting store paths and settings.
- **Auto title depends on summary cadence**: relies on meeting-mode summary updates and title_source fields already in meeting-mode spec.

## Open Questions (Need Answers Before Implementation)

- None for current scope.

## Ready-to-Implement Ordering (Once Questions Answered)

1) Cleanup main window (medium).
2) Auto meeting title generation (medium, isolated).
3) Smart real-time summary debug UI (small, if summary engine ready).
4) WhisperX diarization (large).
