"""
Unified transcription pipeline that handles post-processing for all transcription flows.

This service centralizes:
- Segment formatting (whisper output → standard dict format)
- Diarization application (speaker identification)
- Meeting store updates
- Optional auto-title from transcript (no meeting summary)

All transcription endpoints should use this pipeline after obtaining audio.
"""

from __future__ import annotations

import logging
import os
import json
import tempfile
import threading
import time
from typing import TYPE_CHECKING, Iterator, Optional, Union

import numpy as np
import soundfile as sf

from app.services.debug_logging import dbg

_logger = logging.getLogger(__name__)
_dbg_logger = logging.getLogger("notetaker.debug")


if TYPE_CHECKING:
    from app.services.transcription import FasterWhisperProvider
    from app.services.diarization import DiarizationService
    from app.services.meeting_store import MeetingStore
    from app.services.summarization import SummarizationService


def apply_diarization(
    segments: list[dict], diarization_segments: list[dict]
) -> list[dict]:
    """Apply speaker labels to transcript segments based on diarization output.
    
    Matches each segment to a diarization interval by overlap or proximity
    and assigns the corresponding speaker label.
    """
    if not diarization_segments:
        return segments
    
    diarization_segments = sorted(diarization_segments, key=lambda seg: seg["start"])
    
    for segment in segments:
        seg_start = segment.get("start", 0)
        seg_end = segment.get("end", seg_start)
        
        # First try: exact containment (segment start falls within diarization range)
        matched = False
        for diar in diarization_segments:
            if diar["start"] <= seg_start < diar["end"]:
                segment["speaker"] = diar["speaker"]
                matched = True
                break
        
        if matched:
            continue
        
        # Second try: find diarization segment with best overlap
        best_overlap = 0
        best_speaker = None
        for diar in diarization_segments:
            overlap_start = max(seg_start, diar["start"])
            overlap_end = min(seg_end, diar["end"])
            overlap = max(0, overlap_end - overlap_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = diar["speaker"]
        
        if best_speaker:
            segment["speaker"] = best_speaker
            continue
        
        # Third try: assign to nearest diarization segment by time proximity
        min_distance = float("inf")
        nearest_speaker = None
        for diar in diarization_segments:
            # Distance from segment to diarization range
            if seg_end <= diar["start"]:
                distance = diar["start"] - seg_end
            elif seg_start >= diar["end"]:
                distance = seg_start - diar["end"]
            else:
                distance = 0  # overlapping
            if distance < min_distance:
                min_distance = distance
                nearest_speaker = diar["speaker"]
        
        if nearest_speaker:
            segment["speaker"] = nearest_speaker
    
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
            audio_path: Path to audio file (any format - decoded directly to memory)
            cancel_event: Optional threading.Event to check for cancellation
            
        Returns:
            Tuple of (formatted segments, detected language)
        """
        from app.services.audio_utils import load_audio_for_whisper
        
        
        # Load audio directly to memory (avoids temp WAV file for Opus, FLAC, etc.)
        audio_array = load_audio_for_whisper(audio_path)
        segments_iter, info = self._provider.stream_segments(audio_array)
        language = getattr(info, "language", None)
        
        segments: list[dict] = []
        seg_count = 0
        for segment in segments_iter:
            seg_count += 1
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
            audio_path: Path to audio file (any format - decoded directly to memory)
            cancel_event: Optional threading.Event to check for cancellation
            
        Yields:
            Tuples of (segment dict, detected language)
        """
        from app.services.audio_utils import load_audio_for_whisper
        
        # Load audio directly to memory (avoids temp WAV file for Opus, FLAC, etc.)
        audio_array = load_audio_for_whisper(audio_path)
        segments_iter, info = self._provider.stream_segments(audio_array)
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
        audio_source: Union[str, dict],
        segments: list[dict],
    ) -> list[dict]:
        """Apply diarization to segments if enabled.
        
        Args:
            audio_source: File path (str) or pre-loaded pyannote audio dict
            segments: List of transcript segments
            
        Returns:
            Segments with speaker labels applied (if diarization enabled)
        """
        if not self._diarization.is_enabled():
            return segments
        
        try:
            is_path = isinstance(audio_source, str)
            self._logger.info("Diarization start: source=%s",
                              audio_source if is_path else "in_memory")
            if is_path:
                from app.services.audio_utils import load_audio_for_pyannote
                audio_source = load_audio_for_pyannote(audio_source)
            diarization_segments = self._diarization.run(audio_source)
            segments = apply_diarization(segments, diarization_segments)
            speaker_count = len(set(s.get("speaker") for s in segments if s.get("speaker")))
            self._logger.info("Diarization complete: speakers=%s", speaker_count)
        except Exception as exc:
            self._logger.warning("Diarization failed: %s", exc)
        
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
        - Finalizes meeting (status=completed, summary, title) via enhanced pipeline
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
            audio_path: Path to audio chunk file (any format - decoded directly to memory)
            offset_seconds: Time offset to add to segment timestamps
            
        Returns:
            Tuple of (formatted segments, detected language, chunk duration)
        """
        from app.services.audio_utils import load_audio_for_whisper
        
        # Load audio directly to memory (avoids temp WAV file for Opus, FLAC, etc.)
        audio_array = load_audio_for_whisper(audio_path)
        segments_iter, info = self._provider.stream_segments(audio_array)
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
    ) -> None:
        """Finalize a meeting after transcription (no summary)."""
        self._meeting_store.update_status(meeting_id, "completed")
        self._maybe_auto_title_from_transcript(meeting_id, segments)
        self._logger.info("Finalize complete: meeting_id=%s", meeting_id)

    def _maybe_auto_title_from_transcript(
        self, meeting_id: str, segments: list[dict]
    ) -> None:
        """Generate meeting title from transcript via LLM (best-effort)."""
        transcript_text = "\n".join(
            segment.get("text", "")
            for segment in segments
            if isinstance(segment, dict)
        )
        if not transcript_text.strip():
            return
        try:
            self._meeting_store.maybe_auto_title(
                meeting_id,
                transcript_text[:4000],
                self._summarization,
            )
        except Exception as exc:
            self._logger.warning(
                "Auto title failed (non-fatal): meeting_id=%s error=%s",
                meeting_id,
                exc,
            )

    def finalize_meeting_with_diarization(
        self,
        meeting_id: str,
        segments: list[dict],
        audio_path: Optional[str] = None,
    ) -> Optional[dict]:
        """Enqueue remaining finalization stages (BackgroundFinalizer is the single auto path)."""
        from app.services.background_finalizer import get_background_finalizer

        _ = segments, audio_path
        self._logger.info(
            "finalize_meeting_with_diarization: enqueue meeting_id=%s",
            meeting_id,
        )
        finalizer = get_background_finalizer()
        if finalizer:
            finalizer.enqueue(meeting_id, reason="pipeline_finalize")
        else:
            self._logger.warning(
                "finalize_meeting_with_diarization: no finalizer; meeting %s not enqueued",
                meeting_id,
            )
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

        # Emit input to status log
        transcript_sample = []
        for seg in segments[:20]:  # First 20 segments for preview
            if seg.get("speaker") in ids_to_identify:
                transcript_sample.append({
                    "speaker": seg.get("speaker"),
                    "text": seg.get("text", "")[:100],
                })
        self._meeting_store.publish_status_log(
            meeting_id, "speaker_names", "input",
            {
                "speakers_to_identify": ids_to_identify,
                "transcript_sample": transcript_sample,
            }
        )

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

        # Emit output to status log
        self._meeting_store.publish_status_log(
            meeting_id, "speaker_names", "output",
            {"results": results}
        )

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
