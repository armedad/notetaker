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
from typing import TYPE_CHECKING, Optional

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
    
    def transcribe_and_format(
        self,
        audio_path: str,
    ) -> tuple[list[dict], Optional[str]]:
        """Transcribe audio and format segments to standard dict format.
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            Tuple of (formatted segments, detected language)
        """
        segments_iter, info = self._provider.stream_segments(audio_path)
        language = getattr(info, "language", None)
        
        segments: list[dict] = []
        for segment in segments_iter:
            segments.append({
                "type": "segment",
                "start": float(segment.start),
                "end": float(segment.end),
                "text": segment.text.strip(),
                "speaker": None,
            })
        
        return segments, language
    
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
            diarization_segments = self._diarization.run(audio_path)
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
            return None
        
        try:
            self._logger.info(
                "Finalize summary start: meeting_id=%s segments=%s",
                meeting_id,
                len(segments),
            )
            result = self._summarization.summarize(summary_text)
            
            self._meeting_store.add_summary(
                meeting_id,
                summary=result.get("summary", ""),
                action_items=result.get("action_items", []),
                provider="default",
            )
            
            self._meeting_store.maybe_auto_title(
                meeting_id,
                result.get("summary", ""),
                self._summarization,
                force=True,
            )
            
            self._logger.info("Finalize complete: meeting_id=%s", meeting_id)
            return result
            
        except Exception as exc:
            self._logger.warning("Finalize summary failed: meeting_id=%s error=%s", meeting_id, exc)
            return None
