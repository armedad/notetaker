from typing import Optional

import json
import logging
import os
import re
import time

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.services.meeting_store import MeetingStore
from app.services.summarization import SummarizationService
from app.services.transcript_utils import consolidate_segments
from app.services.active_meeting_tracker import get_tracker


class UpdateMeetingRequest(BaseModel):
    title: str = Field(..., min_length=1)
    title_source: Optional[str] = None


class UpdateAttendeesRequest(BaseModel):
    attendees: list[dict]


class UpdateSpeakerNameRequest(BaseModel):
    name: str = Field(..., min_length=1)


class AutoRenameResponse(BaseModel):
    suggested_name: str
    confidence: str  # "high", "medium", "low"
    reasoning: Optional[str] = None


class ManualBuffersUpdateRequest(BaseModel):
    manual_notes: str = ""
    manual_summary: str = ""


class CreateUserNoteRequest(BaseModel):
    text: str = Field(..., min_length=1)
    timestamp: Optional[float] = None  # Seconds from recording start
    is_post_meeting: bool = False


class UpdateUserNoteRequest(BaseModel):
    text: str = Field(..., min_length=1)


class SaveUserNoteDraftRequest(BaseModel):
    text: str = ""
    timestamp: Optional[float] = None


def create_meetings_router(
    meeting_store: MeetingStore, summarization_service, ctx,
) -> APIRouter:
    router = APIRouter()
    logger = logging.getLogger("notetaker.api.meetings")
    
    # Get global active meeting tracker
    active_tracker = get_tracker()

    def _get_consolidation_settings() -> tuple[float, float]:
        """Load consolidation settings from config, with defaults."""
        max_duration = 15.0
        max_gap = 2.0
        if os.path.exists(ctx.config_path):
            try:
                with open(ctx.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                transcription = data.get("transcription", {})
                max_duration = transcription.get("consolidation_max_duration", 15.0)
                max_gap = transcription.get("consolidation_max_gap", 2.0)
            except Exception:
                pass
        return max_duration, max_gap

    @router.get("/api/meetings")
    def list_meetings() -> list[dict]:
        meetings = meeting_store.list_meetings()
        # Add computed finalization fields for UI
        for meeting in meetings:
            meeting_id = meeting.get("id")
            # Use tracker-aware state resolution
            if meeting_id:
                meeting["resolved_state"] = meeting_store.resolve_state(meeting_id, active_tracker)
            else:
                meeting["resolved_state"] = meeting.get("status", "completed")
            meeting["needs_finalization"] = meeting_store.needs_finalization(meeting)
            meeting["pending_stages"] = meeting_store.get_pending_finalization_stages(meeting)
            meeting["failed_stages"] = meeting_store.get_failed_finalization_stages(meeting)
        return meetings
    
    @router.get("/api/meetings/active")
    def get_active_meetings() -> dict:
        """Get all meetings currently being actively processed.
        
        Returns a dict with:
        - meetings: dict mapping meeting_id to state info
        - count: number of active meetings
        
        Active meetings include:
        - recording: actively being recorded/transcribed
        - finalizing: live finalization in progress
        - background_finalizing: background sweep processing
        """
        active = active_tracker.get_all_active_dict()
        return {
            "meetings": active,
            "count": len(active),
        }

    @router.get("/api/meetings/events")
    def meeting_events() -> StreamingResponse:
        from app.services.debug import debug_log
        logger.info("Meetings SSE connected")

        def event_stream():
            from app.services.debug import debug_log as dl
            cursor = 0
            # #region agent log
            _buf_size = len(meeting_store._events)
            _event_types = [e.get("type") for e in meeting_store._events[-10:]]
            logger.debug("SSE_STREAM_INIT: cursor=%d buffer_size=%d recent_types=%s", cursor, _buf_size, _event_types)
            # #endregion
            # Log notification events in buffer at connection time
            notif_events = [
                e for e in meeting_store._events
                if e.get("type") in ("finalization_complete", "finalization_failed")
            ]
            if notif_events:
                dl(
                    "NOTIFICATIONS",
                    "SSE_CONNECT_BUFFER_HAS_NOTIF_EVENTS",
                    count=len(notif_events),
                    events=[
                        {"type": e.get("type"), "meeting_id": e.get("meeting_id"), "timestamp": e.get("timestamp")}
                        for e in notif_events
                    ],
                    buffer_size=_buf_size,
                    starting_cursor=cursor,
                )
            while True:
                events, cursor = meeting_store.wait_for_events(cursor, timeout=5.0)
                # #region agent log
                if events:
                    _etypes = [e.get("type") for e in events]
                    logger.debug("SSE_EVENTS_SENT: count=%d types=%s new_cursor=%d", len(events), _etypes, cursor)
                # #endregion
                # Log notification events being sent
                notif_in_batch = [
                    e for e in events
                    if e.get("type") in ("finalization_complete", "finalization_failed")
                ]
                if notif_in_batch:
                    dl(
                        "NOTIFICATIONS",
                        "SSE_SENDING_NOTIF_EVENTS",
                        count=len(notif_in_batch),
                        events=[
                            {"type": e.get("type"), "meeting_id": e.get("meeting_id"), "timestamp": e.get("timestamp")}
                            for e in notif_in_batch
                        ],
                        new_cursor=cursor,
                    )
                for event in events:
                    yield f"data: {json.dumps(event)}\n\n"
                if not events:
                    yield "data: {\"type\":\"heartbeat\"}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @router.get("/api/meetings/{meeting_id}")
    def get_meeting(meeting_id: str, raw: bool = Query(False, description="Return raw unconsolidated segments")) -> dict:
        meeting = meeting_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        
        # Apply segment consolidation unless raw=true
        if not raw:
            transcript = meeting.get("transcript")
            if transcript and isinstance(transcript, dict):
                segments = transcript.get("segments", [])
                if segments:
                    max_duration, max_gap = _get_consolidation_settings()
                    consolidated = consolidate_segments(segments, max_duration, max_gap)
                    # Create a new transcript dict with consolidated segments
                    meeting = dict(meeting)
                    meeting["transcript"] = dict(transcript)
                    meeting["transcript"]["segments"] = consolidated
        
        # Add computed finalization fields and resolved state
        meeting["resolved_state"] = meeting_store.resolve_state(meeting_id, active_tracker)
        meeting["needs_finalization"] = meeting_store.needs_finalization(meeting)
        meeting["pending_stages"] = meeting_store.get_pending_finalization_stages(meeting)
        meeting["failed_stages"] = meeting_store.get_failed_finalization_stages(meeting)
        
        return meeting

    @router.post("/api/meetings/{meeting_id}/summary-state/step")
    def step_summary_state(meeting_id: str) -> dict:
        meeting = meeting_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        try:
            return meeting_store.step_summary_state(meeting_id, summarization_service)
        except Exception as exc:
            logger.warning("Summary state step failed: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/api/meetings/{meeting_id}/manual-buffers")
    def update_manual_buffers(meeting_id: str, payload: ManualBuffersUpdateRequest) -> dict:
        meeting = meeting_store.update_manual_buffers(
            meeting_id, payload.manual_notes, payload.manual_summary
        )
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        return meeting

    @router.patch("/api/meetings/{meeting_id}")
    def update_meeting(meeting_id: str, payload: UpdateMeetingRequest) -> dict:
        logger.info("Meeting title update: id=%s source=%s", meeting_id, payload.title_source)
        meeting = meeting_store.update_title(
            meeting_id,
            payload.title,
            source=payload.title_source or "manual",
        )
        if not meeting:
            logger.warning("Meeting not found for title update: id=%s", meeting_id)
            raise HTTPException(status_code=404, detail="Meeting not found")
        return meeting

    @router.patch("/api/meetings/{meeting_id}/attendees")
    def update_attendees(meeting_id: str, payload: UpdateAttendeesRequest) -> dict:
        meeting = meeting_store.update_attendees(meeting_id, payload.attendees)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        return meeting

    @router.patch("/api/meetings/{meeting_id}/attendees/{attendee_id}")
    def update_attendee_name(
        meeting_id: str, attendee_id: str, payload: UpdateSpeakerNameRequest
    ) -> dict:
        meeting = meeting_store.update_attendee_name(
            meeting_id, attendee_id, payload.name, source="manual"
        )
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        return meeting

    @router.post("/api/meetings/{meeting_id}/attendees/{attendee_id}/auto-rename")
    def auto_rename_attendee(meeting_id: str, attendee_id: str) -> AutoRenameResponse:
        """Use AI to suggest a name for an attendee based on their spoken content."""
        meeting = meeting_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        
        # Find the attendee
        attendees = meeting.get("attendees", [])
        attendee = next((a for a in attendees if a.get("id") == attendee_id), None)
        if not attendee:
            raise HTTPException(status_code=404, detail="Attendee not found")
        
        # Get transcript segments for this attendee
        transcript = meeting.get("transcript", {})
        segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
        
        attendee_segments = [
            seg for seg in segments
            if seg.get("speaker_id") == attendee_id or seg.get("speaker") == attendee_id
        ]
        
        if not attendee_segments:
            raise HTTPException(
                status_code=400, 
                detail="No spoken content found for this attendee"
            )
        
        # Build context from their speech
        spoken_text = "\n".join(
            f"[{seg.get('start', 0):.1f}s] {seg.get('text', '')}"
            for seg in attendee_segments[:20]  # Limit to first 20 segments
        )
        
        # Build context from other attendees' speech (for cross-references)
        other_text = ""
        for seg in segments[:30]:  # Sample of conversation
            speaker_id = seg.get("speaker_id") or seg.get("speaker")
            if speaker_id != attendee_id:
                other_text += f"{seg.get('text', '')} "
        other_text = other_text[:1000]  # Limit context size
        
        # Create prompt for AI
        prompt = f"""Analyze this meeting transcript to identify the name of the speaker.

The speaker's own words:
{spoken_text}

Context from the conversation (other speakers):
{other_text[:500] if other_text else "No other context available."}

Based on this content, what is the most likely name of this speaker?

Look for:
1. Self-introductions ("Hi, I'm...", "My name is...", "This is...")
2. Others addressing them by name
3. Professional context clues (role mentions, department, etc.)

Respond in this exact JSON format:
{{"name": "First Name" or "First Last" if available, "confidence": "high/medium/low", "reasoning": "brief explanation"}}

If you cannot determine the name, respond with:
{{"name": "Unknown Speaker", "confidence": "low", "reasoning": "No name indicators found"}}"""

        try:
            result = summarization_service.prompt_raw(prompt)
            
            # Parse the JSON response
            json_match = re.search(r'\{[^}]+\}', result)
            if json_match:
                data = json.loads(json_match.group())
                suggested_name = data.get("name", "Unknown Speaker")
                confidence = data.get("confidence", "low")
                reasoning = data.get("reasoning", "")
            else:
                # Fallback: extract any name-like text
                suggested_name = "Unknown Speaker"
                confidence = "low"
                reasoning = "Could not parse AI response"
            
            logger.info(
                "Auto-rename suggestion: meeting=%s attendee=%s suggested=%s confidence=%s",
                meeting_id, attendee_id, suggested_name, confidence
            )
            
            return AutoRenameResponse(
                suggested_name=suggested_name,
                confidence=confidence,
                reasoning=reasoning,
            )
            
        except Exception as exc:
            logger.exception("Auto-rename failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"AI analysis failed: {str(exc)}")

    @router.delete("/api/meetings/{meeting_id}")
    def delete_meeting(meeting_id: str) -> dict:
        deleted = meeting_store.delete_meeting(meeting_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Meeting not found")
        return {"status": "ok"}

    @router.get("/api/meetings/{meeting_id}/export")
    def export_meeting(meeting_id: str) -> PlainTextResponse:
        content = meeting_store.export_markdown(meeting_id)
        if content is None:
            raise HTTPException(status_code=404, detail="Meeting not found")
        return PlainTextResponse(content, media_type="text/markdown")

    @router.post("/api/meetings/fix-stuck")
    def fix_stuck_meetings() -> dict:
        """Fix meetings stuck in 'in_progress' status.
        
        Checks all in_progress meetings and marks them as completed if:
        - No active recording for that meeting
        - No active transcription job for that meeting
        
        Returns count of fixed meetings.
        """
        meetings = meeting_store.list_meetings()
        fixed_count = 0
        fixed_ids = []
        
        for meeting in meetings:
            if meeting.get("status") == "in_progress":
                meeting_id = meeting.get("id")
                if meeting_id:
                    meeting_store.update_status(meeting_id, "completed")
                    fixed_count += 1
                    fixed_ids.append(meeting_id)
                    logger.info("Fixed stuck meeting: %s", meeting_id)
        
        return {
            "status": "ok",
            "fixed_count": fixed_count,
            "fixed_ids": fixed_ids,
        }

    # ---- User Notes API ----

    @router.get("/api/meetings/{meeting_id}/notes")
    def get_user_notes(meeting_id: str) -> dict:
        """Get all user notes and current draft for a meeting."""
        meeting = meeting_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        return meeting_store.get_user_notes(meeting_id)

    @router.post("/api/meetings/{meeting_id}/notes")
    def create_user_note(meeting_id: str, payload: CreateUserNoteRequest) -> dict:
        """Create a new user note."""
        meeting = meeting_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        
        # Determine if this is a post-meeting note
        is_post_meeting = payload.is_post_meeting
        if not is_post_meeting and meeting.get("status") == "completed":
            is_post_meeting = True
        
        note = meeting_store.create_user_note(
            meeting_id,
            payload.text,
            payload.timestamp,
            is_post_meeting=is_post_meeting,
        )
        if not note:
            raise HTTPException(status_code=500, detail="Failed to create note")
        return note

    @router.patch("/api/meetings/{meeting_id}/notes/{note_id}")
    def update_user_note(
        meeting_id: str, note_id: str, payload: UpdateUserNoteRequest
    ) -> dict:
        """Update an existing user note's text (preserves original timestamp)."""
        note = meeting_store.update_user_note(meeting_id, note_id, payload.text)
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        return note

    @router.delete("/api/meetings/{meeting_id}/notes/{note_id}")
    def delete_user_note(meeting_id: str, note_id: str) -> dict:
        """Delete a user note."""
        deleted = meeting_store.delete_user_note(meeting_id, note_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Note not found")
        return {"status": "ok"}

    @router.put("/api/meetings/{meeting_id}/notes/draft")
    def save_user_notes_draft(
        meeting_id: str, payload: SaveUserNoteDraftRequest
    ) -> dict:
        """Save the current draft note (auto-save)."""
        meeting = meeting_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        
        success = meeting_store.save_user_notes_draft(
            meeting_id,
            payload.text,
            payload.timestamp,
        )
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save draft")
        return {"status": "ok"}

    # ---- Finalization error management ----

    @router.get("/api/meetings/{meeting_id}/finalization-errors")
    def get_finalization_errors(meeting_id: str) -> dict:
        """Get finalization errors and full meeting JSON for debugging."""
        meeting = meeting_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        
        errors = meeting_store.get_finalization_errors(meeting)
        failed_stages = meeting_store.get_failed_finalization_stages(meeting)
        
        return {
            "meeting_id": meeting_id,
            "has_errors": len(errors) > 0,
            "failed_stages": failed_stages,
            "errors": errors,
            "meeting_json": meeting,
        }

    class RetryFinalizationRequest(BaseModel):
        stages: Optional[list[str]] = None  # None = retry all failed stages

    @router.post("/api/meetings/{meeting_id}/retry-finalization")
    def retry_finalization(meeting_id: str, payload: RetryFinalizationRequest = None) -> dict:
        """Re-run finalization stages for a meeting.
        
        If specific stages are provided, runs them immediately in a background
        thread (not queued). If no stages specified, clears failed stages and
        wakes the background finalizer queue.
        """
        from app.services.background_finalizer import get_background_finalizer
        
        meeting = meeting_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        
        # Map human-readable labels back to stage keys
        label_to_key = {v: k for k, v in meeting_store.FINALIZATION_STAGE_LABELS.items()}
        
        stages_to_retry = None
        if payload and payload.stages:
            stages_to_retry = []
            for stage in payload.stages:
                # Accept either the key or the label
                if stage in label_to_key:
                    stages_to_retry.append(label_to_key[stage])
                elif stage in meeting_store.FINALIZATION_STAGE_LABELS:
                    stages_to_retry.append(stage)
                else:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Unknown stage: {stage}. Valid stages: {list(meeting_store.FINALIZATION_STAGE_LABELS.keys())}"
                    )
        
        bg_finalizer = get_background_finalizer()
        
        # If specific stages requested, run them immediately (not queued)
        if stages_to_retry and bg_finalizer:
            # Force stages to pending first
            updated = meeting_store.force_retry_stages(meeting_id, stages_to_retry)
            if not updated:
                raise HTTPException(status_code=500, detail="Failed to update stages")
            
            # Run all requested stages in a single thread, serially in dependency order
            # This ensures stages that depend on each other run correctly
            bg_finalizer.run_stages_now(meeting_id, stages_to_retry)
            
            logger.info(
                "Started immediate re-run: meeting_id=%s stages=%s",
                meeting_id, stages_to_retry
            )
            
            return {
                "status": "started",
                "meeting_id": meeting_id,
                "stages_started": stages_to_retry,
            }
        else:
            # No specific stages - re-run ALL finalization stages
            all_stages = ["diarization", "speaker_names", "summary"]
            updated = meeting_store.force_retry_stages(meeting_id, all_stages)
            if not updated:
                raise HTTPException(status_code=500, detail="Failed to update stages")
            
            if bg_finalizer:
                bg_finalizer.run_stages_now(meeting_id, all_stages)
                logger.info("Started re-finalization of all stages for meeting %s", meeting_id)
            
            return {
                "status": "started",
                "meeting_id": meeting_id,
                "stages_started": all_stages,
            }

    @router.post("/api/meetings/{meeting_id}/auto-fix-finalization")
    def auto_fix_finalization(meeting_id: str) -> StreamingResponse:
        """Use LLM to analyze finalization errors and suggest fixes (streaming)."""
        meeting = meeting_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        
        errors = meeting_store.get_finalization_errors(meeting)
        if not errors:
            raise HTTPException(status_code=400, detail="No failed stages to analyze")
        
        # Build prompt
        errors_text = "\n".join(
            f"- **{stage}**: {error or 'No error message recorded'}"
            for stage, error in errors.items()
        )
        
        # Get schema from meeting_store
        schema_doc = meeting_store._DATA_FOLDER_README if hasattr(meeting_store, '_DATA_FOLDER_README') else "Schema documentation not available"
        
        prompt = f"""You are debugging a meeting finalization error. Analyze the error and meeting data below.

## Error Details
{errors_text}

## Meeting JSON
```json
{json.dumps(meeting, indent=2, default=str)}
```

## Expected Schema
{schema_doc}

Identify what went wrong and suggest a specific fix. If the error is:
- Transient (network, timeout): Recommend clicking "Retry"
- Data corruption: Suggest what JSON needs to be corrected
- Missing dependencies (e.g., no audio file): Explain what's needed

Respond with:
1. **Root Cause Analysis**: What likely caused this error
2. **Recommended Action**: What the user should do
3. **Technical Details**: Any relevant technical information for debugging

Keep your response concise and actionable."""

        def generate():
            try:
                for token in summarization_service.prompt_stream(prompt):
                    yield token
            except Exception as exc:
                logger.warning("Auto-fix LLM error: %s", exc)
                yield f"\n\n**Error during analysis**: {type(exc).__name__}: {str(exc)}"

        return StreamingResponse(generate(), media_type="text/plain")

    return router
