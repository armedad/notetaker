import logging
import time

import json
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.audio_capture import AudioCaptureService
from app.services.meeting_store import MeetingStore
from app.services.active_meeting_tracker import get_tracker, MeetingState


class StartRecordingRequest(BaseModel):
    device_index: Optional[int] = Field(
        None,
        description="Input device index; omit to use system default",
    )
    samplerate: int = Field(48000, description="Sample rate in Hz")
    channels: int = Field(2, description="Number of input channels (<= device max)")


class AudioConfigRequest(BaseModel):
    use_system_device: Optional[bool] = Field(
        None,
        description="When true, use the OS default input device",
    )
    device_index: Optional[int] = Field(
        None, description="Input device index from /api/audio/devices"
    )
    samplerate: Optional[int] = Field(None, description="Sample rate in Hz")
    channels: Optional[int] = Field(None, description="Number of input channels (<= device max)")
    source: Optional[str] = Field(None, description="Recording source: device or file")


def create_recording_router(
    audio_service: AudioCaptureService,
    meeting_store: MeetingStore,
    summarization_service,
    config_path: str,
) -> APIRouter:
    router = APIRouter()
    logger = logging.getLogger("notetaker.api.recording")

    def load_config() -> dict:
        if not os.path.exists(config_path):
            return {}
        with open(config_path, "r", encoding="utf-8") as config_file:
            return json.load(config_file)

    def save_config(data: dict) -> None:
        with open(config_path, "w", encoding="utf-8") as config_file:
            json.dump(data, config_file, indent=2)

    @router.get("/api/audio/devices")
    def list_devices() -> dict:
        devices = audio_service.list_devices()
        try:
            system_default = audio_service.get_system_default_device()
        except Exception:
            system_default = None
        return {"devices": devices, "system_default": system_default}

    def _merged_audio_settings(stored: dict, live: dict) -> dict:
        use_system = stored.get("use_system_device")
        if use_system is None:
            # Legacy configs: explicit device_index means a fixed device.
            use_system = stored.get("device_index") is None and live.get("device_index") is None
        merged = {
            "use_system_device": bool(use_system),
            "device_index": stored.get("device_index", live.get("device_index")),
            "samplerate": stored.get("samplerate", live.get("samplerate")),
            "channels": stored.get("channels", live.get("channels")),
            "source": stored.get("source", "device"),
        }
        if merged["use_system_device"]:
            merged["device_index"] = None
        return merged

    @router.get("/api/recording/status")
    def recording_status() -> dict:
        return audio_service.current_status()

    @router.post("/api/recording/start")
    def start_recording(payload: StartRecordingRequest) -> dict:
        start_time = time.perf_counter()
        logger.debug("start_recording received: %s", payload.model_dump())
        active_tracker = get_tracker()
        try:
            result = audio_service.start_recording(
                device_index=payload.device_index,
                samplerate=payload.samplerate,
                channels=payload.channels,
            )
            meeting_store.create_from_recording(result, status="in_progress")
            meeting_id = result.get("recording_id")
            audio_path = result.get("file_path")
            # Register with active_tracker so status endpoint returns correct state
            if meeting_id:
                active_tracker.register(
                    meeting_id,
                    MeetingState.RECORDING,
                    audio_source="microphone",
                    audio_path=audio_path,
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
        active_tracker = get_tracker()
        try:
            result = audio_service.stop_recording()
            meeting = meeting_store.create_from_recording(result, status="completed")
            # Unregister from active tracker
            meeting_id = result.get("recording_id")
            if meeting_id:
                active_tracker.unregister(meeting_id)
            if meeting:
                meeting_id = meeting.get("id")
                transcript = meeting.get("transcript", {})
                segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
                transcript_text = "\n".join(
                    seg.get("text", "") for seg in segments if isinstance(seg, dict)
                )
                if transcript_text.strip() and meeting_id:
                    try:
                        meeting_store.maybe_auto_title(
                            meeting_id,
                            transcript_text[:4000],
                            summarization_service,
                            force=True,
                        )
                    except Exception as exc:
                        logger.warning("Auto-title on stop failed: %s", exc)
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

    @router.get("/api/settings/audio")
    def get_audio_settings() -> dict:
        config = load_config()
        stored = config.get("audio", {})
        live = audio_service.get_config()
        merged = _merged_audio_settings(stored, live)
        audio_service.update_config(
            device_index=merged.get("device_index"),
            samplerate=merged.get("samplerate"),
            channels=merged.get("channels"),
            use_system_device=merged.get("use_system_device"),
        )
        try:
            merged["system_default"] = audio_service.get_system_default_device()
        except Exception:
            merged["system_default"] = None
        return merged

    @router.post("/api/settings/audio")
    def set_audio_settings(payload: AudioConfigRequest) -> dict:
        logger.debug("set_audio_settings received: %s", payload.model_dump())
        data = load_config()
        audio_config = data.get("audio", {})
        if payload.use_system_device is not None:
            audio_config["use_system_device"] = payload.use_system_device
            if payload.use_system_device:
                audio_config["device_index"] = None
        if payload.device_index is not None:
            audio_config["device_index"] = payload.device_index
            audio_config["use_system_device"] = False
        if payload.samplerate is not None:
            audio_config["samplerate"] = payload.samplerate
        if payload.channels is not None:
            audio_config["channels"] = payload.channels
        if payload.source is not None:
            audio_config["source"] = payload.source
        data["audio"] = audio_config
        save_config(data)
        audio_service.update_config(
            device_index=audio_config.get("device_index"),
            samplerate=audio_config.get("samplerate"),
            channels=audio_config.get("channels"),
            use_system_device=audio_config.get("use_system_device"),
        )
        return {"status": "ok"}

    return router
