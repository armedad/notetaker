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


def create_meetings_router(
    meeting_store: MeetingStore, summarization_service, config_path: str = None
) -> APIRouter:
    router = APIRouter()
    logger = logging.getLogger("notetaker.api.meetings")
    
    def _get_consolidation_settings() -> tuple[float, float]:
        """Load consolidation settings from config, with defaults."""
        max_duration = 15.0
        max_gap = 2.0
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                transcription = data.get("transcription", {})
                max_duration = transcription.get("consolidation_max_duration", 15.0)
                max_gap = transcription.get("consolidation_max_gap", 2.0)
            except Exception:
                pass  # Use defaults on error
        return max_duration, max_gap

    @router.get("/api/meetings")
    def list_meetings() -> list[dict]:
        return meeting_store.list_meetings()

    @router.get("/api/meetings/events")
    def meeting_events() -> StreamingResponse:
        logger.info("Meetings SSE connected")

        def event_stream():
            cursor = 0
            while True:
                # Block until events are available (true push-based SSE)
                # Timeout after 5s to send heartbeat for connection keepalive
                events, cursor = meeting_store.wait_for_events(cursor, timeout=5.0)
                for event in events:
                    yield f"data: {json.dumps(event)}\n\n"
                # Send heartbeat if no events (timeout expired)
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
            meeting_id, attendee_id, payload.name
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

    return router
