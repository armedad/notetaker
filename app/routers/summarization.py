import logging

from fastapi import APIRouter, HTTPException
from typing import Optional

from pydantic import BaseModel, Field

from app.services.meeting_store import MeetingStore
from app.services.summarization import SummarizationService
from app.services.llm.base import LLMProviderError


class SummarizeRequest(BaseModel):
    provider: Optional[str] = Field(None, description="Optional provider override")


def create_summarization_router(
    meeting_store: MeetingStore, summarization_service: SummarizationService
) -> APIRouter:
    router = APIRouter()
    logger = logging.getLogger("notetaker.api.summarization")

    @router.post("/api/meetings/{meeting_id}/summarize")
    def summarize_meeting(meeting_id: str, payload: SummarizeRequest) -> dict:
        meeting = meeting_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        transcript = meeting.get("transcript", {})
        segments = transcript.get("segments") if isinstance(transcript, dict) else None
        if not segments:
            raise HTTPException(status_code=400, detail="Transcript not found")
        transcript_text = "\n".join(
            segment.get("text", "")
            for segment in segments
            if isinstance(segment, dict)
        )
        try:
            result = summarization_service.summarize(
                transcript_text, provider_override=payload.provider
            )
        except LLMProviderError as exc:
            logger.warning("Summarization failed: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        meeting_store.add_summary(
            meeting_id,
            summary=result.get("summary", ""),
            action_items=result.get("action_items", []),
            provider=payload.provider or "default",
        )
        try:
            summary_text = result.get("summary", "").strip()
            if summary_text:
                force_title = meeting.get("status") == "completed"
                meeting_store.maybe_auto_title(
                    meeting_id,
                    summary_text,
                    summarization_service,
                    provider_override=payload.provider,
                    force=force_title,
                )
        except LLMProviderError as exc:
            logger.warning("Auto-title failed: %s", exc)
        except Exception as exc:
            logger.exception("Auto-title error: %s", exc)
        return result

    return router
