import logging
import os
import time
from typing import Optional

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.transcription import (
    FasterWhisperProvider,
    TranscriptionProviderError,
    WhisperConfig,
)


class TranscribeRequest(BaseModel):
    audio_path: str = Field(..., description="Absolute path to audio file")


class TranscribeResponse(BaseModel):
    language: Optional[str]
    duration: float
    segments: list[dict]


def create_transcription_router(config: dict) -> APIRouter:
    router = APIRouter()
    logger = logging.getLogger("notetaker.api.transcription")

    transcription_config = config.get("transcription", {})
    provider_name = transcription_config.get("provider", "faster-whisper")
    if provider_name != "faster-whisper":
        raise RuntimeError(f"Unsupported transcription provider: {provider_name}")

    provider = FasterWhisperProvider(
        WhisperConfig(
            model_size=transcription_config.get("model_size", "base"),
            device=transcription_config.get("device", "cpu"),
            compute_type=transcription_config.get("compute_type", "int8"),
        )
    )

    @router.post("/api/transcribe", response_model=TranscribeResponse)
    def transcribe(payload: TranscribeRequest) -> TranscribeResponse:
        start_time = time.perf_counter()
        logger.debug("transcribe received: %s", payload.model_dump())

        audio_path = payload.audio_path
        if not os.path.isabs(audio_path):
            raise HTTPException(status_code=400, detail="audio_path must be absolute")

        try:
            result = provider.transcribe(audio_path)
        except TranscriptionProviderError as exc:
            logger.warning("transcribe failed: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("transcribe error: %s", exc)
            raise HTTPException(status_code=500, detail="Internal Server Error") from exc

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info("transcribe completed in %.2f ms", duration_ms)

        return TranscribeResponse(
            language=result.language,
            duration=result.duration,
            segments=[
                {
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "speaker": segment.speaker,
                }
                for segment in result.segments
            ],
        )

    @router.post("/api/transcribe/stream")
    def transcribe_stream(payload: TranscribeRequest) -> StreamingResponse:
        logger.debug("transcribe_stream received: %s", payload.model_dump())
        audio_path = payload.audio_path
        if not os.path.isabs(audio_path):
            raise HTTPException(status_code=400, detail="audio_path must be absolute")

        def event_stream():
            try:
                segments_iter, info = provider.stream_segments(audio_path)
                meta = {
                    "type": "meta",
                    "language": getattr(info, "language", None),
                }
                yield f"data: {json.dumps(meta)}\n\n"
                for segment in segments_iter:
                    payload_segment = {
                        "type": "segment",
                        "start": float(segment.start),
                        "end": float(segment.end),
                        "text": segment.text.strip(),
                        "speaker": None,
                    }
                    yield f"data: {json.dumps(payload_segment)}\n\n"
                yield "data: {\"type\":\"done\"}\n\n"
            except TranscriptionProviderError as exc:
                logger.warning("transcribe_stream failed: %s", exc)
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            except Exception as exc:
                logger.exception("transcribe_stream error: %s", exc)
                yield "data: {\"type\":\"error\",\"message\":\"Internal Server Error\"}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return router
