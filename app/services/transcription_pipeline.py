"""
Unified transcription pipeline that handles post-processing for all transcription flows.

This service centralizes:
- Segment formatting (whisper output → standard dict format)
- Diarization application (speaker identification)
- Meeting store updates
- Summarization and auto-title generation

All transcription endpoints should use this pipeline after obtaining audio.
"""

from __future__ import annotations

import logging
import os
import json
import tempfile
import threading
import time
import uuid
from typing import TYPE_CHECKING, Iterator, Optional

import shutil
import subprocess

import numpy as np
import soundfile as sf

from app.services.debug_logging import dbg

_logger = logging.getLogger(__name__)


def _ffmpeg_to_wav(input_path: str, output_path: str) -> tuple[int, int]:
    """Convert any audio file to WAV using ffmpeg.

    Returns (samplerate, channels) of the output file.
    Raises RuntimeError if ffmpeg is not available or conversion fails.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on PATH — needed for MP3/AAC/etc. conversion")

    result = subprocess.run(
        [
            ffmpeg, "-y", "-i", input_path,
            "-acodec", "pcm_s16le",
            output_path,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({result.returncode}): {result.stderr[-500:]}")

    info = sf.info(output_path)
    return info.samplerate, info.channels


def convert_to_wav(
    input_path: str,
    output_dir: str,
    target_samplerate: int = 48000,
    target_channels: int = 2,
) -> tuple[str, int, int]:
    """Convert any audio file to PCM_16 WAV using ffmpeg.

    Uses ffmpeg as the single conversion path so every format it supports
    (MP3, AAC, M4A, OGG, FLAC, WAV, etc.) works identically.  This keeps
    the file-upload pipeline consistent with the mic pipeline, where raw
    PCM is already written to WAV by ``_write_temp_wav``.

    Args:
        input_path: Path to input audio file (any format ffmpeg supports).
        output_dir: Directory to write the output WAV file.
        target_samplerate: Unused (kept for API compat); actual rate is
            preserved from the source file.
        target_channels: Unused (kept for API compat); actual channel
            count is preserved from the source file.

    Returns:
        Tuple of (output_wav_path, actual_samplerate, actual_channels).
    """
    os.makedirs(output_dir, exist_ok=True)

    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    output_filename = f"{timestamp}-{uuid.uuid4()}.wav"
    output_path = os.path.join(output_dir, output_filename)

    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Audio file not found: {input_path}")

    _logger.info("Converting audio via ffmpeg: input=%s output=%s", input_path, output_path)
    actual_samplerate, actual_channels = _ffmpeg_to_wav(input_path, output_path)

    _logger.info(
        "Audio converted: output=%s samplerate=%d channels=%d",
        output_path, actual_samplerate, actual_channels,
    )

    return output_path, actual_samplerate, actual_channels

if TYPE_CHECKING:
    from app.services.transcription import FasterWhisperProvider
    from app.services.diarization import DiarizationService
    from app.services.meeting_store import MeetingStore
    from app.services.summarization import SummarizationService


def apply_diarization(
    segments: list[dict], diarization_segments: list[dict]
) -> list[dict]:
    """Apply speaker labels to transcript segments based on diarization output.
    
    Matches each segment to a diarization interval by start time and assigns
    the corresponding speaker label.
    """
    if not diarization_segments:
        return segments
    
    diarization_segments = sorted(diarization_segments, key=lambda seg: seg["start"])
    
    for segment in segments:
        for diar in diarization_segments:
            if diar["start"] <= segment["start"] < diar["end"]:
                segment["speaker"] = diar["speaker"]
                break
    
    return segments


class TranscriptionPipeline:
    """Unified pipeline for transcription post-processing.
    
    Handles the common workflow after audio is obtained:
    1. Transcription via whisper
    2. Segment formatting
    3. Diarization (optional)
    4. Meeting store updates
    5. Summarization and title generation
    """
    
    def __init__(
        self,
        provider: "FasterWhisperProvider",
        diarization_service: "DiarizationService",
        meeting_store: "MeetingStore",
        summarization_service: "SummarizationService",
    ) -> None:
        self._provider = provider
        self._diarization = diarization_service
        self._meeting_store = meeting_store
        self._summarization = summarization_service
        self._logger = logging.getLogger("notetaker.transcription.pipeline")

    def get_chunk_size(self) -> float:
        """Get the optimal chunk size for live transcription.
        
        Returns the provider's optimal chunk size, which varies by model:
        - Whisper: 30 seconds (fixed encoder window)
        - Parakeet: 2 seconds (configurable streaming)
        - Vosk: 0.5 seconds (native streaming)
        """
        return self._provider.get_chunk_size()
    
    def transcribe_and_format(
        self,
        audio_path: str,
        cancel_event: Optional[threading.Event] = None,
    ) -> tuple[list[dict], Optional[str]]:
        """Transcribe audio and format segments to standard dict format.
        
        Args:
            audio_path: Path to audio file
            cancel_event: Optional threading.Event to check for cancellation
            
        Returns:
            Tuple of (formatted segments, detected language)
        """
        segments_iter, info = self._provider.stream_segments(audio_path)
        language = getattr(info, "language", None)
        
        segments: list[dict] = []
        for segment in segments_iter:
            # Check for cancellation after each segment
            if cancel_event and cancel_event.is_set():
                self._logger.info("Transcription cancelled during processing")
                break
            segments.append({
                "type": "segment",
                "start": float(segment.start),
                "end": float(segment.end),
                "text": segment.text.strip(),
                "speaker": None,
            })
        
        return segments, language
    
    def stream_transcribe_and_format(
        self,
        audio_path: str,
        cancel_event: Optional[threading.Event] = None,
    ) -> Iterator[tuple[dict, Optional[str]]]:
        """Stream transcription segments one at a time for live updates.
        
        Args:
            audio_path: Path to audio file
            cancel_event: Optional threading.Event to check for cancellation
            
        Yields:
            Tuples of (segment dict, detected language)
        """
        segments_iter, info = self._provider.stream_segments(audio_path)
        language = getattr(info, "language", None)
        
        for segment in segments_iter:
            # Check for cancellation after each segment
            if cancel_event and cancel_event.is_set():
                self._logger.info("Transcription cancelled during streaming")
                return
            yield {
                "type": "segment",
                "start": float(segment.start),
                "end": float(segment.end),
                "text": segment.text.strip(),
                "speaker": None,
            }, language

    def run_diarization(
        self,
        audio_path: str,
        segments: list[dict],
    ) -> list[dict]:
        """Apply diarization to segments if enabled.
        
        Args:
            audio_path: Path to audio file (needed for diarization)
            segments: List of transcript segments
            
        Returns:
            Segments with speaker labels applied (if diarization enabled)
        """
        if not self._diarization.is_enabled():
            return segments
        
        try:
            self._logger.info("Diarization start: audio=%s", audio_path)
            # #region agent log
            try:
                dbg(
                    self._logger,
                    location="app/services/transcription_pipeline.py:run_diarization",
                    message="run_diarization_before_run",
                    data={
                        "provider": getattr(self._diarization, "get_provider_name", lambda: "unknown")(),
                        "segments_in": len(segments) if segments else 0,
                        "audio_basename": os.path.basename(audio_path or ""),
                    },
                    run_id="pre-fix",
                    hypothesis_id="H3",
                )
            except Exception:
                pass
            # #endregion
            diarization_segments = self._diarization.run(audio_path)
            segments = apply_diarization(segments, diarization_segments)
            speaker_count = len(set(s.get("speaker") for s in segments if s.get("speaker")))
            self._logger.info("Diarization complete: speakers=%s", speaker_count)
            # #region agent log
            try:
                dbg(
                    self._logger,
                    location="app/services/transcription_pipeline.py:run_diarization",
                    message="run_diarization_after_apply",
                    data={
                        "diarization_segments": len(diarization_segments) if diarization_segments else 0,
                        "segments_out": len(segments) if segments else 0,
                        "speakers": speaker_count,
                    },
                    run_id="pre-fix",
                    hypothesis_id="H5",
                )
            except Exception:
                pass
            # #endregion
        except Exception as exc:
            self._logger.warning("Diarization failed: %s", exc)
            # #region agent log
            try:
                dbg(
                    self._logger,
                    location="app/services/transcription_pipeline.py:run_diarization",
                    message="run_diarization_error",
                    data={"exc_type": type(exc).__name__, "exc_str": str(exc)[:800]},
                    run_id="pre-fix",
                    hypothesis_id="H1",
                )
            except Exception:
                pass
            # #endregion
        
        return segments
    
    def process_audio_file(
        self,
        audio_path: str,
        meeting_id: Optional[str] = None,
        apply_diarization: bool = True,
        update_meeting_live: bool = False,
    ) -> tuple[list[dict], Optional[str]]:
        """Full transcription pipeline for a complete audio file.
        
        Args:
            audio_path: Path to audio file
            meeting_id: Optional meeting ID for store updates
            apply_diarization: Whether to run diarization (default True)
            update_meeting_live: Whether to update meeting store during transcription
            
        Returns:
            Tuple of (formatted segments with speakers, detected language)
        """
        # Step 1: Transcribe and format
        segments, language = self.transcribe_and_format(audio_path)
        
        # Step 2: Update meeting store with initial segments (if requested)
        if meeting_id and update_meeting_live:
            self._meeting_store.append_live_meta(meeting_id, language)
            for segment in segments:
                self._meeting_store.append_live_segment(meeting_id, segment, language)
        
        # Step 3: Apply diarization (if requested and enabled)
        if apply_diarization:
            segments = self.run_diarization(audio_path, segments)
            # Update speakers in meeting store
            if meeting_id:
                self._meeting_store.update_transcript_speakers(meeting_id, segments)
        
        # Step 4: Save final transcript
        self._meeting_store.add_transcript(audio_path, language, segments)
        
        return segments, language

    def persist_and_finalize_meeting(
        self,
        meeting_id: str,
        audio_path: str,
        language: Optional[str],
        segments: list[dict],
        *,
        apply_diarization: bool = True,
    ) -> list[dict]:
        """Persist transcript and finalize meeting via a single shared pipeline.
        
        This is the convergence point for live (mic) vs file flows once audio is obtained.
        
        Behavior:
        - Optionally applies batch diarization (if enabled) and updates stored speakers
        - Saves transcript to storage
        - Finalizes meeting (status=completed, summary, auto-title) via enhanced pipeline
        """
        if apply_diarization:
            segments = self.run_diarization(audio_path, segments)
            if self._diarization.is_enabled():
                self._meeting_store.update_transcript_speakers(meeting_id, segments)

        self._meeting_store.add_transcript(audio_path, language, segments)
        
        # Use enhanced finalization with speaker naming and status updates.
        # Pass audio_path=None since diarization was already done above.
        self.finalize_meeting_with_diarization(meeting_id, segments, audio_path=None)
        return segments
    
    def transcribe_chunk(
        self,
        audio_path: str,
        offset_seconds: float = 0.0,
    ) -> tuple[list[dict], Optional[str], float]:
        """Transcribe a single audio chunk and format segments.
        
        Used for live transcription where audio arrives in chunks.
        Does NOT apply diarization (not possible until full audio available).
        
        Args:
            audio_path: Path to audio chunk file
            offset_seconds: Time offset to add to segment timestamps
            
        Returns:
            Tuple of (formatted segments, detected language, chunk duration)
        """
        segments_iter, info = self._provider.stream_segments(audio_path)
        language = getattr(info, "language", None)
        
        # #region agent log
        import json as _json
        import time as _time
        import soundfile as _sf
        _DEBUG_LOG_PATH = os.path.join(os.getcwd(), "logs", "debug.log")
        try:
            with _sf.SoundFile(audio_path) as f:
                actual_audio_duration = f.frames / f.samplerate
        except:
            actual_audio_duration = -1
        raw_segments = []
        # #endregion
        
        segments: list[dict] = []
        max_end = 0.0
        for segment in segments_iter:
            seg_end = float(segment.end)
            if seg_end > max_end:
                max_end = seg_end
            # #region agent log
            raw_segments.append({"raw_start": float(segment.start), "raw_end": seg_end})
            # #endregion
            segments.append({
                "type": "segment",
                "start": float(segment.start) + offset_seconds,
                "end": seg_end + offset_seconds,
                "text": segment.text.strip(),
                "speaker": None,
            })
        
        # #region agent log
        first_raw_start = raw_segments[0]["raw_start"] if raw_segments else None
        last_raw_end = raw_segments[-1]["raw_end"] if raw_segments else None
        try:
            with open(_DEBUG_LOG_PATH, "a") as f:
                f.write(_json.dumps({
                    "location": "transcription_pipeline.py:transcribe_chunk",
                    "message": "whisper_raw_output",
                    "data": {
                        "audio_path": audio_path,
                        "offset_seconds": offset_seconds,
                        "actual_audio_duration": actual_audio_duration,
                        "max_end_from_whisper": max_end,
                        "num_raw_segments": len(raw_segments),
                        "first_raw_start": first_raw_start,
                        "last_raw_end": last_raw_end,
                        "gap_at_start": first_raw_start if first_raw_start is not None else None,
                        "gap_at_end": actual_audio_duration - max_end if actual_audio_duration > 0 else None,
                    },
                    "timestamp": _time.time() * 1000,
                    "runId": "gaps-debug",
                    "hypothesisId": "H3-H4"
                }) + "\n")
        except: pass
        # #endregion
        
        return segments, language, max_end

    def finalize_meeting(
        self,
        meeting_id: str,
        segments: list[dict],
    ) -> Optional[dict]:
        """Finalize a meeting after transcription: summarize and auto-title.
        
        Args:
            meeting_id: Meeting ID to finalize
            segments: Transcript segments for summarization
            
        Returns:
            Summary result dict or None if summarization failed
        """
        # #region agent log
        try:
            dbg(
                self._logger,
                location="transcription_pipeline.py:finalize_meeting",
                message="finalize_meeting_enter",
                data={"meeting_id": meeting_id, "segments_count": len(segments) if segments else 0},
                run_id="bugs-debug",
                hypothesis_id="H1a_H2a",
            )
        except Exception:
            pass
        # #endregion
        
        # Update status to completed
        self._meeting_store.update_status(meeting_id, "completed")
        
        # Get user notes for inclusion in summary
        meeting = self._meeting_store.get_meeting(meeting_id)
        user_notes = meeting.get("user_notes", []) if meeting else []
        
        # Generate summary from transcript text
        summary_text = "\n".join(
            segment.get("text", "")
            for segment in segments
            if isinstance(segment, dict)
        )
        
        if not summary_text.strip():
            self._logger.info("Finalize skipped (no text): meeting_id=%s", meeting_id)
            # #region agent log
            try:
                dbg(
                    self._logger,
                    location="transcription_pipeline.py:finalize_meeting",
                    message="finalize_meeting_skip_empty",
                    data={"meeting_id": meeting_id},
                    run_id="bugs-debug",
                    hypothesis_id="H2a",
                )
            except Exception:
                pass
            # #endregion
            return None
        
        try:
            self._logger.info(
                "Finalize summary start: meeting_id=%s segments=%s",
                meeting_id,
                len(segments),
            )
            # #region agent log
            try:
                dbg(
                    self._logger,
                    location="transcription_pipeline.py:finalize_meeting",
                    message="finalize_summarize_start",
                    data={"meeting_id": meeting_id, "summary_text_len": len(summary_text)},
                    run_id="bugs-debug",
                    hypothesis_id="H2b",
                )
            except Exception:
                pass
            # #endregion
            result = self._summarization.summarize(summary_text, user_notes=user_notes)
            # #region agent log
            try:
                dbg(
                    self._logger,
                    location="transcription_pipeline.py:finalize_meeting",
                    message="finalize_summarize_done",
                    data={
                        "meeting_id": meeting_id,
                        "has_result": result is not None,
                        "summary_len": len(result.get("summary", "")) if result else 0,
                        "action_items_count": len(result.get("action_items", [])) if result else 0,
                    },
                    run_id="bugs-debug",
                    hypothesis_id="H2b",
                )
            except Exception:
                pass
            # #endregion
            
            self._meeting_store.add_summary(
                meeting_id,
                summary=result.get("summary", ""),
                action_items=result.get("action_items", []),
                provider="default",
            )
            
            # #region agent log
            try:
                dbg(
                    self._logger,
                    location="transcription_pipeline.py:finalize_meeting",
                    message="finalize_auto_title_start",
                    data={"meeting_id": meeting_id, "summary_for_title_len": len(result.get("summary", ""))},
                    run_id="bugs-debug",
                    hypothesis_id="H1b",
                )
            except Exception:
                pass
            # #endregion
            self._meeting_store.maybe_auto_title(
                meeting_id,
                result.get("summary", ""),
                self._summarization,
                force=True,
            )
            # #region agent log
            try:
                dbg(
                    self._logger,
                    location="transcription_pipeline.py:finalize_meeting",
                    message="finalize_auto_title_done",
                    data={"meeting_id": meeting_id},
                    run_id="bugs-debug",
                    hypothesis_id="H1b",
                )
            except Exception:
                pass
            # #endregion
            
            self._logger.info("Finalize complete: meeting_id=%s", meeting_id)
            return result
            
        except Exception as exc:
            self._logger.warning("Finalize summary failed: meeting_id=%s error=%s", meeting_id, exc)
            # #region agent log
            try:
                import traceback
                dbg(
                    self._logger,
                    location="transcription_pipeline.py:finalize_meeting",
                    message="finalize_meeting_error",
                    data={
                        "meeting_id": meeting_id,
                        "exc_type": type(exc).__name__,
                        "exc_str": str(exc)[:500],
                        "traceback": traceback.format_exc()[-1500:],
                    },
                    run_id="bugs-debug",
                    hypothesis_id="H2b",
                )
            except Exception:
                pass
            # #endregion
            return None

    def finalize_meeting_with_diarization(
        self,
        meeting_id: str,
        segments: list[dict],
        audio_path: Optional[str] = None,
    ) -> Optional[dict]:
        """Finalize a meeting with full diarization pipeline.
        
        Enhanced finalization flow:
        1. Publish status: "Analyzing speakers..."
        2. Run batch diarization on the full audio
        3. Apply speaker labels to transcript
        4. Publish status: "Identifying speaker names..."
        5. Use LLM to identify speaker names (if available)
        6. Update attendee names
        7. Publish status: "Generating summary..."
        8. Run summarization
        9. Generate auto-title
        10. Publish status: "Complete"
        
        Args:
            meeting_id: Meeting ID to finalize
            segments: Transcript segments
            audio_path: Path to the audio file for diarization
            
        Returns:
            Summary result dict or None if failed
        """
        # #region agent log
        _log_path = os.path.join(os.getcwd(), "logs", "debug.log")
        import json as _json_fin
        import time as _time_fin
        def _dbg_fin(msg, data=None):
            try:
                with open(_log_path, "a") as _f:
                    _f.write(_json_fin.dumps({"location":"pipeline:finalize_meeting_with_diarization","message":msg,"data":data or {},"timestamp":int(_time_fin.time()*1000),"hypothesisId":"H_DIARIZE"})+"\n")
            except Exception:
                pass
        # Get audio file info for debugging
        _audio_format = None
        _audio_size = None
        if audio_path and os.path.exists(audio_path):
            try:
                _audio_info = sf.info(audio_path)
                _audio_format = _audio_info.format
                _audio_size = os.path.getsize(audio_path)
            except Exception:
                pass
        _dbg_fin("finalize_entry", {
            "meeting_id": meeting_id,
            "segments_count": len(segments) if segments else 0,
            "audio_path": audio_path,
            "audio_format": _audio_format,
            "audio_size_bytes": _audio_size,
            "is_wav": audio_path.endswith(".wav") if audio_path else None,
        })
        # #endregion
        
        try:
            self._logger.info(
                "finalize_meeting_with_diarization: meeting_id=%s segments=%d audio_path=%s",
                meeting_id,
                len(segments) if segments else 0,
                audio_path,
            )
            
            # #region agent log
            _DBG_PATH = "/Users/chee/zapier ai project/.cursor/debug.log"
            import json as _jfin, time as _tfin
            def _dbg_step(step, data=None):
                try:
                    with open(_DBG_PATH, "a") as _ff:
                        _ff.write(_jfin.dumps({"location":"pipeline:finalize","message":step,"data":data or {},"timestamp":int(_tfin.time()*1000),"hypothesisId":"FIN"})+"\n")
                except: pass
            _dbg_step("ENTER", {"meeting_id": meeting_id, "segments": len(segments) if segments else 0, "audio_path": audio_path})
            # #endregion
            
            # Guard against double finalization
            meeting = self._meeting_store.get_meeting(meeting_id)
            if meeting:
                current_status = meeting.get("status")
                if current_status == "completed":
                    self._logger.warning(
                        "finalize_meeting_with_diarization: skipping - already completed: meeting_id=%s",
                        meeting_id,
                    )
                    _dbg_fin("finalize_skipped_already_complete", {"meeting_id": meeting_id, "status": current_status})
                    return meeting.get("summary")
                if current_status == "processing":
                    self._logger.warning(
                        "finalize_meeting_with_diarization: skipping - already processing: meeting_id=%s",
                        meeting_id,
                    )
                    _dbg_fin("finalize_skipped_already_processing", {"meeting_id": meeting_id, "status": current_status})
                    return None
            
            # Update status to processing
            self._meeting_store.update_status(meeting_id, "processing")
            
            # Step 1-3: Run batch diarization if enabled and audio available
            diarization_segments = []
            # #region agent log
            import json as _json
            import time as _time
            _DEBUG_LOG_PATH = "/Users/chee/zapier ai project/.cursor/debug.log"
            try:
                with open(_DEBUG_LOG_PATH, "a") as f:
                    f.write(_json.dumps({
                        "location": "transcription_pipeline.py:finalize",
                        "message": "batch_diarization_check",
                        "data": {
                            "meeting_id": meeting_id,
                            "has_audio_path": bool(audio_path),
                            "audio_path": audio_path[:100] if audio_path else None,
                            "diarization_enabled": self._diarization.is_enabled(),
                            "will_run": bool(audio_path and self._diarization.is_enabled()),
                        },
                        "timestamp": _time.time() * 1000,
                        "runId": "batch-diar-debug",
                        "hypothesisId": "H3"
                    }) + "\n")
            except: pass
            # #endregion
            if audio_path and self._diarization.is_enabled():
                self._meeting_store.publish_finalization_status(
                    meeting_id, "Analyzing speakers...", 0.1
                )
                _dbg_step("DIARIZATION_START", {"meeting_id": meeting_id})
                try:
                    diarization_segments = self._diarization.run(audio_path)
                    self._logger.info(
                        "Diarization complete: meeting_id=%s segments=%d",
                        meeting_id,
                        len(diarization_segments),
                    )
                    # #region agent log
                    try:
                        with open(_DEBUG_LOG_PATH, "a") as f:
                            f.write(_json.dumps({
                                "location": "transcription_pipeline.py:finalize",
                                "message": "batch_diarization_complete",
                                "data": {
                                    "meeting_id": meeting_id,
                                    "segments_count": len(diarization_segments),
                                    "unique_speakers": list(set(s.get("speaker") for s in diarization_segments if s.get("speaker"))),
                                },
                                "timestamp": _time.time() * 1000,
                                "runId": "batch-diar-debug",
                                "hypothesisId": "H3"
                            }) + "\n")
                    except: pass
                    # #endregion
                    
                    # Apply speaker labels to transcript
                    if diarization_segments:
                        segments = apply_diarization(segments, diarization_segments)
                        # Update transcript speakers in meeting store
                        self._meeting_store.update_transcript_speakers(meeting_id, segments)
                except Exception as exc:
                    self._logger.warning(
                        "Diarization failed, continuing without: meeting_id=%s error=%s",
                        meeting_id, exc
                    )
                    self._meeting_store.publish_finalization_status(
                        meeting_id,
                        f"Speaker analysis failed: {type(exc).__name__}: {str(exc)[:120]}. Continuing without speaker labels.",
                        0.2,
                    )
                    # #region agent log
                    import traceback
                    try:
                        with open(_DEBUG_LOG_PATH, "a") as f:
                            f.write(_json.dumps({
                                "location": "transcription_pipeline.py:finalize",
                                "message": "batch_diarization_error",
                                "data": {
                                    "meeting_id": meeting_id,
                                    "error": str(exc)[:500],
                                    "traceback": traceback.format_exc()[-1000:],
                                },
                                "timestamp": _time.time() * 1000,
                                "runId": "batch-diar-debug",
                                "hypothesisId": "H3"
                            }) + "\n")
                    except: pass
                    # #endregion
            
            # Step 4-6: Identify speaker names using LLM
            _dbg_step("DIARIZATION_DONE", {"meeting_id": meeting_id, "diar_segments": len(diarization_segments)})
            if diarization_segments:
                self._meeting_store.publish_finalization_status(
                    meeting_id, "Identifying speaker names...", 0.3
                )
                try:
                    self._identify_and_update_speaker_names(meeting_id, segments)
                except Exception as exc:
                    self._logger.warning(
                        "Speaker name identification failed: meeting_id=%s error=%s",
                        meeting_id, exc
                    )
                    self._meeting_store.publish_finalization_status(
                        meeting_id,
                        f"Speaker identification failed: {str(exc)[:100]}. Continuing with generic names.",
                        0.4,
                    )
            
            # Step 7-9: Generate summary with streaming events
            # Backend always generates - frontend subscribes to events if connected
            _dbg_step("SPEAKER_ID_DONE", {"meeting_id": meeting_id})
            self._meeting_store.publish_finalization_status(
                meeting_id, "Generating summary...", 0.6
            )
            
            # Get user notes for inclusion in summary
            meeting = self._meeting_store.get_meeting(meeting_id)
            user_notes = meeting.get("user_notes", []) if meeting else []
            
            summary_text = "\n".join(
                segment.get("text", "")
                for segment in segments
                if isinstance(segment, dict)
            )
            
            result = None
            _dbg_step("SUMMARY_TEXT_READY", {"meeting_id": meeting_id, "summary_text_len": len(summary_text.strip())})
            if summary_text.strip():
                try:
                    # Emit summary_start event for any connected frontends
                    self._meeting_store.publish_event("summary_start", meeting_id)
                    
                    # Use streaming summarization, emitting tokens as they arrive
                    accumulated_summary = ""
                    token_count = 0
                    # #region agent log
                    _log_path = os.path.join(os.getcwd(), "logs", "debug.log")
                    import json as _json
                    import time as _time
                    def _dbg(msg, data=None):
                        with open(_log_path, "a") as _f:
                            _f.write(_json.dumps({"location":"transcription_pipeline.py:finalize","message":msg,"data":data or {},"timestamp":int(_time.time()*1000),"hypothesisId":"STREAM"})+"\n")
                    _dbg("summary_stream_start", {"meeting_id": meeting_id})
                    # #endregion
                    _dbg_step("LLM_SUMMARIZE_STREAM_START", {"meeting_id": meeting_id})
                    for token in self._summarization.summarize_stream(summary_text, user_notes=user_notes):
                        accumulated_summary += token
                        token_count += 1
                        # #region agent log
                        if token_count <= 5 or token_count % 20 == 0:
                            _dbg("summary_token_emit", {"token_num": token_count, "accum_len": len(accumulated_summary)})
                        # #endregion
                        # Emit each token for progressive display
                        self._meeting_store.publish_event(
                            "summary_token",
                            meeting_id,
                            {"text": accumulated_summary}
                        )
                    # #region agent log
                    _dbg("summary_stream_done", {"total_tokens": token_count, "final_len": len(accumulated_summary)})
                    # #endregion
                    
                    # Parse the final result (may be JSON with summary + action_items)
                    final_text = accumulated_summary.strip()
                    
                    # Try to parse as JSON for structured response
                    import json
                    try:
                        parsed = json.loads(final_text)
                        result = {
                            "summary": str(parsed.get("summary", final_text)).strip(),
                            "action_items": parsed.get("action_items", []) or [],
                        }
                    except json.JSONDecodeError:
                        result = {"summary": final_text, "action_items": []}
                    
                    # Emit summary_complete event
                    self._meeting_store.publish_event(
                        "summary_complete",
                        meeting_id,
                        {"text": result.get("summary", "")}
                    )
                    
                    # Save to meeting store
                    self._meeting_store.add_summary(
                        meeting_id,
                        summary=result.get("summary", ""),
                        action_items=result.get("action_items", []),
                        provider="default",
                    )
                    
                    # Auto-generate title
                    _dbg_step("SUMMARY_SAVED", {"meeting_id": meeting_id, "summary_len": len(result.get("summary",""))})
                    self._meeting_store.publish_finalization_status(
                        meeting_id, "Generating title...", 0.9
                    )
                    _dbg_step("TITLE_GEN_START", {"meeting_id": meeting_id})
                    self._meeting_store.maybe_auto_title(
                        meeting_id,
                        result.get("summary", ""),
                        self._summarization,
                        force=True,
                    )
                    _dbg_step("TITLE_GEN_DONE", {"meeting_id": meeting_id})
                except Exception as exc:
                    self._logger.warning(
                        "Summarization failed: meeting_id=%s error=%s",
                        meeting_id, exc
                    )
                    self._meeting_store.publish_finalization_status(
                        meeting_id,
                        f"Summary generation failed: {type(exc).__name__}: {str(exc)[:120]}",
                        0.7,
                    )
                    # #region agent log
                    import traceback as _tb_sum
                    _dbg_step("SUMMARIZATION_ERROR", {"meeting_id": meeting_id, "error": str(exc)[:500], "traceback": _tb_sum.format_exc()[-1000:]})
                    # #endregion
            
            # Step 10: Ensure attendees are created from speaker labels
            # This handles cases where real-time diarization added speakers but batch diarization was skipped
            meeting = self._meeting_store.get_meeting(meeting_id)
            if meeting:
                transcript = meeting.get("transcript", {})
                current_segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
                existing_attendees = meeting.get("attendees", [])
                
                # Check if any segments have speakers but no attendees exist
                has_speakers = any(seg.get("speaker") for seg in current_segments)
                if has_speakers and not existing_attendees:
                    # Create attendees from speaker labels
                    self._meeting_store.update_transcript_speakers(meeting_id, current_segments)
                    self._logger.info(
                        "Created attendees from existing speaker labels: meeting_id=%s",
                        meeting_id
                    )
            
            # Step 11: Complete
            self._meeting_store.update_status(meeting_id, "completed")
            self._meeting_store.publish_event("meeting_updated", meeting_id)
            
            _dbg_step("FINALIZATION_COMPLETE", {"meeting_id": meeting_id})
            self._logger.info("finalize_meeting_with_diarization complete: meeting_id=%s", meeting_id)
            return result
            
        except Exception as exc:
            _dbg_step("FINALIZATION_CRASH", {"meeting_id": meeting_id, "error": str(exc)[:500]})  # #region agent log  # #endregion
            self._logger.exception(
                "finalize_meeting_with_diarization failed: meeting_id=%s error=%s",
                meeting_id, exc
            )
            self._meeting_store.publish_finalization_status(
                meeting_id,
                f"Finalization failed: {type(exc).__name__}: {str(exc)[:120]}",
                0.0,
            )
            # Make sure to mark completed on error
            self._meeting_store.update_status(meeting_id, "completed")
            return None

    def _identify_and_update_speaker_names(
        self,
        meeting_id: str,
        segments: list[dict],
    ) -> None:
        """Use a single LLM call to identify speaker names from transcript.

        Collects all speakers that need identification (skipping manually-named
        ones), then calls identify_all_speakers() for a single batch request.
        """
        # Get unique speakers from segments
        speakers = set()
        for seg in segments:
            speaker = seg.get("speaker")
            if speaker:
                speakers.add(speaker)

        if not speakers:
            return

        # Get current meeting to check existing attendees
        meeting = self._meeting_store.get_meeting(meeting_id)
        if not meeting:
            return

        attendees = meeting.get("attendees", [])
        attendee_map = {a.get("id"): a for a in attendees}

        # Filter to speakers that need identification (skip manual names)
        ids_to_identify = []
        for speaker_id in speakers:
            attendee = attendee_map.get(speaker_id)
            if attendee and attendee.get("name_source") == "manual":
                self._logger.debug(
                    "Skipping speaker %s — manually named as '%s'",
                    speaker_id, attendee.get("name"),
                )
                continue
            ids_to_identify.append(speaker_id)

        if not ids_to_identify:
            self._logger.info("All speakers already have manual names, skipping identification")
            return

        # Single batch LLM call
        try:
            results = self._summarization.identify_all_speakers(
                segments, ids_to_identify
            )
        except Exception as exc:
            self._logger.warning(
                "Batch speaker identification failed: meeting_id=%s error=%s",
                meeting_id, exc,
            )
            return

        # Apply results
        identified_count = 0
        for result in results:
            name = result.get("name")
            if not name:
                self._logger.debug(
                    "Could not identify speaker %s: %s",
                    result.get("speaker_id"), result.get("reasoning", ""),
                )
                continue

            self._meeting_store.update_attendee_name(
                meeting_id,
                result["speaker_id"],
                name,
                source="llm",
                confidence=result.get("confidence", "low"),
            )
            identified_count += 1
            self._logger.info(
                "Identified speaker: %s -> %s (confidence: %s)",
                result["speaker_id"],
                name,
                result.get("confidence", "unknown"),
            )

        self._logger.info(
            "Batch speaker identification complete: %d/%d identified",
            identified_count, len(ids_to_identify),
        )
