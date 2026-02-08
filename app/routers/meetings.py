from typing import Optional

import json
import logging
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.services.meeting_store import MeetingStore


class UpdateMeetingRequest(BaseModel):
    title: str = Field(..., min_length=1)
    title_source: Optional[str] = None


class UpdateAttendeesRequest(BaseModel):
    attendees: list[dict]


class UpdateSpeakerNameRequest(BaseModel):
    name: str = Field(..., min_length=1)


def create_meetings_router(
    meeting_store: MeetingStore, summarization_service
) -> APIRouter:
    router = APIRouter()
    logger = logging.getLogger("notetaker.api.meetings")

    @router.get("/api/meetings")
    def list_meetings() -> list[dict]:
        return meeting_store.list_meetings()

    @router.get("/api/meetings/events")
    def meeting_events() -> StreamingResponse:
        logger.info("Meetings SSE connected")

        def event_stream():
            cursor = 0
            while True:
                events, cursor = meeting_store.get_events_since(cursor)
                for event in events:
                    yield f"data: {json.dumps(event)}\n\n"
                yield "data: {\"type\":\"heartbeat\"}\n\n"
                time.sleep(2)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @router.get("/api/meetings/{meeting_id}")
    def get_meeting(meeting_id: str) -> dict:
        meeting = meeting_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
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

    return router
