# Auto Meeting Title Generation Spec

## Objective

Automatically generate a meeting title based on live content, while respecting any user-set title.

## Scope

- Live meetings only.
- Title updates during meeting and at end, unless user edits title.
- Reuse meeting-mode summary cadence (30s).

## Decisions

- Title source states: `default` | `auto` | `manual`.
- Auto title should only run if `title_source != manual`.
- First auto title should be generated after the first meaningful summary exists.
- Final auto title should run after meeting ends (if still auto).

## User Experience

- Title shows placeholder until auto title is ready.
- If user edits title, UI locks auto updates.
- Title should update quietly without modal interruptions.

## Data Model

Ensure meeting object includes:

- `title`
- `title_source`
- `title_generated_at`

## Backend

- Add helper to decide if auto title can run.
- Trigger auto title generation on summary refresh cadence.
- Trigger final generation on recording stop (if still auto).

## Prompt Requirements

- Short, specific meeting title (4–8 words).
- Reflect dominant topic and context.
- Avoid dates or generic prefixes like "Meeting".

## Meaningful Summary Definition

- The LLM must state confidence that it has identified the subject of the conversation.

## Open Questions

- None for current scope.

## Done Criteria

- Auto title appears during meeting when allowed.
- Final auto title set on meeting end if still auto.
- User edits are preserved and block further auto updates.
