import logging
import threading
import os
import time
import uuid
from typing import Optional

import json

import tempfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from datetime import datetime

from app.services.audio_capture import AudioCaptureService
from app.services.audio_source import AudioDataSource, FileAudioSource, MicAudioSource, AudioMetadata
from app.services.meeting_store import MeetingStore
from app.services.diarization import DiarizationService
from app.services.diarization.providers.base import (
    DiarizationConfig,
    BatchDiarizationConfig,
    RealtimeDiarizationConfig,
    parse_diarization_config,
)
from app.services.transcription import (
    FasterWhisperProvider,
    TranscriptionProviderError,
    WhisperConfig,
)
from app.services.summarization import SummarizationService
from app.services.llm.base import LLMProviderError
from app.services.transcription_pipeline import TranscriptionPipeline, apply_diarization, convert_to_wav
from app.services.realtime_diarization import RealtimeDiarizationService
from app.services.live_transcription import LiveTranscriptionService
from app.services.debug_logging import dbg
from app.services.ndjson_debug import dbg as nd_dbg

# #region agent log
_DEBUG_LOG_PATH = os.path.join(os.getcwd(), "logs", "debug.log")


def _dbg_ndjson(*, location: str, message: str, data: dict, run_id: str, hypothesis_id: str) -> None:
    """Write one NDJSON debug line for this session. Best-effort only."""
    try:
        payload = {
            "id": f"log_{int(time.time() * 1000)}_{meeting_id_safe()}",
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data,
            "runId": run_id,
            "hypothesisId": hypothesis_id,
        }
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        return


def meeting_id_safe() -> str:
    try:
        return os.urandom(4).hex()
    except Exception:
        return "xxxx"


# #region agent log - concurrent stream counter
import itertools
_live_stream_counter = itertools.count(1)
_live_stream_active: dict[str, list[int]] = {}  # meeting_id -> list of stream_ids
_live_stream_lock = threading.Lock()


def _register_live_stream(meeting_id: str) -> int:
    """Register a new live stream for a meeting, return stream_id."""
    stream_id = next(_live_stream_counter)
    with _live_stream_lock:
        if meeting_id not in _live_stream_active:
            _live_stream_active[meeting_id] = []
        _live_stream_active[meeting_id].append(stream_id)
        concurrent = len(_live_stream_active[meeting_id])
    return stream_id, concurrent


def _unregister_live_stream(meeting_id: str, stream_id: int) -> int:
    """Unregister a live stream, return remaining count."""
    with _live_stream_lock:
        if meeting_id in _live_stream_active:
            if stream_id in _live_stream_active[meeting_id]:
                _live_stream_active[meeting_id].remove(stream_id)
            remaining = len(_live_stream_active[meeting_id])
            if remaining == 0:
                del _live_stream_active[meeting_id]
            return remaining
        return 0
# #endregion


