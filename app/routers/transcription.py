import logging
import threading
import os
import time
import uuid
from typing import Optional

import json

import tempfile

from fastapi import APIRouter, HTTPException

from pydantic import BaseModel, Field
from datetime import datetime

from app.services.audio_capture import AudioCaptureService
from app.services.audio_source import AudioDataSource, LiveAudioSource, AudioMetadata
from app.services.meeting_store import MeetingStore
from app.services.active_meeting_tracker import get_tracker, MeetingState
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
from app.services.transcription_pipeline import TranscriptionPipeline, apply_diarization
from app.services.realtime_diarization import RealtimeDiarizationService
from app.services.debug_logging import dbg
from app.services.debug import debug_log
from app.services.ndjson_debug import dbg as nd_dbg

# #region agent log
_dbg_logger = logging.getLogger("notetaker.debug")
# #endregion

class SimulateTranscribeRequest(BaseModel):
    source: str = Field("file", description="Audio source: 'mic' or 'file'")
    audio_path: Optional[str] = Field(None, description="Absolute path to audio file (file mode)")
    device_index: Optional[int] = Field(None, description="Audio device index (mic mode)")
    samplerate: int = Field(48000, description="Sample rate")
    channels: int = Field(2, description="Channel count")
    model_size: Optional[str] = Field(
        None, description="Override model size for this request"
    )
    meeting_id: Optional[str] = Field(
        None, description="Meeting id (optional)"
    )
    speed_percent: int = Field(
        300,
        description="Playback speed percentage (file mode). 0 = no delay, "
                    "100 = real-time, 300 = 3x faster (default).",
        ge=0,
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
    
    # Get the global active meeting tracker (replaces local transcription_jobs and finalizing_meetings)
    active_tracker = get_tracker()
    
    # Legacy job registry kept for backwards compatibility with audio_source references
    # The tracker handles state, but we still need to store audio_source objects
    transcription_jobs: dict[str, dict] = {}
    transcription_jobs_lock = threading.Lock()
    
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
    final_default_size = transcription_config.get("final_model_size", "medium")

    provider_cache: dict[tuple[str, str, str], FasterWhisperProvider] = {}

    def get_provider(model_size: str, device: str, compute_type: str) -> FasterWhisperProvider:
        key = (model_size, device, compute_type)
        # #region agent log
        _dbg_logger.debug("GET_PROVIDER: key=%s cached=%s", key, key in provider_cache)
        # #endregion
        if key not in provider_cache:
            # #region agent log
            _dbg_logger.debug("GET_PROVIDER_CREATE: creating new FasterWhisperProvider for %s", key)
            # #endregion
            provider_cache[key] = FasterWhisperProvider(
                WhisperConfig(
                    model_size=model_size,
                    device=device,
                    compute_type=compute_type,
                ),
                diarization_service,
            )
            # #region agent log
            _dbg_logger.debug("GET_PROVIDER_CREATED: %s", key)
            # #endregion
        return provider_cache[key]

    def get_pipeline(model_size: str, device: str, compute_type: str) -> TranscriptionPipeline:
        """Get a transcription pipeline with the specified provider configuration."""
        # #region agent log
        _dbg_logger.debug("GET_PIPELINE_START: model=%s device=%s compute=%s", model_size, device, compute_type)
        # #endregion
        provider = get_provider(model_size, device, compute_type)
        # #region agent log
        _dbg_logger.debug("GET_PIPELINE_GOT_PROVIDER: model=%s", model_size)
        # #endregion
        return TranscriptionPipeline(
            provider=provider,
            diarization_service=diarization_service,
            meeting_store=meeting_store,
            summarization_service=summarization_service,
        )

    def _run_transcription(
        meeting_id: str,
        audio_source: AudioDataSource,
        model_size: str,
        audio_offset: float = 0.0,
    ) -> None:
        """Run transcription from any audio source in background thread.
        
        This is the unified transcription loop for both mic and file modes:
        1. Reads audio chunks from AudioDataSource (mic or file)
        2. Transcribes and saves segments via meeting_store (publishes events)
        3. Runs until audio source is complete (recording stopped or file exhausted)
        4. Finalizes meeting with diarization and summarization
        
        If model_size is "none", live transcription is skipped but audio is still
        recorded and finalization will run with the final model.
        
        Args:
            meeting_id: The meeting ID to transcribe
            audio_source: Audio data source (mic or file)
            model_size: Whisper model size for live transcription
            audio_offset: Offset in seconds for resumed meetings (timestamps start here)
        """
        segments: list[dict] = []
        language = None
        skip_live_transcription = (model_size == "none")
        # #region agent log
        _dbg_logger.debug("THREAD_ENTER: meeting_id=%s model_size=%s audio_source_type=%s skip_live=%s audio_offset=%f", meeting_id, model_size, type(audio_source).__name__, skip_live_transcription, audio_offset)
        # #endregion
        
        # Debug: visible console output for resume troubleshooting
        print(f"[RESUME-DBG] Thread ENTERED: meeting_id={meeting_id} model_size={model_size} audio_offset={audio_offset}")
        
        try:
            metadata = audio_source.get_metadata()
            samplerate = metadata.samplerate
            channels = metadata.channels
            bytes_per_second = int(samplerate * channels * 2)  # 16-bit audio
            
            # Model-specific chunk duration
            chunk_seconds = transcription_config.get("live_chunk_seconds", 5.0)
            
            # Skip pipeline creation if live transcription is disabled
            pipeline = None if skip_live_transcription else get_pipeline(model_size, live_device, live_compute)
            # #region agent log
            _dbg_logger.debug("pipeline_created: meeting_id=%s samplerate=%d channels=%d bytes_per_second=%d chunk_seconds=%f", 
                             meeting_id, samplerate, channels, bytes_per_second, chunk_seconds)
            # #endregion
            
            # Create per-session real-time diarization (only if live transcription is enabled)
            session_rt_diarization = None
            rt_diarization_active = False
            if not skip_live_transcription:
                session_rt_diarization = RealtimeDiarizationService(realtime_diar_cfg)
                rt_diarization_active = session_rt_diarization.start(samplerate, channels)
            
            logger.info(
                "Transcription thread started: meeting_id=%s samplerate=%s channels=%s rt_diar=%s live_transcription=%s audio_offset=%s",
                meeting_id, samplerate, channels, rt_diarization_active, not skip_live_transcription, audio_offset
            )
            
            # Emit meta event
            meeting_store.append_live_meta(meeting_id, None)
            
            buffer = bytearray()
            offset_seconds = audio_offset  # Initialize with resume offset (0.0 for new recordings)
            
            # #region agent log
            _dbg_logger.debug("transcription_started: meeting_id=%s samplerate=%d channels=%d bytes_per_second=%d chunk_seconds=%f buffer_threshold=%f", 
                             meeting_id, samplerate, channels, bytes_per_second, chunk_seconds, bytes_per_second * chunk_seconds)
            chunk_count = 0
            _t_buffer_start = time.time()
            process_count = 0
            last_segment_end = 0.0
            loop_iter = 0
            _dbg_logger.debug("LOOP_ENTER: meeting_id=%s is_complete_before=%s", meeting_id, audio_source.is_complete())
            # #endregion
            # Debug: check if loop will even run
            print(f"[RESUME-DBG] Before loop: is_complete={audio_source.is_complete()} is_stopped={audio_source.is_stopped()}")
            while not audio_source.is_complete():
                # #region agent log
                loop_iter += 1
                if loop_iter <= 10 or loop_iter % 50 == 0:
                    _dbg_logger.debug("LOOP_ITER: iter=%d is_complete=%s buffer_len=%d", loop_iter, audio_source.is_complete(), len(buffer))
                # #endregion
                chunk = audio_source.get_chunk(timeout_sec=0.5)
                if chunk:
                    buffer.extend(chunk)
                    # #region agent log
                    chunk_count += 1
                    if chunk_count <= 5:
                        _dbg_logger.debug("CHUNK_RECEIVED: chunk_count=%d chunk_len=%d buffer_len=%d threshold=%f", 
                                         chunk_count, len(chunk), len(buffer), bytes_per_second * chunk_seconds)
                        # Debug: visible output for first few chunks
                        print(f"[RESUME-DBG] Chunk received: count={chunk_count} len={len(chunk)} buffer={len(buffer)}")
                    # #endregion
                
                # Process when we have enough audio
                if len(buffer) >= bytes_per_second * chunk_seconds:
                    # If live transcription is disabled, just track offset and clear buffer
                    if skip_live_transcription:
                        offset_seconds += len(buffer) / bytes_per_second
                        buffer.clear()
                        continue
                    
                    audio_bytes = bytes(buffer)
                    temp_path = None
                    try:
                        temp_path, temp_duration = _write_temp_wav(audio_bytes, samplerate, channels)
                        # #region agent log
                        _dbg_logger.debug("processing_chunk: buffer_len=%d offset_seconds=%f temp_duration=%f expected_duration=%f", 
                                         len(audio_bytes), offset_seconds, temp_duration, len(audio_bytes) / bytes_per_second)
                        # #endregion
                        
                        # #region agent log
                        _t_buffer_ready = time.time()
                        _buffer_fill_ms = round((_t_buffer_ready - _t_buffer_start) * 1000)
                        try:
                            with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f_lat:
                                _f_lat.write(json.dumps({"location":"transcription.py:buffer_ready","message":"buffer_threshold_reached","data":{"meeting_id":meeting_id,"buffer_fill_ms":_buffer_fill_ms,"buffer_bytes":len(audio_bytes),"chunk_seconds":chunk_seconds},"timestamp":int(time.time()*1000),"hypothesisId":"H1"})+"\n")
                        except Exception: pass
                        _t_buffer_start = time.time()
                        # #endregion
                        # Transcribe chunk
                        # #region agent log
                        _t_whisper_start = time.time()
                        # #endregion
                        chunk_segments, chunk_language, chunk_duration = pipeline.transcribe_chunk(
                            temp_path, offset_seconds
                        )
                        # #region agent log
                        _t_whisper_end = time.time()
                        _whisper_ms = round((_t_whisper_end - _t_whisper_start) * 1000)
                        process_count += 1
                        first_seg_start = chunk_segments[0].get("start") if chunk_segments else None
                        last_seg_end_in_chunk = max((s.get("end", 0) for s in chunk_segments), default=0) if chunk_segments else 0
                        gap_from_previous = first_seg_start - last_segment_end if (first_seg_start is not None and last_segment_end > 0) else 0
                        actual_chunk_duration = len(audio_bytes) / bytes_per_second
                        _dbg_logger.debug("chunk_transcribed: process_count=%d offset=%f whisper_dur=%f actual_dur=%f num_segs=%d first_start=%s last_end=%f gap=%f",
                                         process_count, offset_seconds, chunk_duration, actual_chunk_duration, len(chunk_segments),
                                         first_seg_start, last_seg_end_in_chunk, gap_from_previous)
                        if chunk_segments:
                            last_segment_end = last_seg_end_in_chunk
                        try:
                            with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f_lat:
                                _f_lat.write(json.dumps({"location":"transcription.py:whisper_done","message":"whisper_transcribe_chunk_done","data":{"meeting_id":meeting_id,"process_count":process_count,"whisper_ms":_whisper_ms,"num_segments":len(chunk_segments),"chunk_audio_seconds":actual_chunk_duration,"offset":offset_seconds},"timestamp":int(time.time()*1000),"hypothesisId":"H1"})+"\n")
                        except Exception: pass
                        # #endregion
                        
                        if chunk_language and not language:
                            language = chunk_language
                            meeting_store.append_live_meta(meeting_id, language)
                        
                        # Feed audio to real-time diarization
                        new_rt_annotations = []
                        # #region agent log
                        _t_diar_start = time.time()
                        # #endregion
                        if rt_diarization_active and session_rt_diarization.is_active():
                            new_rt_annotations = session_rt_diarization.feed_audio(audio_bytes)
                        # #region agent log
                        _t_diar_end = time.time()
                        _diar_ms = round((_t_diar_end - _t_diar_start) * 1000)
                        try:
                            with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f_lat:
                                _f_lat.write(json.dumps({"location":"transcription.py:rt_diarization","message":"rt_diarization_feed_done","data":{"meeting_id":meeting_id,"diar_ms":_diar_ms,"rt_active":rt_diarization_active,"annotations":len(new_rt_annotations)},"timestamp":int(time.time()*1000),"hypothesisId":"H3"})+"\n")
                        except Exception: pass
                        # #endregion
                        
                        # Process each segment
                        # #region agent log
                        _t_publish_start = time.time()
                        _seg_timings = []
                        # #endregion
                        for segment in chunk_segments:
                            # Try to get speaker from real-time diarization
                            if rt_diarization_active and session_rt_diarization.is_active():
                                speaker = session_rt_diarization.get_speaker_at(segment["start"])
                                # #region agent log
                                _dbg_logger.debug("get_speaker_at_result: seg_start=%f seg_end=%f speaker=%s rt_active=%s",
                                                 segment["start"], segment["end"], speaker, session_rt_diarization.is_active())
                                # #endregion
                                if speaker:
                                    segment["speaker"] = speaker
                            
                            segments.append(segment)
                            # #region agent log
                            _t_seg_start = time.time()
                            # #endregion
                            # Debug: segment being saved
                            print(f"[RESUME-DBG] Segment produced: start={segment.get('start'):.1f} text={segment.get('text', '')[:50]}")
                            meeting_store.append_live_segment(meeting_id, segment, language or chunk_language)
                            # #region agent log
                            _seg_timings.append(round((time.time() - _t_seg_start) * 1000))
                            # #endregion
                        
                        # #region agent log
                        _t_publish_end = time.time()
                        _publish_ms = round((_t_publish_end - _t_publish_start) * 1000)
                        _total_pipeline_ms = round((_t_publish_end - _t_whisper_start) * 1000)
                        try:
                            with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f_lat:
                                _f_lat.write(json.dumps({"location":"transcription.py:segments_published","message":"all_segments_published","data":{"meeting_id":meeting_id,"process_count":process_count,"whisper_ms":_whisper_ms,"diar_ms":_diar_ms,"publish_ms":_publish_ms,"total_pipeline_ms":_total_pipeline_ms,"num_segments":len(chunk_segments),"per_segment_ms":_seg_timings},"timestamp":int(time.time()*1000),"hypothesisId":"H1,H2"})+"\n")
                        except Exception: pass
                        # #endregion
                        
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
            
            # Process remaining buffer (only if live transcription is enabled)
            if buffer and not skip_live_transcription:
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
            if session_rt_diarization and session_rt_diarization.is_active():
                session_rt_diarization.stop()
            
            # Check if this is a resumed meeting (has existing audio that needs concatenation)
            is_resumed_meeting = audio_offset > 0
            
            # Unregister from job registry BEFORE finalization.
            # This frees the slot so starting a new transcription (even for
            # the same file) is not blocked by the dedup guard while
            # finalization (diarization + summarization) runs in this thread.
            with transcription_jobs_lock:
                transcription_jobs.pop(meeting_id, None)
            logger.info("Transcription active phase done, starting finalization: meeting_id=%s is_resumed=%s", meeting_id, is_resumed_meeting)
            
            # Transition to finalizing state in the tracker
            active_tracker.transition(meeting_id, MeetingState.FINALIZING)
            # #region agent log
            _dbg_logger.debug("POST_LOOP_FINALIZING: meeting_id=%s", meeting_id)
            # #endregion
            
            # Wait for audio compression/concatenation before finalization reads audio_path.
            # WAV→Opus compression runs async; without this wait, finalization may read
            # the stale .wav path after the file has already been deleted.
            # #region agent log
            try:
                with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f_res:
                    _f_res.write(json.dumps({"location":"transcription.py:before_wait_check","message":"About to check is_resumed_meeting","data":{"meeting_id":meeting_id,"is_resumed_meeting":is_resumed_meeting,"audio_offset":audio_offset},"timestamp":int(time.time()*1000),"hypothesisId":"A"})+"\n")
            except: pass
            # #endregion
            # Wait for audio compression/concatenation to complete before finalization.
            # For WAV recordings, compression to Opus runs async; we must wait so
            # the meeting's audio_path is updated before diarization tries to read it.
            if True:
                if is_resumed_meeting:
                    logger.info("Resumed meeting: waiting for audio concatenation to complete...")
                else:
                    logger.info("Waiting for audio compression to complete...")
                # #region agent log
                try:
                    with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f_res:
                        _f_res.write(json.dumps({"location":"transcription.py:before_wait","message":"Calling wait_for_compression","data":{"meeting_id":meeting_id,"is_resumed":is_resumed_meeting},"timestamp":int(time.time()*1000),"hypothesisId":"A"})+"\n")
                except: pass
                # #endregion
                meeting_store.publish_finalization_status(
                    meeting_id,
                    "Processing audio..." if not is_resumed_meeting else "Combining audio files...",
                    0.02,
                )
                combined_audio_path = audio_service.wait_for_compression(timeout=300)
                # #region agent log
                try:
                    with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f_res:
                        _f_res.write(json.dumps({"location":"transcription.py:after_wait","message":"wait_for_compression returned","data":{"meeting_id":meeting_id,"combined_audio_path":combined_audio_path},"timestamp":int(time.time()*1000),"hypothesisId":"A"})+"\n")
                except: pass
                # #endregion
                if combined_audio_path:
                    logger.info("Audio concatenation complete: %s", combined_audio_path)
                    print(f"[RESUME-DBG] Audio concatenation complete: {combined_audio_path}")
                else:
                    logger.warning("Audio concatenation timed out or failed, proceeding with available audio")
                    print("[RESUME-DBG] Audio concatenation timed out or failed")
            
            try:
                meeting = meeting_store.get_meeting(meeting_id)
                # #region agent log
                _dbg_logger.debug("GOT_MEETING: meeting_id=%s has_meeting=%s", meeting_id, bool(meeting))
                import time as _t_fin; import json as _j_fin
                try:
                    with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f_fin:
                        _f_fin.write(_j_fin.dumps({"location":"transcription.py:_run_transcription","message":"FINALIZATION_PHASE_ENTERED","data":{"meeting_id":meeting_id,"has_meeting":bool(meeting),"has_segments":bool(meeting and (meeting.get("transcript") or {}).get("segments"))},"timestamp":int(_t_fin.time()*1000),"hypothesisId":"C"})+"\n")
                except Exception: pass
                # #endregion
                if meeting:
                    transcript = meeting.get("transcript") or {}
                    disk_segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
                    audio_path = meeting.get("audio_path")
                    # #region agent log
                    _dbg_logger.debug("MEETING_DATA: meeting_id=%s num_segments=%d has_audio_path=%s", meeting_id, len(disk_segments), bool(audio_path))
                    try:
                        with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f_fin:
                            _f_fin.write(_j_fin.dumps({"location":"transcription.py:finalization_audio_path","message":"Audio path for finalization","data":{"meeting_id":meeting_id,"audio_path":audio_path,"audio_exists":os.path.isfile(audio_path) if audio_path else False,"num_segments":len(disk_segments)},"timestamp":int(_t_fin.time()*1000),"hypothesisId":"B,C,E"})+"\n")
                    except: pass
                    # #endregion
                    
                    # Debug: show which audio file will be used for finalization
                    print(f"[RESUME-DBG] Finalization using audio_path: {audio_path} (exists={os.path.isfile(audio_path) if audio_path else False})")
                    
                    if disk_segments:
                        # Re-transcribe with final model if configured and different
                        final_model = final_default_size
                        # #region agent log
                        _dbg_logger.debug("RETRANSCRIBE_CHECK: meeting_id=%s final_model=%s live_model=%s audio_path=%s audio_exists=%s",
                                         meeting_id, final_model, model_size, audio_path, os.path.isfile(audio_path) if audio_path else False)
                        # #endregion
                        if (
                            final_model
                            and final_model != "none"
                            and final_model != model_size
                            and audio_path
                            and os.path.isfile(audio_path)
                        ):
                            # #region agent log
                            try:
                                with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f_rt:
                                    _f_rt.write(json.dumps({"location":"transcription.py:retranscription:start","message":"Starting re-transcription","data":{"meeting_id":meeting_id,"audio_path":audio_path,"final_model":final_model,"live_model":model_size,"segments_before":len(disk_segments)},"timestamp":int(time.time()*1000),"hypothesisId":"E"})+"\n")
                            except: pass
                            # #endregion
                            meeting_store.publish_finalization_status(
                                meeting_id,
                                f"Re-transcribing with {final_model} model...",
                                0.05,
                            )
                            meeting_store.publish_status_log(
                                meeting_id, "retranscription", "started",
                                {"live_model": model_size, "final_model": final_model, "audio_path": audio_path},
                            )
                            debug_log('TRANSCRIPTION', 'Re-transcription started: meeting=%s live_model=%s final_model=%s wav=%s',
                                      meeting_id, model_size, final_model, audio_path)
                            logger.info(
                                "Re-transcribing: meeting_id=%s live_model=%s final_model=%s wav=%s",
                                meeting_id, model_size, final_model, audio_path,
                            )
                            try:
                                debug_log('TRANSCRIPTION', 'Loading pipeline: model=%s device=%s compute=%s',
                                          final_model, final_device, final_compute)
                                meeting_store.publish_status_log(
                                    meeting_id, "retranscription", "progress",
                                    {"step": "loading_model", "model": final_model, "device": final_device, "compute_type": final_compute},
                                )
                                final_pipeline = get_pipeline(final_model, final_device, final_compute)

                                debug_log('TRANSCRIPTION', 'Pipeline loaded, starting transcribe_and_format on %s', audio_path)
                                meeting_store.publish_status_log(
                                    meeting_id, "retranscription", "progress",
                                    {"step": "transcribing", "audio_path": audio_path},
                                )
                                retrans_start = time.time()
                                new_segments, new_language = final_pipeline.transcribe_and_format(audio_path)
                                retrans_elapsed = round(time.time() - retrans_start, 2)

                                debug_log('TRANSCRIPTION', 'Re-transcription finished: segments=%d language=%s elapsed=%.2fs',
                                          len(new_segments) if new_segments else 0, new_language, retrans_elapsed)
                                # #region agent log
                                try:
                                    with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f_rt:
                                        _f_rt.write(json.dumps({"location":"transcription.py:retranscription:result","message":"Re-transcription result","data":{"meeting_id":meeting_id,"new_segments_count":len(new_segments) if new_segments else 0,"new_language":new_language,"elapsed":retrans_elapsed},"timestamp":int(time.time()*1000),"hypothesisId":"E"})+"\n")
                                except: pass
                                # #endregion
                                if new_segments:
                                    disk_segments = new_segments
                                    meeting_store.replace_transcript_segments(meeting_id, disk_segments, new_language)
                                    # #region agent log
                                    try:
                                        with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f_rt:
                                            _f_rt.write(json.dumps({"location":"transcription.py:retranscription:replaced","message":"Segments replaced","data":{"meeting_id":meeting_id,"new_count":len(disk_segments),"language":new_language},"timestamp":int(time.time()*1000),"hypothesisId":"E"})+"\n")
                                    except: pass
                                    # #endregion
                                    logger.info(
                                        "Re-transcription complete: meeting_id=%s segments=%d elapsed=%.2fs",
                                        meeting_id, len(disk_segments), retrans_elapsed,
                                    )
                                    meeting_store.publish_status_log(
                                        meeting_id, "retranscription", "output",
                                        {"segments_count": len(disk_segments), "language": new_language, "elapsed_seconds": retrans_elapsed},
                                    )
                                else:
                                    debug_log('TRANSCRIPTION', 'Re-transcription returned no segments, keeping live transcript')
                                    meeting_store.publish_status_log(
                                        meeting_id, "retranscription", "output",
                                        {"segments_count": 0, "note": "No segments returned, keeping live transcript", "elapsed_seconds": retrans_elapsed},
                                    )
                                meeting_store.publish_status_log(
                                    meeting_id, "retranscription", "completed",
                                )
                            except Exception as exc:
                                debug_log('TRANSCRIPTION', 'Re-transcription failed: %s: %s', type(exc).__name__, str(exc)[:500])
                                logger.warning(
                                    "Re-transcription failed, using live segments: meeting_id=%s error=%s",
                                    meeting_id, exc,
                                )
                                meeting_store.publish_finalization_status(
                                    meeting_id,
                                    f"Re-transcription failed: {type(exc).__name__}. Using live transcript.",
                                    0.08,
                                )
                                meeting_store.publish_status_log(
                                    meeting_id, "retranscription", "failed",
                                    {"error": f"{type(exc).__name__}: {str(exc)[:200]}"},
                                )
                        else:
                            if final_model and final_model != "none" and final_model != model_size:
                                debug_log('TRANSCRIPTION', 'Re-transcription skipped: audio_path=%s exists=%s',
                                          audio_path, os.path.isfile(audio_path) if audio_path else False)
                                meeting_store.publish_status_log(
                                    meeting_id, "retranscription", "skipped",
                                    {"reason": "Audio file not available", "audio_path": audio_path},
                                )

                        # #region agent log
                        _dbg_logger.debug("FINAL_PIPELINE_GET: meeting_id=%s model=%s device=%s compute=%s",
                                         meeting_id, final_model if final_model != "none" else model_size, final_device, final_compute)
                        # #endregion
                        # Transcription is done (re-transcribed, skipped, or used live segments)
                        meeting_store.mark_finalization_stage(meeting_id, "transcription")

                        final_pipeline = get_pipeline(
                            final_model if final_model != "none" else model_size,
                            final_device, final_compute,
                        )
                        # #region agent log
                        _dbg_logger.debug("FINALIZE_START: meeting_id=%s num_segments=%d has_audio_path=%s", meeting_id, len(disk_segments), bool(audio_path))
                        # #endregion
                        final_pipeline.finalize_meeting_with_diarization(
                            meeting_id, disk_segments, audio_path
                        )
                        # #region agent log
                        _dbg_logger.debug("FINALIZE_COMPLETE: meeting_id=%s", meeting_id)
                        # #endregion
                        logger.info("Meeting finalized: meeting_id=%s segments=%d", meeting_id, len(disk_segments))
                    else:
                        for stage in ("transcription", "diarization", "speaker_names", "summary"):
                            meeting_store.mark_finalization_stage(meeting_id, stage)
                        meeting_store.update_status(meeting_id, "completed")
                        logger.info("Meeting completed (no segments): meeting_id=%s", meeting_id)
                else:
                    for stage in ("transcription", "diarization", "speaker_names", "summary"):
                        meeting_store.mark_finalization_stage(meeting_id, stage)
                    meeting_store.update_status(meeting_id, "completed")
            finally:
                active_tracker.unregister(meeting_id)
                
        except Exception as exc:
            logger.exception("Transcription error: meeting_id=%s error=%s", meeting_id, exc)
            # #region agent log
            import traceback as _tb_run
            _dbg_logger.debug("THREAD_CRASH: meeting_id=%s exc_type=%s exc_str=%s", meeting_id, type(exc).__name__, str(exc)[:500])
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
            # Also ensure tracker is cleaned up
            active_tracker.unregister(meeting_id)
            logger.info("Transcription thread finished: meeting_id=%s segments=%d", meeting_id, len(segments))

    @router.post("/api/transcribe/simulate")
    def simulate_transcribe(payload: SimulateTranscribeRequest) -> dict:
        """Start transcription from either a microphone or a file.

        Both modes use the same downstream pipeline: AudioCaptureService
        feeds _audio_callback -> queues -> _writer_loop (WAV) + _live_queue
        (LiveAudioSource) -> _run_transcription thread.
        """
        source = payload.source

        # --- Start audio capture (only branch between mic and file) ---
        if source == "mic":
            if payload.device_index is None:
                raise HTTPException(status_code=400, detail="device_index required for mic mode")
            try:
                result = audio_service.start_recording(
                    device_index=payload.device_index,
                    samplerate=payload.samplerate,
                    channels=payload.channels,
                )
            except Exception as exc:
                logger.exception("Failed to start mic recording: %s", exc)
                raise HTTPException(status_code=400, detail=f"Failed to start recording: {exc}")
            audio_service.enable_live_tap()
            original_audio_path = None
        elif source == "file":
            original_audio_path = payload.audio_path
            if not original_audio_path or not os.path.isabs(original_audio_path):
                raise HTTPException(status_code=400, detail="audio_path must be an absolute path")
            # Dedup: check if this file is already being transcribed
            existing = next(
                (job for job in transcription_jobs.values() if job.get("original_audio_path") == original_audio_path),
                None,
            )
            if existing:
                return {"status": "running", "meeting_id": existing.get("meeting_id")}
            try:
                result = audio_service.start_file_playback(
                    original_audio_path,
                    speed_percent=payload.speed_percent,
                )
            except Exception as exc:
                logger.exception("Failed to start file playback: %s", exc)
                raise HTTPException(status_code=400, detail=f"Failed to start file playback: {exc}")
        else:
            raise HTTPException(status_code=400, detail=f"Invalid source: {source}. Must be 'mic' or 'file'.")

        # --- Everything below is identical for both modes ---
        recording_id = result["recording_id"]
        wav_path = result["file_path"]
        samplerate = result["samplerate"]
        channels = result["channels"]

        if payload.meeting_id:
            meeting = meeting_store.get_meeting(payload.meeting_id)
            if not meeting:
                audio_service.stop_recording()
                raise HTTPException(status_code=404, detail="Meeting not found")
        else:
            meeting = meeting_store.create_file_meeting(
                wav_path, samplerate, channels,
                session_id=recording_id,
            )

        meeting_id = meeting.get("id")
        if not meeting_id:
            audio_service.stop_recording()
            raise HTTPException(status_code=500, detail="Failed to create meeting")
        meeting_store.update_status(meeting_id, "in_progress")
        
        # Set meeting context for audio level publishing
        audio_service.set_meeting_context(meeting_id, meeting_store)
        model_size = payload.model_size or live_default_size

        if not active_tracker.register(
            meeting_id,
            MeetingState.RECORDING,
            audio_source=source,
            audio_path=wav_path,
        ):
            audio_service.stop_recording()
            return {"status": "already_active", "meeting_id": meeting_id}

        audio_source = LiveAudioSource(audio_service, recording_id)

        thread = threading.Thread(
            target=_run_transcription,
            args=(meeting_id, audio_source, model_size),
            daemon=True,
        )
        transcription_jobs[meeting_id] = {
            "meeting_id": meeting_id,
            "audio_source": audio_source,
            "audio_path": wav_path,
            "original_audio_path": original_audio_path,
        }
        logger.info(
            "Transcription started: source=%s meeting_id=%s wav=%s",
            source, meeting_id, wav_path,
        )
        thread.start()
        return {"status": "started", "meeting_id": meeting_id}

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
          recording             – actively processing audio (mic or file)
          paused                – recording is paused (audio not being captured)
          finalizing            – live diarization / summarization running
          background_finalizing – background sweep processing
          idle                  – nothing running for this meeting
        """
        active = active_tracker.get_state(meeting_id)
        if active:
            state_value = active.state.value
            # Check if recording is paused
            if active.state == MeetingState.RECORDING and audio_service.is_paused():
                state_value = "paused"
            return {
                "meeting_id": meeting_id,
                "state": state_value,
                "stage": active.stage,
                "started_at": active.started_at.isoformat(),
                "paused": audio_service.is_paused() if active.state == MeetingState.RECORDING else False,
            }
        return {"meeting_id": meeting_id, "state": "idle", "paused": False}

    @router.get("/api/transcribe/finalizing")
    def get_finalizing_meetings_list() -> dict:
        """Return IDs and start times of all meetings currently in finalization."""
        all_active = active_tracker.get_all_active()
        meetings = {}
        for mid, am in all_active.items():
            if am.state in (MeetingState.FINALIZING, MeetingState.BACKGROUND_FINALIZING):
                meetings[mid] = {
                    "started_at": am.started_at.isoformat(),
                    "stage": am.stage,
                }
        return {"meeting_ids": list(meetings.keys()), "meetings": meetings}

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
        _dbg_logger.debug("stop called: meeting_id=%s transcription_jobs=%d", meeting_id, len(transcription_jobs))
        # #endregion
        
        # Unified job lookup from registry
        with transcription_jobs_lock:
            job = transcription_jobs.get(meeting_id)
        
        if job:
            audio_source = job.get("audio_source")
            
            # Unified stop: audio_source.stop() handles everything for both modes
            if audio_source:
                audio_source.stop()
                logger.info("AudioDataSource.stop() called: meeting_id=%s", meeting_id)
            
            # #region agent log
            _dbg_logger.debug("unified stop completed: meeting_id=%s had_audio_source=%s", meeting_id, audio_source is not None)
            # #endregion
            
            logger.info("Stopped transcription: meeting_id=%s", meeting_id)
            return {
                "status": "stopping", 
                "meeting_id": meeting_id, 
                "message": "Stop signal sent. Processing of buffered audio continues in background."
            }
        
        return {"status": "not_found", "meeting_id": meeting_id}

    @router.post("/api/transcribe/pause/{meeting_id}")
    def pause_transcription(meeting_id: str) -> dict:
        """Pause audio ingestion for a meeting.
        
        When paused:
        - Audio from microphone/file is ignored (not transcribed)
        - Opus file stops recording new audio
        - For file playback, the file continues playing (audio is lost during pause)
        
        Returns immediately with pause status.
        """
        # Check if meeting is actively recording
        active = active_tracker.get_state(meeting_id)
        if not active or active.state != MeetingState.RECORDING:
            raise HTTPException(
                status_code=400,
                detail="Meeting is not actively recording"
            )
        
        # Check if already paused
        if audio_service.is_paused():
            return {
                "status": "already_paused",
                "meeting_id": meeting_id,
            }
        
        # Pause the audio capture
        try:
            result = audio_service.pause()
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        
        logger.info("Paused transcription: meeting_id=%s", meeting_id)
        return {
            "status": "paused",
            "meeting_id": meeting_id,
            "paused_at": result.get("paused_at"),
        }

    @router.post("/api/transcribe/unpause/{meeting_id}")
    def unpause_transcription(meeting_id: str) -> dict:
        """Resume audio ingestion for a paused meeting.
        
        When unpaused:
        - Audio ingestion resumes with continuous timestamps
        - A pause marker is added to the transcript showing wall-clock duration
        
        Returns immediately with unpause status.
        """
        from app.services.audio_utils import get_audio_duration
        
        # Check if meeting is actively recording
        active = active_tracker.get_state(meeting_id)
        if not active or active.state != MeetingState.RECORDING:
            raise HTTPException(
                status_code=400,
                detail="Meeting is not actively recording"
            )
        
        # Check if actually paused
        if not audio_service.is_paused():
            return {
                "status": "not_paused",
                "meeting_id": meeting_id,
            }
        
        # Unpause the audio capture
        try:
            result = audio_service.unpause()
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        
        # Get current audio position for the pause marker
        # For simplicity, we estimate based on what's been recorded so far
        # The audio file is still being written, so we use the current status
        status = audio_service.current_status()
        audio_path = status.get("file_path")
        audio_position = 0.0
        if audio_path and os.path.isfile(audio_path):
            try:
                duration = get_audio_duration(audio_path)
                if duration:
                    audio_position = duration
            except Exception:
                pass
        
        # Add pause marker to meeting
        meeting_store.add_pause_marker(
            meeting_id,
            audio_position=audio_position,
            paused_at=result.get("paused_at", datetime.utcnow().isoformat()),
            resumed_at=result.get("resumed_at", datetime.utcnow().isoformat()),
        )
        
        logger.info(
            "Unpaused transcription: meeting_id=%s pause_duration=%.1fs",
            meeting_id,
            result.get("pause_duration_seconds", 0),
        )
        return {
            "status": "resumed",
            "meeting_id": meeting_id,
            "paused_at": result.get("paused_at"),
            "resumed_at": result.get("resumed_at"),
            "pause_duration_seconds": result.get("pause_duration_seconds", 0),
        }

    @router.post("/api/transcribe/resume/{meeting_id}")
    def resume_transcription(meeting_id: str) -> dict:
        """Resume recording for a meeting that was stopped.
        
        This continues the meeting by:
        1. Getting the duration of the existing audio (for timestamp offset)
        2. Starting a new mic recording (new WAV file)
        3. Recording a pause marker
        4. Running transcription with the offset so timestamps are additive
        5. On stop, the new audio will be concatenated with the existing audio
        """
        from app.services.audio_utils import get_audio_duration
        
        # Check if any transcription is already running (use tracker)
        recording = active_tracker.get_by_state(MeetingState.RECORDING)
        if recording:
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
        existing_audio_path = meeting.get("audio_path")
        if not existing_audio_path:
            raise HTTPException(status_code=400, detail="Meeting has no audio file")
        if not os.path.exists(existing_audio_path):
            raise HTTPException(status_code=400, detail="Audio file not found")
        
        # Get duration of existing audio = offset for new segments
        audio_offset = get_audio_duration(existing_audio_path)
        if audio_offset is None:
            raise HTTPException(status_code=400, detail="Could not determine audio duration")
        
        # Get audio device settings
        audio_config = audio_service.get_config()
        device_index = audio_config.get("device_index")
        if device_index is None:
            raise HTTPException(status_code=400, detail="No audio device configured. Please configure in Settings.")
        samplerate = audio_config.get("samplerate", 48000)
        channels = audio_config.get("channels", 2)
        
        # Record pause marker (paused_at from meeting.ended_at, resumed_at = now)
        paused_at = meeting.get("ended_at") or datetime.utcnow().isoformat()
        resumed_at = datetime.utcnow().isoformat()
        meeting_store.add_pause_marker(
            meeting_id,
            audio_position=audio_offset,
            paused_at=paused_at,
            resumed_at=resumed_at,
        )
        
        # Start NEW mic recording (creates new WAV file)
        try:
            result = audio_service.start_recording(
                device_index=device_index,
                samplerate=samplerate,
                channels=channels,
            )
        except Exception as exc:
            logger.exception("Failed to start mic recording for resume: %s", exc)
            raise HTTPException(status_code=400, detail=f"Failed to start recording: {exc}")
        
        audio_service.enable_live_tap()
        
        recording_id = result["recording_id"]
        new_wav_path = result["file_path"]
        
        # Set meeting context for audio level publishing and compression
        # Include existing_audio_path so compression knows to concatenate
        audio_service.set_meeting_context(meeting_id, meeting_store, existing_audio_path)

        # Update meeting status back to in_progress
        meeting_store.update_status(meeting_id, "in_progress")
        # Clear finalization flags since transcript will change
        meeting_store.clear_finalization_flags(meeting_id)

        # Register with active tracker - store existing audio path for concatenation
        if not active_tracker.register(
            meeting_id,
            MeetingState.RECORDING,
            audio_source="mic",
            audio_path=new_wav_path,
            existing_audio_path=existing_audio_path,  # For concatenation on stop
        ):
            audio_service.stop_recording()
            raise HTTPException(
                status_code=409,
                detail="Meeting is already being processed"
            )

        audio_source_obj = LiveAudioSource(audio_service, recording_id)
        model_size_for_resume = live_default_size  # Use same model as normal recording
        logger.info(
            "Resume: creating transcription thread meeting_id=%s model_size=%s audio_offset=%.1f",
            meeting_id, model_size_for_resume, audio_offset
        )
        
        thread = threading.Thread(
            target=_run_transcription,
            args=(meeting_id, audio_source_obj, model_size_for_resume, audio_offset),
            daemon=True,
            name=f"transcribe-resume-{meeting_id[:8]}",
        )
        transcription_jobs[meeting_id] = {
            "meeting_id": meeting_id,
            "audio_source": audio_source_obj,
            "audio_path": new_wav_path,
            "existing_audio_path": existing_audio_path,  # For concatenation on stop
        }
        logger.info(
            "Resumed recording: meeting_id=%s existing_audio=%s new_wav=%s offset=%.1fs model=%s",
            meeting_id, existing_audio_path, new_wav_path, audio_offset, model_size_for_resume
        )
        thread.start()
        logger.info("Resume: transcription thread started, thread.is_alive=%s", thread.is_alive())
        return {"status": "resumed", "meeting_id": meeting_id, "audio_offset": audio_offset}

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
