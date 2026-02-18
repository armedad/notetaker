"""
Background finalizer service that processes meetings with incomplete finalization.

This service runs as a daemon thread and periodically sweeps through meetings
that need finalization (e.g., after server restart). It processes one meeting
at a time to avoid CPU overload.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.services.meeting_store import MeetingStore
    from app.services.summarization import SummarizationService
    from app.services.diarization import DiarizationService

_logger = logging.getLogger(__name__)


class BackgroundFinalizer:
    """Background service that finalizes meetings with incomplete stages.
    
    Runs a sweep loop that:
    - Finds meetings needing finalization
    - Processes one meeting at a time
    - Waits between meetings to avoid CPU overload
    """
    
    def __init__(
        self,
        meeting_store: "MeetingStore",
        summarization_service: "SummarizationService",
        diarization_service: "DiarizationService",
        *,
        delay_between_meetings: float = 30.0,
        idle_check_interval: float = 300.0,
    ) -> None:
        """Initialize the background finalizer.
        
        Args:
            meeting_store: Meeting store instance
            summarization_service: Summarization service for summary/title generation
            diarization_service: Diarization service for speaker analysis
            delay_between_meetings: Seconds to wait between finalizing meetings
            idle_check_interval: Seconds to wait before checking again when no work
        """
        self._meeting_store = meeting_store
        self._summarization = summarization_service
        self._diarization = diarization_service
        self._delay_between_meetings = delay_between_meetings
        self._idle_check_interval = idle_check_interval
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
    
    def start(self) -> None:
        """Start the background finalizer thread."""
        if self._running:
            _logger.warning("BackgroundFinalizer already running")
            return
        
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._sweep_loop,
            name="BackgroundFinalizer",
            daemon=True,
        )
        self._thread.start()
        _logger.info("BackgroundFinalizer started")
    
    def stop(self) -> None:
        """Stop the background finalizer thread."""
        if not self._running:
            return
        
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        _logger.info("BackgroundFinalizer stopped")
    
    def _sweep_loop(self) -> None:
        """Main loop that sweeps for and processes incomplete meetings."""
        _logger.info("BackgroundFinalizer sweep loop started")
        
        # Initial delay to let the server fully start
        self._stop_event.wait(10.0)
        
        while not self._stop_event.is_set():
            try:
                meeting = self._find_next_incomplete()
                if meeting:
                    meeting_id = meeting.get("id")
                    _logger.info(
                        "BackgroundFinalizer processing meeting: %s",
                        meeting_id,
                    )
                    self._finalize_meeting(meeting)
                    _logger.info(
                        "BackgroundFinalizer completed meeting: %s",
                        meeting_id,
                    )
                    # Wait before processing next meeting
                    self._stop_event.wait(self._delay_between_meetings)
                else:
                    # No meetings need finalization, wait and check again
                    _logger.debug(
                        "BackgroundFinalizer: no meetings need finalization, "
                        "sleeping %ds",
                        self._idle_check_interval,
                    )
                    self._stop_event.wait(self._idle_check_interval)
            except Exception as exc:
                _logger.exception(
                    "BackgroundFinalizer sweep loop error: %s",
                    exc,
                )
                # Wait before retrying on error
                self._stop_event.wait(60.0)
    
    def _find_next_incomplete(self) -> Optional[dict]:
        """Find the oldest meeting that needs finalization.
        
        Returns:
            Meeting dict or None if no meetings need finalization
        """
        try:
            meetings = self._meeting_store.list_meetings_needing_finalization()
            if meetings:
                return meetings[0]  # Oldest first
        except Exception as exc:
            _logger.warning(
                "BackgroundFinalizer: error finding incomplete meetings: %s",
                exc,
            )
        return None
    
    def _finalize_meeting(self, meeting: dict) -> None:
        """Run finalization for a single meeting.
        
        Only runs stages that are pending (skips completed and failed stages).
        
        Args:
            meeting: Meeting dict to finalize
        """
        from app.services.transcription_pipeline import apply_diarization
        from app.services.meeting_store import MeetingStore
        
        meeting_id = meeting.get("id")
        if not meeting_id:
            return
        
        audio_path = meeting.get("audio_path")
        finalization = meeting.get("finalization", {})
        # Migrate old format if needed
        finalization = self._meeting_store._migrate_finalization_state(finalization)
        
        # Get transcript segments
        transcript = meeting.get("transcript", {})
        segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
        
        # Check which stages need to run (only pending, not failed)
        needs_diarization = finalization.get("diarization") == MeetingStore.FINALIZATION_PENDING
        needs_speaker_names = finalization.get("speaker_names") == MeetingStore.FINALIZATION_PENDING
        needs_summary = finalization.get("summary") == MeetingStore.FINALIZATION_PENDING
        needs_title = finalization.get("title") == MeetingStore.FINALIZATION_PENDING
        
        pending_stages = self._meeting_store.get_pending_finalization_stages(meeting)
        failed_stages = self._meeting_store.get_failed_finalization_stages(meeting)
        _logger.info(
            "BackgroundFinalizer: meeting %s - pending: %s, failed: %s",
            meeting_id,
            pending_stages,
            failed_stages,
        )
        
        try:
            # Stage 1: Diarization
            diarization_segments = []
            if needs_diarization and audio_path and self._diarization.is_enabled():
                self._meeting_store.publish_finalization_status(
                    meeting_id, "Analyzing speakers...", 0.1
                )
                try:
                    diarization_segments = self._diarization.run(audio_path)
                    if diarization_segments:
                        segments = apply_diarization(segments, diarization_segments)
                        self._meeting_store.update_transcript_speakers(meeting_id, segments)
                    self._meeting_store.mark_finalization_stage(meeting_id, "diarization")
                    _logger.info(
                        "BackgroundFinalizer: diarization complete for %s (%d segments)",
                        meeting_id, len(diarization_segments),
                    )
                except Exception as exc:
                    _logger.warning(
                        "BackgroundFinalizer: diarization failed for %s: %s",
                        meeting_id, exc,
                    )
                    # Mark as failed so it won't be retried
                    self._meeting_store.mark_finalization_stage_failed(meeting_id, "diarization")
            elif needs_diarization:
                # No audio or diarization disabled, mark as done
                self._meeting_store.mark_finalization_stage(meeting_id, "diarization")
            
            # Stage 2: Speaker name identification
            if needs_speaker_names and diarization_segments:
                self._meeting_store.publish_finalization_status(
                    meeting_id, "Identifying speaker names...", 0.3
                )
                try:
                    self._identify_speaker_names(meeting_id, segments)
                    self._meeting_store.mark_finalization_stage(meeting_id, "speaker_names")
                except Exception as exc:
                    _logger.warning(
                        "BackgroundFinalizer: speaker identification failed for %s: %s",
                        meeting_id, exc,
                    )
                    self._meeting_store.mark_finalization_stage_failed(meeting_id, "speaker_names")
            elif needs_speaker_names:
                # No diarization segments to identify, mark as done
                self._meeting_store.mark_finalization_stage(meeting_id, "speaker_names")
            
            # Stage 3: Summary generation
            if needs_summary:
                self._meeting_store.publish_finalization_status(
                    meeting_id, "Generating summary...", 0.6
                )
                # Refresh meeting to get latest segments
                meeting = self._meeting_store.get_meeting(meeting_id)
                if meeting:
                    transcript = meeting.get("transcript", {})
                    segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
                    user_notes = meeting.get("user_notes", [])
                    
                    summary_text = "\n".join(
                        seg.get("text", "") for seg in segments if isinstance(seg, dict)
                    )
                    
                    if summary_text.strip():
                        try:
                            # Use streaming summarization
                            accumulated_summary = ""
                            for token in self._summarization.summarize_stream(summary_text, user_notes=user_notes):
                                accumulated_summary += token
                                self._meeting_store.publish_event(
                                    "summary_token", meeting_id, {"text": accumulated_summary}
                                )
                            
                            # Parse result
                            import json
                            final_text = accumulated_summary.strip()
                            try:
                                parsed = json.loads(final_text)
                                result = {
                                    "summary": str(parsed.get("summary", final_text)).strip(),
                                    "action_items": parsed.get("action_items", []) or [],
                                }
                            except json.JSONDecodeError:
                                result = {"summary": final_text, "action_items": []}
                            
                            # Save summary
                            self._meeting_store.add_summary(
                                meeting_id,
                                summary=result.get("summary", ""),
                                action_items=result.get("action_items", []),
                                provider="default",
                            )
                            self._meeting_store.publish_event(
                                "summary_complete", meeting_id, {"text": result.get("summary", "")}
                            )
                            self._meeting_store.mark_finalization_stage(meeting_id, "summary")
                            _logger.info(
                                "BackgroundFinalizer: summary generated for %s",
                                meeting_id,
                            )
                        except Exception as exc:
                            _logger.warning(
                                "BackgroundFinalizer: summary generation failed for %s: %s",
                                meeting_id, exc,
                            )
                            self._meeting_store.mark_finalization_stage_failed(meeting_id, "summary")
                    else:
                        # No transcript text, mark as complete (nothing to summarize)
                        self._meeting_store.mark_finalization_stage(meeting_id, "summary")
            
            # Stage 4: Title generation
            if needs_title:
                self._meeting_store.publish_finalization_status(
                    meeting_id, "Generating title...", 0.9
                )
                meeting = self._meeting_store.get_meeting(meeting_id)
                if meeting:
                    summary = meeting.get("summary", {})
                    summary_text = summary.get("text", "") if isinstance(summary, dict) else ""
                    if summary_text:
                        try:
                            self._meeting_store.maybe_auto_title(
                                meeting_id,
                                summary_text,
                                self._summarization,
                                force=True,
                            )
                            self._meeting_store.mark_finalization_stage(meeting_id, "title")
                            _logger.info(
                                "BackgroundFinalizer: title generated for %s",
                                meeting_id,
                            )
                        except Exception as exc:
                            _logger.warning(
                                "BackgroundFinalizer: title generation failed for %s: %s",
                                meeting_id, exc,
                            )
                            self._meeting_store.mark_finalization_stage_failed(meeting_id, "title")
                    else:
                        # No summary text, mark as complete (can't generate title without summary)
                        self._meeting_store.mark_finalization_stage(meeting_id, "title")
            
            # Mark meeting as completed if it wasn't already
            meeting = self._meeting_store.get_meeting(meeting_id)
            if meeting and meeting.get("status") != "completed":
                self._meeting_store.update_status(meeting_id, "completed")
            
            self._meeting_store.publish_event("meeting_updated", meeting_id)
            
        except Exception as exc:
            _logger.exception(
                "BackgroundFinalizer: finalization failed for %s: %s",
                meeting_id,
                exc,
            )
    
    def _identify_speaker_names(self, meeting_id: str, segments: list[dict]) -> None:
        """Use LLM to identify speaker names from transcript context.
        
        Args:
            meeting_id: Meeting ID
            segments: Transcript segments with speaker labels
        """
        # Get unique speakers
        speakers = set()
        for seg in segments:
            speaker = seg.get("speaker")
            if speaker:
                speakers.add(speaker)
        
        if not speakers:
            return
        
        # Get current meeting
        meeting = self._meeting_store.get_meeting(meeting_id)
        if not meeting:
            return
        
        attendees = meeting.get("attendees", [])
        attendee_map = {a.get("id"): a for a in attendees}
        
        # Filter to speakers that need identification
        ids_to_identify = []
        for speaker_id in speakers:
            attendee = attendee_map.get(speaker_id)
            if attendee and attendee.get("name_source") == "manual":
                continue  # Skip manually named
            ids_to_identify.append(speaker_id)
        
        if not ids_to_identify:
            return
        
        # Batch LLM call
        try:
            name_map = self._summarization.identify_all_speakers(
                ids_to_identify, segments
            )
            for speaker_id, (name, confidence) in name_map.items():
                self._meeting_store.update_attendee_name(
                    meeting_id,
                    speaker_id,
                    name,
                    source="llm",
                    confidence=confidence,
                )
        except Exception as exc:
            _logger.warning(
                "BackgroundFinalizer: speaker name identification failed: %s", exc
            )