# #endregion

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
    speed_percent: int = Field(
        300,
        description="Playback speed percentage. 0 = no delay (as fast as possible), "
                    "100 = real-time, 300 = 3x faster (default).",
        ge=0,
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
    ctx,
) -> APIRouter:
    router = APIRouter()
    logger = logging.getLogger("notetaker.api.transcription")
    
    # Unified job registry for both file and mic transcription
    # Each job contains: meeting_id, audio_source, audio_path
    transcription_jobs: dict[str, dict] = {}
    transcription_jobs_lock = threading.Lock()
    
    # Meetings currently running finalization (diarization + summarization).
    # Tracked separately so the frontend can distinguish "finalizing" from
    # "stale/stuck" without scanning every meeting file on boot.
    finalizing_meetings: set[str] = set()
    finalizing_lock = threading.Lock()
    
    trace_logger = logging.getLogger("notetaker.trace")

    def trace(stage: str, **fields) -> None:
        # Single-line trace logs to make grepping easy.
        payload = " ".join(f"{k}={fields[k]!r}" for k in sorted(fields.keys()))
        trace_logger.info("TRACE stage=%s ts=%s %s", stage, datetime.utcnow().isoformat(), payload)

    def dbg_rt(location: str, message: str, data: dict, run_id: str, hypothesis_id: str) -> None:
        # #region agent log
        try:
            dbg(
                logging.getLogger("notetaker.debug"),
                location=location,
                message=message,
                data=data,
                run_id=run_id,
                hypothesis_id=hypothesis_id,
            )
        except Exception:
            pass
        # #endregion

    transcription_config = config.get("transcription", {})
    provider_name = transcription_config.get("provider", "faster-whisper")
    if provider_name != "faster-whisper":
        raise RuntimeError(f"Unsupported transcription provider: {provider_name}")

    # Parse diarization config (supports both new split format and legacy single format)
    diarization_config = config.get("diarization", {})
    realtime_diar_cfg, batch_diar_cfg = parse_diarization_config(diarization_config)
    
    # Batch diarization service (for post-transcription diarization)
    diarization_service = DiarizationService(batch_diar_cfg)
    
    # Note: Real-time diarization instances are now created per-session in event_stream()
    # to prevent state corruption when multiple live transcription sessions run concurrently.
    # The config is kept at router level for creating new instances.

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
        # #region agent log
        logger.warning("LEGACY ENDPOINT CALLED: POST /api/transcribe (non-streaming). Caller should use /api/transcribe/simulate instead.")
        import json as _json_leg; import traceback as _tb_leg
        try:
            with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f:
                _f.write(_json_leg.dumps({"location":"transcription.py:transcribe","message":"LEGACY_ENDPOINT_HIT","data":{"endpoint":"/api/transcribe","audio_path":payload.audio_path,"stack":_tb_leg.format_stack()[-3:]},"timestamp":int(time.time()*1000),"hypothesisId":"LEGACY"})+"\n")
        except Exception: pass
        # #endregion
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
        # #region agent log
        logger.warning("LEGACY ENDPOINT CALLED: POST /api/transcribe/stream. Caller should use /api/transcribe/simulate instead.")
        import json as _json_leg2; import traceback as _tb_leg2
        try:
            with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f:
                _f.write(_json_leg2.dumps({"location":"transcription.py:transcribe_stream","message":"LEGACY_ENDPOINT_HIT","data":{"endpoint":"/api/transcribe/stream","audio_path":payload.audio_path,"simulate_live":payload.simulate_live,"stack":_tb_leg2.format_stack()[-3:]},"timestamp":int(time.time()*1000),"hypothesisId":"LEGACY"})+"\n")
        except Exception: pass
        # #endregion
        logger.debug("transcribe_stream received: %s", payload.model_dump())
        original_audio_path = payload.audio_path
        if not os.path.isabs(original_audio_path):
            raise HTTPException(status_code=400, detail="audio_path must be absolute")

        def event_stream():
            nonlocal original_audio_path
            try:
                model_size = payload.model_size or final_default_size
                pipeline = get_pipeline(model_size, final_device, final_compute)
                meeting_id = payload.meeting_id
                wav_path = original_audio_path  # Will be updated if we convert
                
                if payload.simulate_live and not meeting_id:
                    # Convert audio to WAV first (same format as mic recording)
                    # This ensures the pipeline is identical after ingestion
                    try:
                        wav_path, samplerate, channels = convert_to_wav(
                            original_audio_path,
                            ctx.recordings_dir,
                        )
                        logger.info(
                            "Audio converted for stream transcription: original=%s wav=%s",
                            original_audio_path,
                            wav_path,
                        )
                    except Exception as exc:
                        logger.exception("Failed to convert audio file: %s", exc)
                        yield f"data: {json.dumps({'type': 'error', 'message': f'Failed to convert audio: {exc}'})}\n\n"
                        return
                    
                    meeting = meeting_store.create_file_meeting(wav_path, samplerate, channels)
                    meeting_id = meeting.get("id")
                    logger.info(
                        "Streaming transcription started: meeting_id=%s wav=%s original=%s",
                        meeting_id,
                        wav_path,
                        original_audio_path,
                    )
                
                # Use pipeline for transcription (use converted WAV path)
                segments, language = pipeline.transcribe_and_format(wav_path)
                
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
                
                # Shared post-audio pipeline after streaming.
                # Same flow as mic/file: read from disk and finalize
                if meeting_id and payload.simulate_live:
                    # Read segments back from disk (they were stored via append_live_segment above)
                    meeting = meeting_store.get_meeting(meeting_id)
                    if meeting:
                        transcript = meeting.get("transcript") or {}
                        disk_segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
                        audio_path_from_meeting = meeting.get("audio_path") or wav_path
                        
                        if disk_segments:
                            pipeline.finalize_meeting_with_diarization(
                                meeting_id, disk_segments, audio_path_from_meeting
                            )
                        else:
                            meeting_store.update_status(meeting_id, "completed")
                    else:
                        meeting_store.update_status(meeting_id, "completed")
                else:
                    # No meeting context: just produce final speakers and persist transcript.
                    # Use wav_path for consistency (though this path doesn't create a meeting)
                    segments = pipeline.run_diarization(wav_path, segments)
                    meeting_store.add_transcript(wav_path, language, segments)
                
                yield "data: {\"type\":\"done\"}\n\n"
                
            except TranscriptionProviderError as exc:
                logger.warning("transcribe_stream failed: %s", exc)
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            except Exception as exc:
                logger.exception("transcribe_stream error: %s", exc)
                yield "data: {\"type\":\"error\",\"message\":\"Internal Server Error\"}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    def _run_transcription(
        meeting_id: str,
        audio_source: AudioDataSource,
        model_size: str,
    ) -> None:
        """Run transcription from any audio source in background thread.
        
        This is the unified transcription loop for both mic and file modes:
        1. Reads audio chunks from AudioDataSource (mic or file)
        2. Transcribes and saves segments via meeting_store (publishes events)
        3. Runs until audio source is complete (recording stopped or file exhausted)
        4. Finalizes meeting with diarization and summarization
        """
        segments: list[dict] = []
        language = None
        # #region agent log
        _dbg_ndjson(location="transcription.py:_run_transcription", message="THREAD_ENTER", data={"meeting_id": meeting_id, "model_size": model_size, "audio_source_type": type(audio_source).__name__}, run_id="start-debug", hypothesis_id="H4")
        # #endregion
        
        try:
            metadata = audio_source.get_metadata()
            samplerate = metadata.samplerate
            channels = metadata.channels
            bytes_per_second = int(samplerate * channels * 2)  # 16-bit audio
            
            # Model-specific chunk duration
            chunk_seconds = transcription_config.get("chunk_seconds", 30.0)
            
            pipeline = get_pipeline(model_size, live_device, live_compute)
            # #region agent log
            _dbg_ndjson(location="transcription.py:_run_transcription", message="pipeline_created", data={"meeting_id": meeting_id, "samplerate": samplerate, "channels": channels, "bytes_per_second": bytes_per_second, "chunk_seconds": chunk_seconds, "live_device": live_device, "live_compute": live_compute}, run_id="start-debug", hypothesis_id="H4")
            # #endregion
            
            # Create per-session real-time diarization
            session_rt_diarization = RealtimeDiarizationService(realtime_diar_cfg)
            rt_diarization_active = session_rt_diarization.start(samplerate, channels)
            
            logger.info(
                "Transcription thread started: meeting_id=%s samplerate=%s channels=%s rt_diar=%s",
                meeting_id, samplerate, channels, rt_diarization_active
            )
            
            # Emit meta event
            meeting_store.append_live_meta(meeting_id, None)
            
            buffer = bytearray()
            offset_seconds = 0.0
            
            # #region agent log
            import json as _json
            def _dbg_trans(msg, data):
                try:
                    with open(os.path.join(os.getcwd(), "logs", "debug.log"), "a") as f:
                        f.write(_json.dumps({"location": "transcription.py:_run_transcription", "message": msg, "data": data, "timestamp": __import__("time").time() * 1000, "runId": "gaps-debug", "hypothesisId": "H1-H4"}) + "\n")
                except: pass
            _dbg_trans("transcription_started", {"meeting_id": meeting_id, "samplerate": samplerate, "channels": channels, "bytes_per_second": bytes_per_second, "chunk_seconds": chunk_seconds, "buffer_threshold": bytes_per_second * chunk_seconds})
            chunk_count = 0
            process_count = 0
            last_segment_end = 0.0
            # #endregion
            
            while not audio_source.is_complete():
                chunk = audio_source.get_chunk(timeout_sec=0.5)
                if chunk:
                    buffer.extend(chunk)
                    # #region agent log
                    chunk_count += 1
                    if chunk_count <= 5:
                        _dbg_trans("chunk_received", {"chunk_count": chunk_count, "chunk_len": len(chunk), "buffer_len": len(buffer), "threshold": bytes_per_second * chunk_seconds})
                    # #endregion
                
                # Process when we have enough audio
                if len(buffer) >= bytes_per_second * chunk_seconds:
                    audio_bytes = bytes(buffer)
                    temp_path = None
                    try:
                        temp_path, temp_duration = _write_temp_wav(audio_bytes, samplerate, channels)
                        # #region agent log
                        _dbg_trans("processing_chunk", {"buffer_len": len(audio_bytes), "offset_seconds": offset_seconds, "temp_duration": temp_duration, "expected_duration": len(audio_bytes) / bytes_per_second})
                        # #endregion
                        
                        # Transcribe chunk
                        chunk_segments, chunk_language, chunk_duration = pipeline.transcribe_chunk(
                            temp_path, offset_seconds
                        )
                        # #region agent log
                        process_count += 1
                        # Find first and last segment timestamps
                        first_seg_start = chunk_segments[0].get("start") if chunk_segments else None
                        last_seg_end_in_chunk = max((s.get("end", 0) for s in chunk_segments), default=0) if chunk_segments else 0
                        gap_from_previous = first_seg_start - last_segment_end if (first_seg_start is not None and last_segment_end > 0) else 0
                        actual_chunk_duration = len(audio_bytes) / bytes_per_second
                        _dbg_trans("chunk_transcribed", {
                            "process_count": process_count,
                            "offset_seconds": offset_seconds,
                            "chunk_duration_from_whisper": chunk_duration,
                            "actual_chunk_duration": actual_chunk_duration,
                            "num_segments": len(chunk_segments),
                            "first_seg_start": first_seg_start,
                            "last_seg_end": last_seg_end_in_chunk,
                            "gap_from_previous": gap_from_previous,
                            "last_segment_end_prev": last_segment_end,
                            "segments_preview": [{"start": s.get("start"), "end": s.get("end"), "text": s.get("text", "")[:50]} for s in chunk_segments[:3]]
                        })
                        # Update for next iteration
                        if chunk_segments:
                            last_segment_end = last_seg_end_in_chunk
                        # #endregion
                        
                        if chunk_language and not language:
                            language = chunk_language
                            meeting_store.append_live_meta(meeting_id, language)
                        
                        # Feed audio to real-time diarization
                        new_rt_annotations = []
                        if rt_diarization_active and session_rt_diarization.is_active():
                            new_rt_annotations = session_rt_diarization.feed_audio(audio_bytes)
                        
                        # Process each segment
                        for segment in chunk_segments:
                            # Try to get speaker from real-time diarization
                            if rt_diarization_active and session_rt_diarization.is_active():
                                speaker = session_rt_diarization.get_speaker_at(segment["start"])
                                # #region agent log
                                _dbg_trans("get_speaker_at_result", {
                                    "segment_start": segment["start"],
                                    "segment_end": segment["end"],
                                    "speaker_returned": speaker,
                                    "rt_active": session_rt_diarization.is_active(),
                                })
                                # #endregion
                                if speaker:
                                    segment["speaker"] = speaker
                            
                            segments.append(segment)
                            # This saves segment AND publishes event to all subscribers
                            meeting_store.append_live_segment(meeting_id, segment, language or chunk_language)
                        
                        # Reconcile: if new diarization annotations cover previously-
                        # stored segments with a different speaker, update them.
                        if new_rt_annotations:
                            meeting_store.reconcile_speakers(meeting_id, new_rt_annotations)
                        
                        offset_seconds += len(buffer) / bytes_per_second
                        
                    except Exception as exc:
                        logger.warning("Transcription chunk error: meeting_id=%s error=%s", meeting_id, exc)
                        # Publish error event
                        meeting_store.publish_event("transcription_error", meeting_id, {
                            "message": str(exc),
                            "offset_seconds": offset_seconds,
                        })
                    finally:
                        if temp_path and os.path.exists(temp_path):
                            os.unlink(temp_path)
                    
                    buffer.clear()
            
            # Process remaining buffer
            if buffer:
                audio_bytes = bytes(buffer)
                temp_path = None
                try:
                    temp_path, _ = _write_temp_wav(audio_bytes, samplerate, channels)
                    chunk_segments, chunk_language, _ = pipeline.transcribe_chunk(temp_path, offset_seconds)
                    
                    new_rt_annotations_final = []
                    if rt_diarization_active and session_rt_diarization.is_active():
                        new_rt_annotations_final = session_rt_diarization.feed_audio(audio_bytes)
                    
                    for segment in chunk_segments:
                        if rt_diarization_active and session_rt_diarization.is_active():
                            speaker = session_rt_diarization.get_speaker_at(segment["start"])
                            if speaker:
                                segment["speaker"] = speaker
                        segments.append(segment)
                        meeting_store.append_live_segment(meeting_id, segment, language or chunk_language)
                    
                    # Reconcile retroactive speaker assignments
                    if new_rt_annotations_final:
                        meeting_store.reconcile_speakers(meeting_id, new_rt_annotations_final)
                except Exception as exc:
                    logger.warning("Transcription final chunk error: meeting_id=%s error=%s", meeting_id, exc)
                finally:
                    if temp_path and os.path.exists(temp_path):
                        os.unlink(temp_path)
            
            # Stop real-time diarization
            if session_rt_diarization.is_active():
                session_rt_diarization.stop()
            
            # Unregister from job registry BEFORE finalization.
            # This frees the slot so starting a new transcription (even for
            # the same file) is not blocked by the dedup guard while
            # finalization (diarization + summarization) runs in this thread.
            with transcription_jobs_lock:
                transcription_jobs.pop(meeting_id, None)
            logger.info("Transcription active phase done, starting finalization: meeting_id=%s", meeting_id)
            
            # Register as finalizing so the frontend can query real state
            with finalizing_lock:
                finalizing_meetings.add(meeting_id)
            
            try:
                # Finalize meeting (same path as file mode)
                meeting = meeting_store.get_meeting(meeting_id)
                if meeting:
                    transcript = meeting.get("transcript") or {}
                    disk_segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
                    audio_path = meeting.get("audio_path")
                    
                    if disk_segments:
                        # Use final device/compute for quality finalization
                        final_pipeline = get_pipeline(model_size, final_device, final_compute)
                        final_pipeline.finalize_meeting_with_diarization(
                            meeting_id, disk_segments, audio_path
                        )
                        logger.info("Meeting finalized: meeting_id=%s segments=%d", meeting_id, len(disk_segments))
                    else:
                        meeting_store.update_status(meeting_id, "completed")
                        logger.info("Meeting completed (no segments): meeting_id=%s", meeting_id)
                else:
                    meeting_store.update_status(meeting_id, "completed")
            finally:
                with finalizing_lock:
                    finalizing_meetings.discard(meeting_id)
                
        except Exception as exc:
            logger.exception("Transcription error: meeting_id=%s error=%s", meeting_id, exc)
            # #region agent log
            import traceback as _tb_run
            _dbg_ndjson(location="transcription.py:_run_transcription", message="THREAD_CRASH", data={"meeting_id": meeting_id, "exc_type": type(exc).__name__, "exc_str": str(exc)[:1000], "traceback": _tb_run.format_exc()[-2000:]}, run_id="start-debug", hypothesis_id="H4")
            # #endregion
            # Publish error event for frontend notification
            try:
                meeting_store.publish_event("transcription_error", meeting_id, {
                    "message": f"Transcription error: {exc}",
                    "error_type": "internal_error",
                })
            except Exception:
                pass
            try:
                meeting_store.update_status(meeting_id, "completed")
            except Exception:
                pass
        finally:
            # Safety net: ensure job is removed even if thread crashes before
            # the early cleanup above runs.  pop() is idempotent.
            with transcription_jobs_lock:
                transcription_jobs.pop(meeting_id, None)
            logger.info("Transcription thread finished: meeting_id=%s segments=%d", meeting_id, len(segments))

    @router.post("/api/transcribe/simulate")
    def simulate_transcribe(payload: SimulateTranscribeRequest) -> dict:
        # #region agent log
        _dbg_ndjson(location="transcription.py:simulate_transcribe", message="ENTER", data={"audio_path": payload.audio_path, "meeting_id": payload.meeting_id, "speed_percent": payload.speed_percent}, run_id="start-debug", hypothesis_id="H3")
        # #endregion
        original_audio_path = payload.audio_path
        if not os.path.isabs(original_audio_path):
            raise HTTPException(status_code=400, detail="audio_path must be absolute")
        existing = next(
            (job for job in transcription_jobs.values() if job.get("original_audio_path") == original_audio_path),
            None,
        )
        if existing:
            return {"status": "running", "meeting_id": existing.get("meeting_id")}
        
        meeting = None
        wav_path = None
        samplerate = None
        channels = None
        audio_source: Optional[FileAudioSource] = None
        
        if payload.meeting_id:
            # Resuming an existing meeting - use the provided meeting_id
            meeting = meeting_store.get_meeting(payload.meeting_id)
            if not meeting:
                raise HTTPException(status_code=404, detail="Meeting not found")
            # Meeting already has converted audio_path
            wav_path = meeting.get("audio_path")
            samplerate = meeting.get("samplerate")
            channels = meeting.get("channels")
            # Create FileAudioSource for resumed meeting
            audio_source = FileAudioSource(
                wav_path,
                chunk_duration_sec=5.0,
                speed_percent=payload.speed_percent,
            )
        else:
            # Starting fresh - convert audio to WAV first (same format as mic recording)
            # This ensures the pipeline is identical after ingestion
            try:
                wav_path, samplerate, channels = convert_to_wav(
                    original_audio_path,
                    ctx.recordings_dir,
                )
                logger.info(
                    "Audio converted for file transcription: original=%s wav=%s sr=%d ch=%d",
                    original_audio_path,
                    wav_path,
                    samplerate,
                    channels,
                )
            except Exception as exc:
                logger.exception("Failed to convert audio file: %s", exc)
                raise HTTPException(status_code=400, detail=f"Failed to convert audio: {exc}")
            
            # Create FileAudioSource with user-specified speed
            audio_source = FileAudioSource(
                wav_path,
                chunk_duration_sec=5.0,
                speed_percent=payload.speed_percent,
            )
            
            # Create meeting with converted WAV path and session_id from audio source
            meeting = meeting_store.create_file_meeting(
                wav_path, samplerate, channels,
                session_id=audio_source.get_metadata().session_id,
            )
        
        meeting_id = meeting.get("id")
        if not meeting_id:
            raise HTTPException(status_code=500, detail="Failed to create meeting")
        meeting_store.update_status(meeting_id, "in_progress")
        model_size = payload.model_size or final_default_size
        
        # Use unified transcription function with AudioDataSource
        thread = threading.Thread(
            target=_run_transcription,
            args=(meeting_id, audio_source, model_size),
            daemon=True,
        )
        transcription_jobs[meeting_id] = {
            "meeting_id": meeting_id,
            "audio_source": audio_source,
            "audio_path": wav_path,
            "original_audio_path": original_audio_path,  # For deduplication
        }
        logger.info(
            "File transcription started: meeting_id=%s wav=%s original=%s speed=%d%%",
            meeting_id,
            wav_path,
            original_audio_path,
            payload.speed_percent,
        )
        thread.start()
        return {"status": "started", "meeting_id": meeting_id, "speed_percent": payload.speed_percent}

    @router.post("/api/transcribe/simulate/stop")
    def simulate_stop(audio_path: str) -> dict:
        """Stop file transcription by audio path.
        
        This endpoint finds the meeting_id for the given audio_path and delegates
        to the unified stop endpoint. Kept for backwards compatibility.
        """
        # Find job by audio_path
        job = next(
            (job for job in transcription_jobs.values() 
             if job.get("audio_path") == audio_path or job.get("original_audio_path") == audio_path),
            None,
        )
        if not job:
            return {"status": "idle"}
        
        # Delegate to unified stop
        meeting_id = job.get("meeting_id")
        if meeting_id:
            return stop_transcription_by_meeting(meeting_id)
        return {"status": "idle"}

    class StartLiveTranscriptionRequest(BaseModel):
        """Request to start live transcription for an active recording."""
        meeting_id: str
        model_size: Optional[str] = None

    @router.post("/api/transcribe/start")
    def start_live_transcription(payload: StartLiveTranscriptionRequest) -> dict:
        """Start live transcription for an active recording.
        
        This starts a background thread that:
        1. Reads audio from the microphone via AudioCaptureService
        2. Transcribes chunks and saves segments (publishes events)
        3. All subscribers to /api/meetings/events receive transcript_segment events
        
        Unlike the legacy /api/transcribe/live SSE endpoint, this:
        - Runs transcription in background (not tied to SSE connection)
        - Supports multiple frontend windows viewing the same meeting
        - Uses the same event publishing as file transcription
        """
        meeting_id = payload.meeting_id
        # #region agent log
        _dbg_ndjson(location="transcription.py:start_live_transcription", message="ENTER", data={"meeting_id": meeting_id, "model_size": payload.model_size}, run_id="start-debug", hypothesis_id="H2")
        # #endregion
        
        # Check if already running
        with transcription_jobs_lock:
            if meeting_id in transcription_jobs:
                # #region agent log
                _dbg_ndjson(location="transcription.py:start_live_transcription", message="ALREADY_RUNNING", data={"meeting_id": meeting_id}, run_id="start-debug", hypothesis_id="H2")
                # #endregion
                return {"status": "already_running", "meeting_id": meeting_id}
        
        # Verify recording is active for this meeting
        # If no active recording, return gracefully (file mode uses /api/transcribe/simulate instead)
        status = audio_service.current_status()
        # #region agent log
        _dbg_ndjson(location="transcription.py:start_live_transcription", message="recording_status_check", data={"meeting_id": meeting_id, "recording": status.get("recording"), "recording_id": status.get("recording_id"), "id_match": status.get("recording_id") == meeting_id, "capture_stopped": status.get("capture_stopped")}, run_id="start-debug", hypothesis_id="H2")
        # #endregion
        if not status.get("recording") or status.get("recording_id") != meeting_id:
            return {"status": "not_applicable", "meeting_id": meeting_id, "reason": "no_active_recording"}
        
        # Create MicAudioSource
        session_id = status.get("recording_id") or meeting_id
        mic_audio_source = MicAudioSource(audio_service, session_id)
        audio_service.enable_live_tap()
        
        # Determine model size
        model_size = payload.model_size or transcription_config.get("model_size", "medium")
        
        # Register job
        with transcription_jobs_lock:
            transcription_jobs[meeting_id] = {
                "meeting_id": meeting_id,
                "audio_source": mic_audio_source,
                "audio_path": status.get("file_path"),
            }
        
        # Start transcription thread
        thread = threading.Thread(
            target=_run_transcription,
            args=(meeting_id, mic_audio_source, model_size),
            daemon=True,
        )
        thread.start()
        
        logger.info("Live transcription started: meeting_id=%s model=%s", meeting_id, model_size)
        return {
            "status": "started",
            "meeting_id": meeting_id,
            "model_size": model_size,
        }

    @router.get("/api/transcribe/active")
    def get_active_transcription() -> dict:
        """Get currently active transcription job, if any."""
        with transcription_jobs_lock:
            if transcription_jobs:
                job = next(iter(transcription_jobs.values()))
                return {
                    "active": True,
                    "meeting_id": job.get("meeting_id"),
                    "audio_path": job.get("audio_path"),
                }
        return {"active": False, "meeting_id": None, "audio_path": None}

    @router.get("/api/transcribe/status/{meeting_id}")
    def get_transcription_status(meeting_id: str) -> dict:
        """Get the real-time transcription/finalization state for a meeting.

        Returns one of:
          transcribing  – actively processing audio
          finalizing    – diarization / summarization running
          idle          – nothing running for this meeting
        """
        with transcription_jobs_lock:
            if meeting_id in transcription_jobs:
                return {"meeting_id": meeting_id, "state": "transcribing"}
        with finalizing_lock:
            if meeting_id in finalizing_meetings:
                return {"meeting_id": meeting_id, "state": "finalizing"}
        return {"meeting_id": meeting_id, "state": "idle"}

    @router.post("/api/transcribe/stop/{meeting_id}")
    def stop_transcription_by_meeting(meeting_id: str) -> dict:
        """Stop transcription for a specific meeting with responsive behavior.
        
        Uses unified AudioDataSource.stop() interface for both file and mic modes:
        - File mode: Stops reading file, interrupts any playback delays
        - Mic mode: Signals capture stopped, stops actual recording
        
        Both modes continue processing already-buffered audio in background.
        Returns immediately with status='stopping'.
        """
        # #region agent log
        _dbg_ndjson(
            location="app/routers/transcription.py:stop_transcription_by_meeting",
            message="stop called",
            data={"meeting_id": meeting_id, "transcription_jobs": len(transcription_jobs)},
            run_id="pre-fix",
            hypothesis_id="STOP500",
        )
        # #endregion
        
        # Unified job lookup from registry
        with transcription_jobs_lock:
            job = transcription_jobs.get(meeting_id)
        
        if job:
            audio_source = job.get("audio_source")
            
            # Unified stop: audio_source.stop() handles everything for both modes
            # - For MicAudioSource: signals capture stopped AND stops recording device
            # - For FileAudioSource: sets stopped flag and interrupts any delays
            if audio_source:
                audio_source.stop()
                logger.info("AudioDataSource.stop() called: meeting_id=%s", meeting_id)
            
            # #region agent log
            _dbg_ndjson(
                location="app/routers/transcription.py:stop_transcription_by_meeting",
                message="unified stop completed",
                data={
                    "meeting_id": meeting_id,
                    "had_audio_source": audio_source is not None,
                },
                run_id="pre-fix",
                hypothesis_id="STOP500",
            )
            # #endregion
            
            logger.info("Stopped transcription: meeting_id=%s", meeting_id)
            return {
                "status": "stopping", 
                "meeting_id": meeting_id, 
                "message": "Stop signal sent. Processing of buffered audio continues in background."
            }
        
        return {"status": "not_found", "meeting_id": meeting_id}

    @router.post("/api/transcribe/resume/{meeting_id}")
    def resume_transcription(meeting_id: str) -> dict:
        """Resume transcription for a meeting that was stopped."""
        # Check if any transcription is already running
        if transcription_jobs:
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
        # Clear finalization flags since transcript will change
        meeting_store.clear_finalization_flags(meeting_id)
        
        # Create FileAudioSource for resumed meeting
        audio_source = FileAudioSource(
            audio_path,
            chunk_duration_sec=5.0,
            speed_percent=0,  # No delay for resume - process as fast as possible
        )
        
        # Start transcription using unified function
        model_size = transcription_config.get("model_size", "medium")
        thread = threading.Thread(
            target=_run_transcription,
            args=(meeting_id, audio_source, model_size),
            daemon=True,
        )
        transcription_jobs[meeting_id] = {
            "meeting_id": meeting_id,
            "audio_source": audio_source,
            "audio_path": audio_path,
        }
        logger.info("Resumed transcription: meeting_id=%s audio=%s", meeting_id, audio_path)
        thread.start()
        return {"status": "resumed", "meeting_id": meeting_id}

    # Track active live transcription services by meeting_id
    live_transcription_services: dict[str, LiveTranscriptionService] = {}

    @router.post("/api/transcribe/live")
    def transcribe_live(payload: LiveTranscribeRequest) -> StreamingResponse:
        """DEPRECATED: Use POST /api/transcribe/start instead.
        
        This legacy SSE endpoint is maintained for backwards compatibility but
        should not be used for new code. The new /api/transcribe/start endpoint:
        - Runs transcription in a background thread (not tied to SSE connection)
        - Supports multiple browser windows viewing the same meeting
        - Uses unified meeting events SSE for all transcript updates
        
        This endpoint will be removed in a future version.
        """
        logger.warning(
            "DEPRECATED: /api/transcribe/live called for meeting_id=%s. Use /api/transcribe/start instead.",
            payload.meeting_id
        )
        # #region agent log
        import json as _json_leg3; import traceback as _tb_leg3
        try:
            with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f:
                _f.write(_json_leg3.dumps({"location":"transcription.py:transcribe_live","message":"LEGACY_ENDPOINT_HIT","data":{"endpoint":"/api/transcribe/live","meeting_id":payload.meeting_id,"stack":_tb_leg3.format_stack()[-3:]},"timestamp":int(time.time()*1000),"hypothesisId":"LEGACY"})+"\n")
        except Exception: pass
        # #endregion
        logger.debug("transcribe_live received: %s", payload.model_dump())
        # #region agent log
        stream_id, concurrent_streams = _register_live_stream(payload.meeting_id or "unknown")
        _dbg_ndjson(
            location="app/routers/transcription.py:transcribe_live",
            message="transcribe_live received",
            data={
                "meeting_id": payload.meeting_id,
                "model_size": payload.model_size,
                "stream_id": stream_id,
                "concurrent_streams": concurrent_streams,
            },
            run_id="pre-fix",
            hypothesis_id="H1-DUAL-STREAM",
        )
        if concurrent_streams > 1:
            _dbg_ndjson(
                location="app/routers/transcription.py:transcribe_live",
                message="WARNING: multiple concurrent streams detected!",
                data={
                    "meeting_id": payload.meeting_id,
                    "stream_id": stream_id,
                    "concurrent_streams": concurrent_streams,
                    "all_active": list(_live_stream_active.get(payload.meeting_id or "unknown", [])),
                },
                run_id="pre-fix",
                hypothesis_id="H1-DUAL-STREAM",
            )
        # #endregion
        model_size = payload.model_size or live_default_size
        pipeline = get_pipeline(model_size, live_device, live_compute)
        
        # Use model-specific chunk size instead of fixed 5 seconds
        chunk_seconds = pipeline.get_chunk_size()
        logger.info("Using model-specific chunk size: %.1f seconds", chunk_seconds)

        def process_audio_chunk(
            temp_path: str,
            offset_seconds: float,
            meeting_id: Optional[str],
            last_language: Optional[str],
            audio_bytes: bytes,
            samplerate: int,
            channels: int,
            rt_diarization: Optional[RealtimeDiarizationService] = None,
        ):
            """Process a single audio chunk through the pipeline with real-time diarization.
            
            Args:
                rt_diarization: Per-session real-time diarization instance (or None if disabled)
            """
            t0 = time.perf_counter()
            trace(
                "whisper_start",
                meeting_id=meeting_id,
                offset_seconds=offset_seconds,
                audio_bytes=len(audio_bytes),
                samplerate=samplerate,
                channels=channels,
            )
            segments, language, chunk_duration = pipeline.transcribe_chunk(temp_path, offset_seconds)
            trace(
                "whisper_end",
                meeting_id=meeting_id,
                offset_seconds=offset_seconds,
                elapsed_s=round(time.perf_counter() - t0, 3),
                segments=len(segments),
                language=language,
                chunk_duration_s=round(chunk_duration, 3),
            )
            
            # Feed audio to real-time diarization if active
            if rt_diarization and rt_diarization.is_active():
                rt_diarization.feed_audio(audio_bytes)
            
                for seg_idx, segment in enumerate(segments):
                    # Try to get speaker from real-time diarization
                    if rt_diarization.is_active():
                        speaker = rt_diarization.get_speaker_at(segment["start"])
                        if speaker:
                            segment["speaker"] = speaker
                        if seg_idx == 0:
                            dbg_rt(
                                "app/routers/transcription.py:process_audio_chunk",
                                "rt_assign_first_segment",
                                {
                                    "rt_active": True,
                                    "segment_start": segment.get("start"),
                                    "speaker_found": bool(speaker),
                                    "speaker": speaker or None,
                                    "segments_in_chunk": len(segments),
                                },
                                run_id="pre-fix",
                                hypothesis_id="H5",
                            )
                            nd_dbg(
                                "app/routers/transcription.py:process_audio_chunk",
                                "rt_assign_first_segment",
                                {
                                    "rt_active": True,
                                    "segment_start": segment.get("start"),
                                    "speaker_found": bool(speaker),
                                    "speaker": speaker or None,
                                    "segments_in_chunk": len(segments),
                                },
                                run_id="pre-fix",
                                hypothesis_id="H4",
                            )
                    
                    if meeting_id:
                        trace(
                            "meeting_append_segment",
                            meeting_id=meeting_id,
                            segment_start=segment.get("start"),
                            segment_end=segment.get("end"),
                            text_len=len(segment.get("text", "") or ""),
                        )
                        meeting_store.append_live_segment(meeting_id, segment, language or last_language)
                    
                    # #region agent log
                    nd_dbg(
                        "app/routers/transcription.py:process_audio_chunk",
                        "sse_segment_yield",
                        {
                            "meeting_id": meeting_id,
                            "seg_idx": seg_idx,
                            "segment_start": segment.get("start"),
                            "segment_end": segment.get("end"),
                            "text_len": len(segment.get("text", "") or ""),
                            "text_preview": (segment.get("text", "") or "")[:50],
                        },
                        run_id="bugs-debug",
                        hypothesis_id="H3a",
                    )
                    # #endregion
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
            
            # Create MicAudioSource for unified stop mechanism
            session_id = status.get("recording_id") or payload.meeting_id or str(uuid.uuid4())
            mic_audio_source = MicAudioSource(audio_service, session_id)
            
            # Register job in unified registry for stop mechanism
            if payload.meeting_id:
                with transcription_jobs_lock:
                    transcription_jobs[payload.meeting_id] = {
                        "meeting_id": payload.meeting_id,
                        "audio_source": mic_audio_source,
                        "audio_path": status.get("file_path"),
                    }
            
            # Create per-session real-time diarization instance to prevent state corruption
            # when multiple live transcription sessions run concurrently
            session_rt_diarization = RealtimeDiarizationService(realtime_diar_cfg)
            
            # Start real-time diarization if enabled
            rt_diarization_active = session_rt_diarization.start(samplerate, channels)
            dbg_rt(
                "app/routers/transcription.py:event_stream",
                "rt_start_result",
                {
                    "rt_started": bool(rt_diarization_active),
                    "samplerate": samplerate,
                    "channels": channels,
                    "chunk_seconds": chunk_seconds,
                    "meeting_id_present": bool(payload.meeting_id),
                    "per_session_instance": True,
                },
                run_id="pre-fix",
                hypothesis_id="H1",
            )
            nd_dbg(
                "app/routers/transcription.py:event_stream",
                "rt_start_result",
                {
                    "rt_started": bool(rt_diarization_active),
                    "samplerate": samplerate,
                    "channels": channels,
                    "chunk_seconds": chunk_seconds,
                    "meeting_id_present": bool(payload.meeting_id),
                    "per_session_instance": True,
                },
                run_id="pre-fix",
                hypothesis_id="H1",
            )
            
            logger.info(
                "Live transcription started: samplerate=%s channels=%s chunk_seconds=%.2f realtime_diarization=%s",
                samplerate,
                channels,
                chunk_seconds,
                rt_diarization_active,
            )

            # #region agent log
            loop_count = 0
            chunks_received = 0
            # #endregion
            try:
                meta = {"type": "meta", "language": None, "realtime_diarization": rt_diarization_active, "chunk_seconds": chunk_seconds}
                yield f"data: {json.dumps(meta)}\n\n"
                trace(
                    "live_transcription_started",
                    meeting_id=payload.meeting_id,
                    samplerate=samplerate,
                    channels=channels,
                    bytes_per_second=bytes_per_second,
                    chunk_seconds=chunk_seconds,
                    rt_diarization=rt_diarization_active,
                )
                # Manual summarization mode: no periodic summary ticks.
                
                while True:
                    loop_count += 1
                    # Check if capture was stopped (responsive stop)
                    if audio_service.is_capture_stopped():
                        logger.info("Capture stopped signal received, draining remaining audio")
                        # #region agent log
                        _dbg_ndjson(
                            location="app/routers/transcription.py:event_stream",
                            message="capture_stopped_signal",
                            data={
                                "meeting_id": payload.meeting_id,
                                "stream_id": stream_id,
                                "loop_count": loop_count,
                                "chunks_received": chunks_received,
                                "buffer_len": len(buffer),
                            },
                            run_id="pre-fix",
                            hypothesis_id="H1-DUAL-STREAM",
                        )
                        # #endregion
                        # Drain any remaining audio from the queue
                        remaining = audio_service.drain_live_queue()
                        if remaining:
                            buffer.extend(remaining)
                        break
                    
                    # Normal check - recording ended
                    if not audio_service.is_recording() and not buffer:
                        # #region agent log
                        _dbg_ndjson(
                            location="app/routers/transcription.py:event_stream",
                            message="not_recording_exit",
                            data={
                                "meeting_id": payload.meeting_id,
                                "stream_id": stream_id,
                                "loop_count": loop_count,
                                "chunks_received": chunks_received,
                            },
                            run_id="pre-fix",
                            hypothesis_id="H1-DUAL-STREAM",
                        )
                        # #endregion
                        break

                    chunk = audio_service.get_live_chunk(timeout=0.5)
                    if chunk:
                        chunks_received += 1
                        buffer.extend(chunk)
                        # #region agent log - log every 20 chunks to avoid spam
                        if chunks_received % 20 == 1:
                            _dbg_ndjson(
                                location="app/routers/transcription.py:event_stream",
                                message="chunk_received",
                                data={
                                    "meeting_id": payload.meeting_id,
                                    "stream_id": stream_id,
                                    "chunks_received": chunks_received,
                                    "chunk_len": len(chunk),
                                    "buffer_len": len(buffer),
                                },
                                run_id="pre-fix",
                                hypothesis_id="H1-DUAL-STREAM",
                            )
                        # #endregion

                    if len(buffer) >= bytes_per_second * chunk_seconds:
                        temp_path = None
                        audio_bytes = bytes(buffer)
                        try:
                            trace(
                                "live_audio_chunk_ready",
                                meeting_id=payload.meeting_id,
                                buffer_bytes=len(buffer),
                                buffer_seconds=round(len(buffer) / bytes_per_second, 3),
                                offset_seconds=round(offset_seconds, 3),
                            )
                            temp_path, _ = _write_temp_wav(audio_bytes, samplerate, channels)
                            
                            # Use pipeline for chunk processing with per-session real-time diarization
                            for event in process_audio_chunk(
                                temp_path, offset_seconds, payload.meeting_id, 
                                last_language, audio_bytes, samplerate, channels,
                                rt_diarization=session_rt_diarization,
                            ):
                                yield event
                            
                            # Update offset (approximation based on buffer size)
                            offset_seconds += len(buffer) / bytes_per_second
                            
                            # Manual summarization mode: no periodic summary tick.
                        except TranscriptionProviderError as exc:
                            logger.warning("live transcription failed: %s", exc)
                            # #region agent log
                            nd_dbg(
                                "app/routers/transcription.py:event_stream",
                                "live_transcription_provider_error",
                                {"exc_type": type(exc).__name__, "exc_str": str(exc)[:800], "offset_seconds": offset_seconds},
                                run_id="pre-fix",
                                hypothesis_id="E1",
                            )
                            # #endregion
                            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
                            break
                        except Exception as exc:
                            logger.exception("live transcription error: %s", exc)
                            # #region agent log
                            import traceback
                            nd_dbg(
                                "app/routers/transcription.py:event_stream",
                                "live_transcription_internal_error",
                                {
                                    "exc_type": type(exc).__name__,
                                    "exc_str": str(exc)[:800],
                                    "traceback": traceback.format_exc()[-2000:],
                                    "offset_seconds": offset_seconds,
                                },
                                run_id="pre-fix",
                                hypothesis_id="E1",
                            )
                            # #endregion
                            yield "data: {\"type\":\"error\",\"message\":\"Internal Server Error\"}\n\n"
                            break
                        finally:
                            if temp_path and os.path.exists(temp_path):
                                os.unlink(temp_path)
                        buffer.clear()

                # Process remaining buffer (including any drained audio after stop)
                if buffer:
                    logger.info("Processing final buffer: %.2f seconds", len(buffer) / bytes_per_second)
                    temp_path = None
                    audio_bytes = bytes(buffer)
                    try:
                        trace(
                            "live_final_buffer_ready",
                            meeting_id=payload.meeting_id,
                            buffer_bytes=len(buffer),
                            buffer_seconds=round(len(buffer) / bytes_per_second, 3),
                            offset_seconds=round(offset_seconds, 3),
                        )
                        temp_path, _ = _write_temp_wav(audio_bytes, samplerate, channels)
                        
                        for event in process_audio_chunk(
                            temp_path, offset_seconds, payload.meeting_id,
                            last_language, audio_bytes, samplerate, channels,
                            rt_diarization=session_rt_diarization,
                        ):
                            yield event
                            
                        # Manual summarization mode: no final-buffer summary tick.
                    except Exception as exc:
                        logger.exception("final live transcription error: %s", exc)
                        # #region agent log
                        import traceback
                        nd_dbg(
                            "app/routers/transcription.py:event_stream",
                            "live_final_buffer_error",
                            {
                                "exc_type": type(exc).__name__,
                                "exc_str": str(exc)[:800],
                                "traceback": traceback.format_exc()[-2000:],
                                "offset_seconds": offset_seconds,
                            },
                            run_id="pre-fix",
                            hypothesis_id="E1",
                        )
                        # #endregion
                    finally:
                        if temp_path and os.path.exists(temp_path):
                            os.unlink(temp_path)

                yield "data: {\"type\":\"done\"}\n\n"
            finally:
                # #region agent log
                _log_path = os.path.join(os.getcwd(), "logs", "debug.log")
                import json as _json_dbg
                import time as _time_dbg
                def _dbg_finally(msg, data=None):
                    try:
                        with open(_log_path, "a") as _f:
                            _f.write(_json_dbg.dumps({"location":"transcription.py:live_finally","message":msg,"data":data or {},"timestamp":int(_time_dbg.time()*1000),"hypothesisId":"H1,H4"})+"\n")
                    except Exception:
                        pass
                remaining_streams = _unregister_live_stream(payload.meeting_id or "unknown", stream_id)
                _dbg_finally("finally_block_entered", {
                    "meeting_id": payload.meeting_id if payload else None,
                    "stream_id": stream_id,
                    "remaining_streams": remaining_streams,
                    "chunks_received": chunks_received,
                    "loop_count": loop_count,
                })
                # #endregion
                
                # Stop per-session real-time diarization
                if session_rt_diarization.is_active():
                    final_annotations = session_rt_diarization.stop()
                    logger.info("Real-time diarization final: %s annotations", len(final_annotations))
                
                audio_service.disable_live_tap()
                
                # Unregister job from unified registry
                if payload.meeting_id:
                    with transcription_jobs_lock:
                        transcription_jobs.pop(payload.meeting_id, None)
                
                trace("live_transcription_ended", meeting_id=payload.meeting_id)
                logger.info("Live transcription ended (deprecated SSE endpoint)")
                
                # NOTE: Finalization is NOT done here in the deprecated endpoint.
                # The new /api/transcribe/start flow handles finalization in _run_transcription().
                # If this deprecated endpoint is used, the meeting will need manual finalization
                # or the user should use the new endpoint instead.
                _dbg_finally("deprecated_endpoint_no_finalize", {
                    "meeting_id": payload.meeting_id,
                    "note": "Use /api/transcribe/start instead for automatic finalization"
                })

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @router.get("/api/transcribe/live/status/{meeting_id}")
    def get_live_transcription_status(meeting_id: str) -> dict:
        """Get status of live transcription for a meeting.
        
        Returns:
            Status dict with capture_stopped and transcription_pending flags
        """
        service = live_transcription_services.get(meeting_id)
        if not service:
            return {
                "status": "not_found",
                "capture_stopped": True,
                "transcription_complete": True,
                "chunks_pending": 0,
            }
        return service.get_status()

    @router.post("/api/diarization/settings")
    def update_diarization_settings(payload: DiarizationSettingsRequest) -> dict:
        nonlocal realtime_diar_cfg
        logger.debug("update_diarization_settings received: %s", payload.model_dump())
        new_config = DiarizationConfig(
            enabled=payload.enabled,
            provider=payload.provider,
            model=payload.model,
            device=payload.device,
            hf_token=payload.hf_token,
            performance_level=payload.performance_level,
        )
        # Update batch diarization service
        diarization_service.update_config(new_config)
        # Update real-time diarization config for new sessions
        # (existing sessions keep their config until they complete)
        realtime_diar_cfg = RealtimeDiarizationConfig(
            enabled=payload.enabled,
            provider=payload.provider,
            model=payload.model,
            device=payload.device,
            hf_token=payload.hf_token,
            performance_level=payload.performance_level,
        )
        
        return {
            "status": "ok",
            "realtime_enabled": payload.provider.lower() == "diart" and payload.enabled,
        }

    return router
