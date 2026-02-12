# Notetaker Project — Agent Instructions

## Overview

Local-first meeting notetaker that records system audio, transcribes with speaker ID, summarizes, extracts action items, and supports read-only sharing. Runs on macOS + Windows. Offline works; cloud improves summaries and sharing.

## Source of Truth

- `docs/specs/opportunity-assessment.md` — full spec + architecture (source of truth)
- `docs/plans/plan.md` — phased implementation plan
- `docs/README.md` — current status + how to run/test

## Getting Started

### For New AI Agent

**Methodology:** Use `@thinking/from-thinking-to-coding/` for any large, multi-step feature with open questions before implementation. The flow is spec → plan → agent instructions → execution.

**First, read these files in order:**
1. `docs/README.md` — current status and what's next
2. `docs/AGENTS.MD` — how to work here
3. `docs/specs/opportunity-assessment.md` — spec + architecture
4. `docs/plans/plan.md` — phases and done criteria
5. `docs/testing/TESTING.md` — manual QA steps
6. `docs/testing/test-automation.md` — automated curl checks with timeouts

**Then:**
1. Run the app to verify current behavior
2. Test current features (`docs/README.md` + `docs/testing/TESTING.md`)
3. Continue with the next phase in `docs/plans/plan.md`
4. Update docs as you go (see Continuous Documentation)

## Non-Negotiables (Read First)

- **Source code location:** `/Users/chee/zapier ai project/coding/notetaker` (Cursor workspace)
- **Runtime location:** `~/projects/notetaker` (where the app runs)
- **NEVER** edit files under `~/projects/notetaker` or `/Users/chee/projects/notetaker`
- **ALWAYS** edit in the workspace and deploy via `./deploy.sh` (run from `coding/notetaker/`)
- **Runtime logs only:** use `~/projects/notetaker/logs/server_*.log` and `~/projects/notetaker/logs/server_runtime_debug.log`
- **Do NOT** use `.cursor/debug.log` unless the user explicitly asks

## Pre-Flight Checklist (Must Do Before Any Change)

- Confirm edits are in `/Users/chee/zapier ai project/coding/notetaker`
- Confirm deployment uses `./deploy.sh` to `~/projects/notetaker`
- Confirm logs are read from `~/projects/notetaker/logs/`

## Tech Stack (Implemented)

- Backend: Python + FastAPI
- Storage: JSON file-based (meetings.json in data/)
- Transcription: faster-whisper (local Whisper with modular provider interface)
- Diarization: WhisperX, pyannote-audio (batch), Diart (real-time)
- LLM/Summarization: Unified model selection supporting OpenAI, Anthropic, Gemini, Grok, Ollama, LMStudio
- Frontend: Vanilla JS web UI served by backend

## LLM Provider Architecture (CRITICAL)

- **Single model selection:** User picks ONE model in Settings > AI Models
- **Format:** `provider:model_id` (e.g., `openai:gpt-4o`, `anthropic:claude-3-5-sonnet`)
- **Config location:** `config.json` → `models.selected_model`
- **Provider credentials:** `config.json` → `providers.<provider>` (api_key, base_url)
- **Service:** `SummarizationService` reads config dynamically, NOT at boot time
- **DO NOT** hardcode models or providers anywhere
- **DO NOT** use separate summarization config — use the unified model selection

## Dependencies

Default to stdlib first. For new packages, explain why and alternatives briefly in PR description or notes. Prefer widely used, well-maintained libraries.

## Logging (CRITICAL)

- All logs must include timestamps: `[HH:MM:SS] [PREFIX] message`
- Frontend logs must go through `/api/logs/client` so they land in runtime logs
- Prefer runtime logs under `~/projects/notetaker/logs/` (do not invent new locations)

## Pipeline Convergence Rule (CRITICAL)

**Rule:** After audio is obtained (from mic/live queues OR from file/simulate), all downstream steps MUST share the same codepath:
- segment normalization/formatting
- diarization (real-time feed/assign when enabled, plus optional batch diarization)
- meeting store persistence
- finalization (status=completed, summary, auto-title)

**Allowed differences:** only the *audio acquisition* layer and UI transport (SSE vs background job) may differ.

**Implementation checklist (required for any new transcription feature):**
- Add/extend methods on `TranscriptionPipeline` instead of copying logic into routers
- Ensure `/api/transcribe/live`, `/api/transcribe/simulate`, and `/api/transcribe/stream` call the same post-audio pipeline entrypoint
- Add a regression note in `docs/specs/opportunity-assessment.md` if you intentionally diverge (rare)

## Framework/OS Gotchas (CRITICAL)

- Audio capture requires **virtual audio device** setup:
  - macOS: BlackHole, ZoomAudioDevice (for Zoom calls)
  - Windows: VB-Cable
- Device permissions may require OS prompts; document steps in README
- If audio capture seems silent, verify system output is routed to the virtual device
- **ZoomAudioDevice caveat:** May capture silence if Zoom audio routing is not configured properly in Zoom settings

## Transcription Architecture (CRITICAL)

- **TranscriptionPipeline:** Centralizes all post-audio processing in `app/services/transcription_pipeline.py`
- **Simulated transcription:** Uses `stream_transcribe_and_format()` for cancellation support
- **Cancellation:** `threading.Event` checked after each segment, not just at start/end
- **Finalization on stop:** When user stops transcription, ALWAYS run summarization and title generation with whatever segments exist
- **Audio source:** Configured in `config.json` → `audio.source` ("device" for live, "file" for simulated)

## Continuous Documentation

Update docs as you work, not just at wrap-up:
- **docs/README.md**: current status, how to run/test
- **docs/AGENTS.MD**: new gotchas, patterns, decisions
- **docs/specs/opportunity-assessment.md**: when implementation differs from spec
- **docs/plans/plan.md**: update done criteria if realities change
- **docs/testing/TESTING.md**: manual QA steps for new features

**CRITICAL:** If you diverge from the spec, update `docs/specs/opportunity-assessment.md` immediately with the decision + rationale.

## Progress Tracking

Keep a **Current Status** section at the top of `docs/README.md`:
- Which phases are complete
- What works now (brief)
- What's next
- Quick test command

## Phase Wrap-Up Protocol (REQUIRED)

Before calling any phase complete, you MUST:
1. **Verify objectives** in `docs/plans/plan.md` line by line with evidence
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
- For large features, create or update spec/plan via `@thinking/from-thinking-to-coding/` before coding

## Code Review

Request review at the end of major phases or complex features. If sub-agents are not available, instruct the user on manual review per `code-review.md` patterns.
