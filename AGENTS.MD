# Notetaker Project — Agent Instructions

## Overview

Local-first meeting notetaker that records system audio, transcribes with speaker ID, summarizes, extracts action items, and supports read-only sharing. Runs on macOS + Windows. Offline works; cloud improves summaries and sharing.

## Source of Truth

- `opportunity-assessment.md` — full spec + architecture (source of truth)
- `plan.md` — phased implementation plan
- `README.md` — current status + how to run/test

## Getting Started

### For New AI Agent

**First, read these files in order:**
1. `README.md` — current status and what's next
2. `AGENTS.MD` — how to work here
3. `opportunity-assessment.md` — spec + architecture
4. `plan.md` — phases and done criteria
5. `TESTING.md` — manual QA steps
6. `test-automation.md` — automated curl checks with timeouts

**Then:**
1. Run the app to verify current behavior
2. Test current features (README + TESTING.md)
3. Continue with the next phase in `plan.md`
4. Update docs as you go (see Continuous Documentation)

## Working Directory

Project root: `coding/notetaker/`

## Tech Stack (Planned)

- Backend: Python + FastAPI
- Storage: SQLite
- Transcription: local Whisper (modular provider interface)
- Diarization: pyannote-audio (or equivalent)
- Summarization: cloud when available, local fallback
- Frontend: static web UI served by backend

## Dependencies

Default to stdlib first. For new packages, explain why and alternatives briefly in PR description or notes. Prefer widely used, well-maintained libraries.

## Logging (CRITICAL)

- All logs must include timestamps: `[HH:MM:SS] [PREFIX] message`
- Route frontend logs to backend so all logs are visible in one place
- Prefer one unified log file under `data/logs/`

## Framework/OS Gotchas (CRITICAL)

- Audio capture requires **virtual audio device** setup:
  - macOS: BlackHole
  - Windows: VB-Cable
- Device permissions may require OS prompts; document steps in README
- If audio capture seems silent, verify system output is routed to the virtual device

## Continuous Documentation

Update docs as you work, not just at wrap-up:
- **README.md**: current status, how to run/test
- **AGENTS.MD**: new gotchas, patterns, decisions
- **opportunity-assessment.md**: when implementation differs from spec
- **plan.md**: update done criteria if realities change
- **TESTING.md**: manual QA steps for new features

**CRITICAL:** If you diverge from the spec, update `opportunity-assessment.md` immediately with the decision + rationale.

## Progress Tracking

Keep a **Current Status** section at the top of `README.md`:
- Which phases are complete
- What works now (brief)
- What's next
- Quick test command

## Phase Wrap-Up Protocol (REQUIRED)

Before calling any phase complete, you MUST:
1. **Verify objectives** in `plan.md` line by line with evidence
2. **Run tests and show output** (or clearly state if no tests yet)
3. **Update docs**: README, TESTING, spec/plan if needed
4. **Walk the user through manual QA** with exact steps
5. **Wait for user confirmation** before moving to next phase
6. **Memory sweep**: capture new learnings in docs
7. **Offer a commit message** (user approves before committing)

Never say "should work now" or "tests passed" without showing output.

## Collaboration Style

- Explain your approach before writing code
- Define new technical terms when first used
- Use clear, small steps; keep code readable
- Make reasonable assumptions when needed and state them explicitly

## Code Review

Request review at the end of major phases or complex features. If sub-agents are not available, instruct the user on manual review per `code-review.md` patterns.
