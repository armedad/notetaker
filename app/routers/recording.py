import logging
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.audio_capture import AudioCaptureService


class StartRecordingRequest(BaseModel):
    device_index: int = Field(..., description="Input device index from /api/audio/devices")
    samplerate: int = Field(48000, description="Sample rate in Hz")
    channels: int = Field(2, description="Number of input channels (<= device max)")


def create_recording_router(audio_service: AudioCaptureService) -> APIRouter:
    router = APIRouter()
    logger = logging.getLogger("notetaker.api.recording")

    @router.get("/api/audio/devices")
    def list_devices() -> list[dict]:
        return audio_service.list_devices()

    @router.get("/api/recording/status")
    def recording_status() -> dict:
        return audio_service.current_status()

    @router.post("/api/recording/start")
    def start_recording(payload: StartRecordingRequest) -> dict:
        start_time = time.perf_counter()
        logger.debug("start_recording received: %s", payload.model_dump())
        try:
            result = audio_service.start_recording(
                device_index=payload.device_index,
                samplerate=payload.samplerate,
                channels=payload.channels,
            )
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info("start_recording completed in %.2f ms", duration_ms)
            return result
        except RuntimeError as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.warning("start_recording failed in %.2f ms: %s", duration_ms, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.exception("start_recording error in %.2f ms: %s", duration_ms, exc)
            raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    @router.post("/api/recording/stop")
    def stop_recording() -> dict:
        start_time = time.perf_counter()
        logger.debug("stop_recording received")
        try:
            result = audio_service.stop_recording()
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info("stop_recording completed in %.2f ms", duration_ms)
            return result
        except RuntimeError as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.warning("stop_recording failed in %.2f ms: %s", duration_ms, exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.exception("stop_recording error in %.2f ms: %s", duration_ms, exc)
            raise HTTPException(status_code=500, detail="Internal Server Error") from exc

    return router
