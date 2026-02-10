import logging
import threading
import os
import time
from typing import Optional

import json

import tempfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.audio_capture import AudioCaptureService
from app.services.meeting_store import MeetingStore
from app.services.diarization import DiarizationService
from app.services.diarization.providers.base import DiarizationConfig
from app.services.transcription import (
    FasterWhisperProvider,
    TranscriptionProviderError,
    WhisperConfig,
)
from app.services.summarization import SummarizationService
from app.services.llm.base import LLMProviderError
from app.services.transcription_pipeline import TranscriptionPipeline, apply_diarization

class TranscribeRequest(BaseModel):
    audio_path: str = Field(..., description="Absolute path to audio file")
    model_size: Optional[str] = Field(
        None, description="Override model size for this request"
    )
    meeting_id: Optional[str] = Field(
        None, description="Meeting id (optional)"
    )
    simulate_live: bool = Field(
        False, description="Simulate live recording flow when transcribing file"
    )


class SimulateTranscribeRequest(BaseModel):
    audio_path: str = Field(..., description="Absolute path to audio file")
    model_size: Optional[str] = Field(
        None, description="Override model size for this request"
    )
    meeting_id: Optional[str] = Field(
        None, description="Meeting id (optional)"
    )


class TranscribeResponse(BaseModel):
    language: Optional[str]
    duration: float
    segments: list[dict]


class LiveTranscribeRequest(BaseModel):
    model_size: Optional[str] = Field(
        None, description="Override model size for live transcription"
    )
    meeting_id: Optional[str] = Field(
        None, description="Meeting id for live transcript storage"
    )


class DiarizationSettingsRequest(BaseModel):
    enabled: bool
    provider: str
    model: str
    device: str
    hf_token: Optional[str]
    performance_level: float = 0.5


def _write_temp_wav(buffer: bytes, samplerate: int, channels: int) -> tuple[str, float]:
    frames = len(buffer) // (2 * channels)
    duration = frames / samplerate if samplerate > 0 else 0.0
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
        tmp_path = tmp_file.name
    import numpy as np
    import soundfile as sf

    audio = np.frombuffer(buffer, dtype=np.int16)
    if channels > 1:
        audio = audio.reshape(-1, channels)
    with sf.SoundFile(
        tmp_path,
        mode="w",
        samplerate=samplerate,
        channels=channels,
        subtype="PCM_16",
    ) as sound_file:
        sound_file.write(audio)
    return tmp_path, duration


