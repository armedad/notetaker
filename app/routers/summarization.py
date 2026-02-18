import json
import logging
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
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
        # Get user notes for inclusion in summary
        user_notes = meeting.get("user_notes", [])
        try:
            result = summarization_service.summarize(
                transcript_text, provider_override=payload.provider, user_notes=user_notes
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

    @router.post("/api/meetings/{meeting_id}/summarize-stream")
    def summarize_stream(meeting_id: str, payload: ManualSummarizeRequest):
        """Stream summary generation via Server-Sent Events.
        
        Returns an SSE stream with tokens as they are generated by the LLM.
        Each line is in the format: data: {"token": "..."}\n\n
        Stream ends with: data: [DONE]\n\n
        """
        meeting = meeting_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        
        transcript_text = payload.transcript_text
        if not transcript_text.strip():
            raise HTTPException(status_code=400, detail="Transcript text is empty")
        
        # Get user notes for inclusion in summary
        user_notes = meeting.get("user_notes", [])
        
        def generate():
            # #region agent log
            import time as _time
            _log_path = os.path.join(os.getcwd(), "logs", "debug.log")
            def _dbg(msg, data=None):
                with open(_log_path, "a") as _f:
                    _f.write(json.dumps({"location":"summarization.py:generate","message":msg,"data":data or {},"timestamp":int(_time.time()*1000),"hypothesisId":"H2"})+"\n")
            _dbg("generate_start")
            _sse_count = 0
            # #endregion
            accumulated_text = ""
            try:
                for token in summarization_service.summarize_stream(
                    transcript_text, provider_override=payload.provider, user_notes=user_notes
                ):
                    accumulated_text += token
                    # #region agent log
                    _sse_count += 1
                    if _sse_count <= 5 or _sse_count % 20 == 0:
                        _dbg("sse_yield", {"sse_num": _sse_count, "token_len": len(token)})
                    # #endregion
                    yield f"data: {json.dumps({'token': token})}\n\n"
            except LLMProviderError as exc:
                logger.warning("Streaming summarization failed: %s", exc)
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            except Exception as exc:
                logger.exception("Streaming summarization error: %s", exc)
                yield f"data: {json.dumps({'error': 'Summarization failed'})}\n\n"
            finally:
                # #region agent log
                _dbg("generate_finally", {"total_sse": _sse_count})
                # #endregion
                # Signal completion
                yield "data: [DONE]\n\n"
                
                # After streaming completes, save the accumulated summary
                if accumulated_text.strip():
                    try:
                        # Store the raw streaming result as manual summary
                        existing_notes = meeting.get("manual_notes", "") if isinstance(meeting, dict) else ""
                        meeting_store.update_manual_buffers(
                            meeting_id, existing_notes or "", accumulated_text.strip()
                        )
                    except Exception as save_exc:
                        logger.warning("Failed to save streaming summary: %s", save_exc)
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable buffering in nginx
            }
        )

    class AutoTitleRequest(BaseModel):
        summary_text: str = Field(..., min_length=1, description="Summary text to generate title from")
        provider: Optional[str] = Field(None, description="Optional provider override")

    @router.post("/api/meetings/{meeting_id}/auto-title")
    def auto_title(meeting_id: str, payload: AutoTitleRequest) -> dict:
        """Generate and set an auto-title for a meeting based on summary text."""
        meeting = meeting_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        
        try:
            # First save the summary
            meeting_store.add_summary(
                meeting_id,
                summary=payload.summary_text,
                action_items=[],
                provider=payload.provider or "default",
            )
            
            # Then generate title
            meeting_store.maybe_auto_title(
                meeting_id,
                payload.summary_text,
                summarization_service,
                provider_override=payload.provider,
                force=True,
            )
            
            meeting_store.update_status(meeting_id, "completed")
            
            updated = meeting_store.get_meeting(meeting_id) or {}
            return {"title": updated.get("title", ""), "meeting": updated}
        except LLMProviderError as exc:
            logger.warning("Auto-title failed: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Auto-title error: %s", exc)
            raise HTTPException(status_code=500, detail="Auto-title failed") from exc

    return router
