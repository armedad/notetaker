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
from typing import TYPE_CHECKING, Callable, Iterator, Optional

import numpy as np
import soundfile as sf

from app.services.debug_logging import dbg

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

    def chunked_transcribe_and_format(
        self,
        audio_path: str,
        cancel_event: Optional[threading.Event] = None,
        on_chunk_ingested: Optional[Callable[[int, float], None]] = None,
        on_chunk_audio: Optional[Callable[[bytes, int, int, float], None]] = None,
    ) -> Iterator[tuple[dict, Optional[str], bool]]:
        """Transcribe file in chunks with cancellation between chunks.
        
        This method reads the audio file in chunks matching the model's optimal
        chunk size. Cancellation is checked BEFORE each chunk is transcribed,
        allowing for responsive stop behavior:
        
        1. When cancel_event is set, no more audio is ingested
        2. The current chunk being transcribed will complete
        3. Any subsequent chunks will be skipped
        
        Args:
            audio_path: Path to audio file
            cancel_event: Optional threading.Event to check for cancellation
            on_chunk_ingested: Callback(chunk_num, offset_seconds) when chunk is read
            
        Yields:
            Tuples of (segment dict, detected language, was_cancelled)
            The was_cancelled flag is True only on the final yield if cancelled
        """
        import time
        chunk_seconds = self.get_chunk_size()
        
        # Read audio file info
        try:
            info = sf.info(audio_path)
            samplerate = info.samplerate
            channels = info.channels
            total_frames = info.frames
            total_duration = info.duration
        except Exception as exc:
            self._logger.error("Failed to read audio file: %s", exc)
            return
        
        chunk_frames = int(samplerate * chunk_seconds)
        offset_frames = 0
        chunk_num = 0
        language = None
        was_cancelled = False
        
        self._logger.info(
            "Chunked transcription start: audio=%s duration=%.1fs chunk_size=%.1fs",
            audio_path,
            total_duration,
            chunk_seconds,
        )
        
        while offset_frames < total_frames:
            # Check for cancellation BEFORE reading next chunk
            if cancel_event and cancel_event.is_set():
                cancel_detected_time = time.perf_counter()
                self._logger.info(
                    "TIMING: Cancel detected before chunk %d (offset=%.1fs) - stop will complete now",
                    chunk_num,
                    offset_frames / samplerate,
                )
                was_cancelled = True
                break
            
            # Calculate chunk bounds
            end_frames = min(offset_frames + chunk_frames, total_frames)
            frames_to_read = end_frames - offset_frames
            offset_seconds = offset_frames / samplerate
            
            # Read chunk from file
            try:
                audio_data, _ = sf.read(
                    audio_path,
                    start=offset_frames,
                    stop=end_frames,
                    dtype='int16',
                )
            except Exception as exc:
                self._logger.error("Failed to read audio chunk: %s", exc)
                break
            
            # Notify that chunk has been ingested
            if on_chunk_ingested:
                on_chunk_ingested(chunk_num, offset_seconds)
            
            # Write chunk to temp file for transcription
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    temp_path = tmp.name
                
                with sf.SoundFile(
                    temp_path,
                    mode="w",
                    samplerate=samplerate,
                    channels=channels,
                    subtype="PCM_16",
                ) as f:
                    f.write(audio_data)
                
                # Transcribe the chunk with timing instrumentation
                chunk_start_time = time.perf_counter()
                self._logger.info(
                    "TIMING: Chunk %d transcription START (audio offset=%.1fs, audio_duration=%.1fs)",
                    chunk_num,
                    offset_seconds,
                    frames_to_read / samplerate,
                )
                
                segments, chunk_lang, chunk_duration = self.transcribe_chunk(
                    temp_path,
                    offset_seconds,
                )
                
                chunk_elapsed = time.perf_counter() - chunk_start_time
                self._logger.info(
                    "TIMING: Chunk %d transcription END (took %.2fs for %.1fs audio, ratio=%.2fx)",
                    chunk_num,
                    chunk_elapsed,
                    frames_to_read / samplerate,
                    chunk_elapsed / (frames_to_read / samplerate) if frames_to_read > 0 else 0,
                )
                
                if chunk_lang and not language:
                    language = chunk_lang

                # Optional hook: provide raw chunk audio bytes for downstream (e.g. real-time diarization).
                if on_chunk_audio:
                    try:
                        on_chunk_audio(audio_data.tobytes(), samplerate, channels, offset_seconds)
                    except Exception:
                        pass
                
                # Yield segments from this chunk
                for segment in segments:
                    yield segment, language, False
                    
            except Exception as exc:
                self._logger.warning("Chunk %d transcription error: %s", chunk_num, exc)
            finally:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
            
            offset_frames = end_frames
            chunk_num += 1
        
        # Final yield to signal completion status
        if was_cancelled:
            # Yield a marker that transcription was cancelled
            self._logger.info(
                "Chunked transcription cancelled: processed %d chunks",
                chunk_num,
            )
        else:
            self._logger.info(
                "Chunked transcription complete: %d chunks",
                chunk_num,
            )
    
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
        
        This is the convergence point for live vs simulated flows once audio is obtained.
        
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
        
        segments: list[dict] = []
        max_end = 0.0
        for segment in segments_iter:
            seg_end = float(segment.end)
            if seg_end > max_end:
                max_end = seg_end
            segments.append({
                "type": "segment",
                "start": float(segment.start) + offset_seconds,
                "end": seg_end + offset_seconds,
                "text": segment.text.strip(),
                "speaker": None,
            })
        
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
            result = self._summarization.summarize(summary_text)
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
        try:
            self._logger.info(
                "finalize_meeting_with_diarization: meeting_id=%s segments=%d audio_path=%s",
                meeting_id,
                len(segments) if segments else 0,
                audio_path,
            )
            
            # Update status to processing
            self._meeting_store.update_status(meeting_id, "processing")
            
            # Step 1-3: Run batch diarization if enabled and audio available
            diarization_segments = []
            if audio_path and self._diarization.is_enabled():
                self._meeting_store.publish_finalization_status(
                    meeting_id, "Analyzing speakers...", 0.1
                )
                try:
                    diarization_segments = self._diarization.run(audio_path)
                    self._logger.info(
                        "Diarization complete: meeting_id=%s segments=%d",
                        meeting_id,
                        len(diarization_segments),
                    )
                    
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
            
            # Step 4-6: Identify speaker names using LLM
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
            
            # Step 7-9: Generate summary
            self._meeting_store.publish_finalization_status(
                meeting_id, "Generating summary...", 0.6
            )
            
            summary_text = "\n".join(
                segment.get("text", "")
                for segment in segments
                if isinstance(segment, dict)
            )
            
            result = None
            if summary_text.strip():
                try:
                    result = self._summarization.summarize(summary_text)
                    self._meeting_store.add_summary(
                        meeting_id,
                        summary=result.get("summary", ""),
                        action_items=result.get("action_items", []),
                        provider="default",
                    )
                    
                    # Auto-generate title
                    self._meeting_store.publish_finalization_status(
                        meeting_id, "Generating title...", 0.9
                    )
                    self._meeting_store.maybe_auto_title(
                        meeting_id,
                        result.get("summary", ""),
                        self._summarization,
                        force=True,
                    )
                except Exception as exc:
                    self._logger.warning(
                        "Summarization failed: meeting_id=%s error=%s",
                        meeting_id, exc
                    )
            
            # Step 10: Complete
            self._meeting_store.update_status(meeting_id, "completed")
            self._meeting_store.clear_finalization_status(meeting_id)
            self._meeting_store.publish_event("meeting_updated", meeting_id)
            
            self._logger.info("finalize_meeting_with_diarization complete: meeting_id=%s", meeting_id)
            return result
            
        except Exception as exc:
            self._logger.exception(
                "finalize_meeting_with_diarization failed: meeting_id=%s error=%s",
                meeting_id, exc
            )
            # Make sure to clear status on error
            self._meeting_store.update_status(meeting_id, "completed")
            self._meeting_store.clear_finalization_status(meeting_id)
            return None

    def _identify_and_update_speaker_names(
        self,
        meeting_id: str,
        segments: list[dict],
    ) -> None:
        """Use LLM to identify speaker names from transcript.
        
        For each unique speaker label (e.g., "SPEAKER_00"), extract their
        dialogue and ask the LLM if it can identify who they are.
        """
        # Get unique speakers
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
        
        # For each speaker, try to identify their name
        for speaker_id in speakers:
            # Skip if already has a human-assigned name
            attendee = attendee_map.get(speaker_id)
            if attendee and attendee.get("name_source") == "manual":
                continue
            
            # Get segments for this speaker
            speaker_segments = [
                seg for seg in segments
                if seg.get("speaker") == speaker_id
            ]
            
            if not speaker_segments:
                continue
            
            # Try to identify the speaker
            try:
                result = self._summarization.identify_speaker_name(
                    speaker_id, speaker_segments
                )
                
                if result and result.get("name"):
                    # Update or create attendee
                    self._meeting_store.update_attendee_name(
                        meeting_id,
                        speaker_id,
                        result["name"],
                        source="llm",
                        confidence=result.get("confidence", "low"),
                    )
                    self._logger.info(
                        "Identified speaker: %s -> %s (confidence: %s)",
                        speaker_id,
                        result["name"],
                        result.get("confidence", "unknown"),
                    )
            except Exception as exc:
                self._logger.warning(
                    "Failed to identify speaker %s: %s",
                    speaker_id, exc
                )