def create_transcription_router(
    config: dict,
    audio_service: AudioCaptureService,
    meeting_store: MeetingStore,
    summarization_service: SummarizationService,
) -> APIRouter:
    router = APIRouter()
    logger = logging.getLogger("notetaker.api.transcription")
    simulate_jobs: dict[str, dict] = {}

    transcription_config = config.get("transcription", {})
    provider_name = transcription_config.get("provider", "faster-whisper")
    if provider_name != "faster-whisper":
        raise RuntimeError(f"Unsupported transcription provider: {provider_name}")

    diarization_config = config.get("diarization", {})
    diarization_service = DiarizationService(
        DiarizationConfig(
            enabled=bool(diarization_config.get("enabled", False)),
            provider=diarization_config.get("provider", "pyannote"),
            model=diarization_config.get(
                "model", "pyannote/speaker-diarization-3.1"
            ),
            device=diarization_config.get("device", "cpu"),
            hf_token=diarization_config.get("hf_token"),
            performance_level=float(diarization_config.get("performance_level", 0.5)),
        )
    )

    live_device = transcription_config.get("live_device", "cpu")
    live_compute = transcription_config.get("live_compute_type", "int8")
    final_device = transcription_config.get("final_device", "cpu")
    final_compute = transcription_config.get("final_compute_type", "int8")
    live_default_size = transcription_config.get("live_model_size", "base")
    final_default_size = transcription_config.get("final_model_size", "small")

    provider_cache: dict[tuple[str, str, str], FasterWhisperProvider] = {}

    def get_provider(model_size: str, device: str, compute_type: str) -> FasterWhisperProvider:
        key = (model_size, device, compute_type)
        if key not in provider_cache:
            provider_cache[key] = FasterWhisperProvider(
                WhisperConfig(
                    model_size=model_size,
                    device=device,
                    compute_type=compute_type,
                ),
                diarization_service,
            )
        return provider_cache[key]

    def get_pipeline(model_size: str, device: str, compute_type: str) -> TranscriptionPipeline:
        """Get a transcription pipeline with the specified provider configuration."""
        provider = get_provider(model_size, device, compute_type)
        return TranscriptionPipeline(
            provider=provider,
            diarization_service=diarization_service,
            meeting_store=meeting_store,
            summarization_service=summarization_service,
        )

    @router.post("/api/transcribe", response_model=TranscribeResponse)
    def transcribe(payload: TranscribeRequest) -> TranscribeResponse:
        start_time = time.perf_counter()
        logger.debug("transcribe received: %s", payload.model_dump())

        audio_path = payload.audio_path
        if not os.path.isabs(audio_path):
            raise HTTPException(status_code=400, detail="audio_path must be absolute")

        model_size = payload.model_size or final_default_size
        pipeline = get_pipeline(model_size, final_device, final_compute)
        
        try:
            segments, language = pipeline.process_audio_file(
                audio_path,
                meeting_id=payload.meeting_id,
                apply_diarization=True,
                update_meeting_live=False,
            )
        except TranscriptionProviderError as exc:
            logger.warning("transcribe failed: %s", exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("transcribe error: %s", exc)
            raise HTTPException(status_code=500, detail="Internal Server Error") from exc

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info("transcribe completed in %.2f ms", duration_ms)

        return TranscribeResponse(
            language=language,
            duration=duration_ms / 1000.0,
            segments=segments,
        )

    @router.post("/api/transcribe/stream")
    def transcribe_stream(payload: TranscribeRequest) -> StreamingResponse:
        """Streaming file transcription using the unified pipeline."""
        logger.debug("transcribe_stream received: %s", payload.model_dump())
        audio_path = payload.audio_path
        if not os.path.isabs(audio_path):
            raise HTTPException(status_code=400, detail="audio_path must be absolute")

        def event_stream():
            try:
                model_size = payload.model_size or final_default_size
                pipeline = get_pipeline(model_size, final_device, final_compute)
                meeting_id = payload.meeting_id
                
                if payload.simulate_live and not meeting_id:
                    meeting = meeting_store.create_simulated_meeting(audio_path)
                    meeting_id = meeting.get("id")
                    logger.info(
                        "Streaming transcription started: meeting_id=%s audio=%s",
                        meeting_id,
                        audio_path,
                    )
                
                # Use pipeline for transcription
                segments, language = pipeline.transcribe_and_format(audio_path)
                
                # Stream metadata
                meta = {"type": "meta", "language": language}
                if meeting_id and payload.simulate_live:
                    meeting_store.append_live_meta(meeting_id, language)
                yield f"data: {json.dumps(meta)}\n\n"
                
                # Stream segments
                for segment in segments:
                    if meeting_id and payload.simulate_live:
                        meeting_store.append_live_segment(meeting_id, segment, language)
                    yield f"data: {json.dumps(segment)}\n\n"
                
                # Apply diarization (after all segments streamed)
                segments = pipeline.run_diarization(audio_path, segments)
                if diarization_service.is_enabled() and meeting_id:
                    meeting_store.update_transcript_speakers(meeting_id, segments)
                
                # Save transcript
                meeting_store.add_transcript(audio_path, language, segments)
                
                # Finalize if simulating live
                if meeting_id and payload.simulate_live:
                    pipeline.finalize_meeting(meeting_id, segments)
                
                yield "data: {\"type\":\"done\"}\n\n"
                
            except TranscriptionProviderError as exc:
                logger.warning("transcribe_stream failed: %s", exc)
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            except Exception as exc:
                logger.exception("transcribe_stream error: %s", exc)
                yield "data: {\"type\":\"error\",\"message\":\"Internal Server Error\"}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    def _run_simulated_transcription(
        job_id: str,
        meeting_id: str,
        audio_path: str,
        model_size: str,
        cancel_event: threading.Event,
    ) -> None:
        """Run simulated transcription using the unified pipeline."""
        try:
            if cancel_event.is_set():
                logger.info("Simulated transcription cancelled before start: meeting_id=%s", meeting_id)
                meeting_store.update_status(meeting_id, "completed")
                return
            
            pipeline = get_pipeline(model_size, final_device, final_compute)
            
            # Use pipeline for transcription with live updates
            # Note: We need to handle cancellation during transcription, so we do it in stages
            
            # Stage 1: Transcribe and format (with live segment updates)
            segments, language = pipeline.transcribe_and_format(audio_path)
            
            # Update meeting store with segments as they're processed
            meeting_store.append_live_meta(meeting_id, language)
            for segment in segments:
                if cancel_event.is_set():
                    logger.info("Simulated transcription cancelled: meeting_id=%s", meeting_id)
                    meeting_store.update_status(meeting_id, "completed")
                    break
                meeting_store.append_live_segment(meeting_id, segment, language)
            
            if cancel_event.is_set():
                return
            
            # Stage 2: Apply diarization
            segments = pipeline.run_diarization(audio_path, segments)
            if diarization_service.is_enabled():
                meeting_store.update_transcript_speakers(meeting_id, segments)
            
            # Stage 3: Save transcript
            meeting_store.add_transcript(audio_path, language, segments)
            
            # Stage 4: Finalize (summarize + title)
            pipeline.finalize_meeting(meeting_id, segments)
            
        except TranscriptionProviderError as exc:
            logger.warning("Simulated transcription failed: %s", exc)
        except Exception as exc:
            logger.exception("Simulated transcription error: %s", exc)
        finally:
            simulate_jobs.pop(job_id, None)
            logger.info("Simulated transcription finished: meeting_id=%s", meeting_id)

    @router.post("/api/transcribe/simulate")
    def simulate_transcribe(payload: SimulateTranscribeRequest) -> dict:
        audio_path = payload.audio_path
        if not os.path.isabs(audio_path):
            raise HTTPException(status_code=400, detail="audio_path must be absolute")
        existing = next(
            (job for job in simulate_jobs.values() if job.get("audio_path") == audio_path),
            None,
        )
        if existing:
            return {"status": "running", "meeting_id": existing.get("meeting_id")}
        meeting = None
        if payload.meeting_id:
            # Resuming an existing meeting - use the provided meeting_id
            meeting = meeting_store.get_meeting(payload.meeting_id)
            if not meeting:
                raise HTTPException(status_code=404, detail="Meeting not found")
        else:
            # Starting fresh from main window - always create a new meeting
            meeting = meeting_store.create_simulated_meeting(audio_path)
        meeting_id = meeting.get("id")
        if not meeting_id:
            raise HTTPException(status_code=500, detail="Failed to create meeting")
        meeting_store.update_status(meeting_id, "in_progress")
        model_size = payload.model_size or final_default_size
        cancel_event = threading.Event()
        thread = threading.Thread(
            target=_run_simulated_transcription,
            args=(meeting_id, meeting_id, audio_path, model_size, cancel_event),
            daemon=True,
        )
        simulate_jobs[meeting_id] = {
            "meeting_id": meeting_id,
            "audio_path": audio_path,
            "thread": thread,
            "cancel": cancel_event,
        }
        logger.info(
            "Simulated transcription started: meeting_id=%s audio=%s",
            meeting_id,
            audio_path,
        )
        thread.start()
        return {"status": "started", "meeting_id": meeting_id}

    @router.get("/api/transcribe/simulate/status")
    def simulate_status(audio_path: str) -> dict:
        job = next(
            (job for job in simulate_jobs.values() if job.get("audio_path") == audio_path),
            None,
        )
        if not job:
            return {"status": "idle", "meeting_id": None}
        return {
            "status": "running",
            "meeting_id": job.get("meeting_id"),
            "audio_path": job.get("audio_path"),
        }

    @router.post("/api/transcribe/simulate/stop")
    def simulate_stop(audio_path: str) -> dict:
        job = next(
            (job for job in simulate_jobs.values() if job.get("audio_path") == audio_path),
            None,
        )
        if not job:
            return {"status": "idle"}
        cancel_event = job.get("cancel")
        if cancel_event:
            cancel_event.set()
        meeting_id = job.get("meeting_id")
        if meeting_id:
            meeting_store.update_status(meeting_id, "completed")
        return {"status": "stopping", "meeting_id": job.get("meeting_id")}

    @router.get("/api/transcribe/active")
    def get_active_transcription() -> dict:
        """Get currently active transcription job, if any."""
        # Check for simulated (file) transcription
        if simulate_jobs:
            job = next(iter(simulate_jobs.values()))
            return {
                "active": True,
                "type": "file",
                "meeting_id": job.get("meeting_id"),
                "audio_path": job.get("audio_path"),
            }
        # Check for live recording
        status = audio_service.current_status()
        if status.get("recording"):
            return {
                "active": True,
                "type": "live",
                "meeting_id": status.get("recording_id"),
                "audio_path": status.get("file_path"),
            }
        return {"active": False, "type": None, "meeting_id": None, "audio_path": None}

    @router.post("/api/transcribe/stop/{meeting_id}")
    def stop_transcription_by_meeting(meeting_id: str) -> dict:
        """Stop transcription for a specific meeting."""
        # Check simulated jobs
        job = next(
            (job for job in simulate_jobs.values() if job.get("meeting_id") == meeting_id),
            None,
        )
        if job:
            cancel_event = job.get("cancel")
            if cancel_event:
                cancel_event.set()
            meeting_store.update_status(meeting_id, "completed")
            logger.info("Stopped file transcription: meeting_id=%s", meeting_id)
            return {"status": "stopping", "meeting_id": meeting_id, "type": "file"}
        # Check live recording
        status = audio_service.current_status()
        if status.get("recording") and status.get("recording_id") == meeting_id:
            audio_service.stop_recording()
            meeting_store.update_status(meeting_id, "completed")
            logger.info("Stopped live transcription: meeting_id=%s", meeting_id)
            return {"status": "stopping", "meeting_id": meeting_id, "type": "live"}
        return {"status": "not_found", "meeting_id": meeting_id}

    @router.post("/api/transcribe/resume/{meeting_id}")
    def resume_transcription(meeting_id: str) -> dict:
        """Resume transcription for a meeting that was stopped."""
        # Check if any transcription is already running
        if simulate_jobs:
            raise HTTPException(
                status_code=409,
                detail="Another transcription is already in progress"
            )
        status = audio_service.current_status()
        if status.get("recording"):
            raise HTTPException(
                status_code=409,
                detail="A live recording is already in progress"
            )
        # Get meeting and its audio path
        meeting = meeting_store.get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found")
        audio_path = meeting.get("audio_path")
        if not audio_path:
            raise HTTPException(status_code=400, detail="Meeting has no audio file")
        if not os.path.exists(audio_path):
            raise HTTPException(status_code=400, detail="Audio file not found")
        # Update meeting status back to in_progress
        meeting_store.update_status(meeting_id, "in_progress")
        # Start transcription
        model_size = transcription_config.get("model_size", "medium")
        cancel_event = threading.Event()
        thread = threading.Thread(
            target=_run_simulated_transcription,
            args=(meeting_id, meeting_id, audio_path, model_size, cancel_event),
            daemon=True,
        )
        simulate_jobs[meeting_id] = {
            "meeting_id": meeting_id,
            "audio_path": audio_path,
            "thread": thread,
            "cancel": cancel_event,
        }
        logger.info("Resumed transcription: meeting_id=%s audio=%s", meeting_id, audio_path)
        thread.start()
        return {"status": "resumed", "meeting_id": meeting_id}

    @router.post("/api/transcribe/live")
    def transcribe_live(payload: LiveTranscribeRequest) -> StreamingResponse:
        """Live transcription from microphone using the unified pipeline."""
        logger.debug("transcribe_live received: %s", payload.model_dump())
        live_chunk_seconds = float(
            transcription_config.get("live_chunk_seconds", 5.0)
        )
        model_size = payload.model_size or live_default_size
        pipeline = get_pipeline(model_size, live_device, live_compute)

        def process_audio_chunk(temp_path: str, offset_seconds: float, meeting_id: Optional[str], last_language: Optional[str]):
            """Process a single audio chunk through the pipeline."""
            segments, language, chunk_duration = pipeline.transcribe_chunk(temp_path, offset_seconds)
            
            for segment in segments:
                if meeting_id:
                    meeting_store.append_live_segment(meeting_id, segment, language or last_language)
                yield f"data: {json.dumps(segment)}\n\n"
            
            if language:
                yield f"data: {json.dumps({'type': 'meta', 'language': language})}\n\n"
            
            return offset_seconds + chunk_duration, language or last_language

        def event_stream():
            status = audio_service.current_status()
            if not status.get("recording"):
                yield "data: {\"type\":\"error\",\"message\":\"Not recording\"}\n\n"
                return

            samplerate = status.get("samplerate") or 48000
            channels = status.get("channels") or 1
            bytes_per_second = int(samplerate * channels * 2)
            buffer = bytearray()
            offset_seconds = 0.0
            last_language = None
            audio_service.enable_live_tap()
            logger.info(
                "Live transcription started: samplerate=%s channels=%s chunk_seconds=%.2f",
                samplerate,
                channels,
                live_chunk_seconds,
            )

            try:
                meta = {"type": "meta", "language": None}
                yield f"data: {json.dumps(meta)}\n\n"
                tick_interval = 30.0
                last_summary_tick = time.time()
                
                while True:
                    if not audio_service.is_recording() and not buffer:
                        break

                    chunk = audio_service.get_live_chunk(timeout=0.5)
                    if chunk:
                        buffer.extend(chunk)

                    if len(buffer) >= bytes_per_second * live_chunk_seconds:
                        temp_path = None
                        try:
                            temp_path, _ = _write_temp_wav(bytes(buffer), samplerate, channels)
                            
                            # Use pipeline for chunk processing
                            for event in process_audio_chunk(temp_path, offset_seconds, payload.meeting_id, last_language):
                                yield event
                            
                            # Update offset (approximation based on buffer size)
                            offset_seconds += len(buffer) / bytes_per_second
                            
                            # Periodic summary tick
                            if payload.meeting_id and time.time() - last_summary_tick >= tick_interval:
                                last_summary_tick = time.time()
                                try:
                                    meeting_store.step_summary_state(payload.meeting_id, summarization_service)
                                except Exception as exc:
                                    logger.warning("Summary tick failed: %s", exc)
                                    
                        except TranscriptionProviderError as exc:
                            logger.warning("live transcription failed: %s", exc)
                            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
                            break
                        except Exception as exc:
                            logger.exception("live transcription error: %s", exc)
                            yield "data: {\"type\":\"error\",\"message\":\"Internal Server Error\"}\n\n"
                            break
                        finally:
                            if temp_path and os.path.exists(temp_path):
                                os.unlink(temp_path)
                        buffer.clear()

                # Process remaining buffer
                if buffer:
                    temp_path = None
                    try:
                        temp_path, _ = _write_temp_wav(bytes(buffer), samplerate, channels)
                        
                        for event in process_audio_chunk(temp_path, offset_seconds, payload.meeting_id, last_language):
                            yield event
                            
                        if payload.meeting_id and time.time() - last_summary_tick >= tick_interval:
                            try:
                                meeting_store.step_summary_state(payload.meeting_id, summarization_service)
                            except Exception as exc:
                                logger.warning("Summary tick failed: %s", exc)
                    except Exception as exc:
                        logger.exception("final live transcription error: %s", exc)
                    finally:
                        if temp_path and os.path.exists(temp_path):
                            os.unlink(temp_path)

                yield "data: {\"type\":\"done\"}\n\n"
            finally:
                audio_service.disable_live_tap()
                logger.info("Live transcription ended")

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @router.post("/api/diarization/settings")
    def update_diarization_settings(payload: DiarizationSettingsRequest) -> dict:
        logger.debug("update_diarization_settings received: %s", payload.model_dump())
        diarization_service.update_config(
            DiarizationConfig(
                enabled=payload.enabled,
                provider=payload.provider,
                model=payload.model,
                device=payload.device,
                hf_token=payload.hf_token,
                performance_level=payload.performance_level,
            )
        )
        return {"status": "ok"}

    return router
