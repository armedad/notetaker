import logging
import os

from fastapi import APIRouter, HTTPException
from typing import Optional

from pydantic import BaseModel, Field

from app.services.meeting_store import MeetingStore
from app.services.summarization import SummarizationService
from app.services.llm.base import LLMProviderError


class SummarizeRequest(BaseModel):
    provider: Optional[str] = Field(None, description="Optional provider override")

class ManualSummarizeRequest(BaseModel):
    transcript_text: str = Field(..., min_length=1, description="Transcript to summarize")
    provider: Optional[str] = Field(None, description="Optional provider override")


def create_summarization_router(
    meeting_store: MeetingStore, summarization_service: SummarizationService
) -> APIRouter:
    router = APIRouter()
    logger = logging.getLogger("notetaker.api.summarization")
    prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", "summary_prompt.txt")

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

    @router.post("/api/meetings/{meeting_id}/manual-summarize")
    def manual_summarize_meeting(meeting_id: str, payload: ManualSummarizeRequest) -> dict:
        meeting = meeting_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        try:
            # Use the same summarization flow + prompt file as final summarization.
            result = summarization_service.summarize(
                payload.transcript_text, provider_override=payload.provider
            )
        except LLMProviderError as exc:
            logger.warning("Manual summarization failed: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Manual summarization error: %s", exc)
            raise HTTPException(status_code=500, detail="Manual summarization failed") from exc

        summary_text = str(result.get("summary", "")).strip()
        action_items = result.get("action_items", []) or []

        # Persist to meeting summary and attempt one-time title generation.
        meeting_store.add_summary(
            meeting_id,
            summary=summary_text,
            action_items=action_items,
            provider=payload.provider or "default",
        )
        try:
            if summary_text:
                meeting_store.maybe_auto_title(
                    meeting_id,
                    summary_text,
                    summarization_service,
                    provider_override=payload.provider,
                    force=False,
                )
        except LLMProviderError as exc:
            logger.warning("Manual auto-title failed: %s", exc)
        except Exception as exc:
            logger.exception("Manual auto-title error: %s", exc)

        # Also mirror into the manual buffer so the textarea persists even if user edits later.
        existing_notes = meeting.get("manual_notes", "") if isinstance(meeting, dict) else ""
        meeting_store.update_manual_buffers(meeting_id, existing_notes or "", summary_text)

        updated = meeting_store.get_meeting(meeting_id) or {}
        return {
            "summary_text": summary_text,
            "prompt_path": prompt_path,
            "meeting": updated,
            "action_items": action_items,
        }

    return router
