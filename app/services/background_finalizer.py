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

from app.services.active_meeting_tracker import get_tracker, MeetingState

if TYPE_CHECKING:
    from app.services.meeting_store import MeetingStore
    from app.services.summarization import SummarizationService
    from app.services.diarization import DiarizationService

_logger = logging.getLogger(__name__)

# Global singleton instance
_background_finalizer: Optional["BackgroundFinalizer"] = None


def get_background_finalizer() -> Optional["BackgroundFinalizer"]:
    """Get the global BackgroundFinalizer instance, if initialized."""
    return _background_finalizer


def set_background_finalizer(instance: "BackgroundFinalizer") -> None:
    """Set the global BackgroundFinalizer instance."""
    global _background_finalizer
    _background_finalizer = instance


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
        self._wake_event = threading.Event()
        
        # Track current work for status reporting (also tracked in global tracker)
        self._current_meeting_id: Optional[str] = None
        self._current_stage: Optional[str] = None
        self._lock = threading.Lock()
        
        # Per-meeting locks to ensure stages run serially within a meeting
        self._meeting_locks: dict[str, threading.Lock] = {}
        self._meeting_locks_lock = threading.Lock()
        
        # Get reference to global tracker
        self._tracker = get_tracker()
    
    def _get_meeting_lock(self, meeting_id: str) -> threading.Lock:
        """Get or create a lock for a specific meeting."""
        with self._meeting_locks_lock:
            if meeting_id not in self._meeting_locks:
                self._meeting_locks[meeting_id] = threading.Lock()
            return self._meeting_locks[meeting_id]
    
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
        self._wake_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        _logger.info("BackgroundFinalizer stopped")
    
    def run_stages_now(self, meeting_id: str, stages: list[str]) -> None:
        """Run multiple stages immediately in a new thread (not queued).
        
        Stages are run serially in dependency order within a single thread.
        Uses per-meeting locking to prevent concurrent stage execution
        (e.g., if background finalizer is also working on this meeting).
        
        Args:
            meeting_id: The meeting ID
            stages: List of stage keys ('diarization', 'speaker_names', 'summary')
        """
        import threading
        
        # Define the correct dependency order
        STAGE_ORDER = ["diarization", "speaker_names", "summary"]
        
        # Sort requested stages by dependency order
        ordered_stages = [s for s in STAGE_ORDER if s in stages]
        
        def _run():
            meeting_lock = self._get_meeting_lock(meeting_id)
            
            # Acquire meeting lock to serialize with background finalizer
            # and other manual requests for the same meeting
            with meeting_lock:
                _logger.info(
                    "run_stages_now: acquired lock for meeting %s, running stages %s",
                    meeting_id, ordered_stages
                )
                
                for stage in ordered_stages:
                    # Refresh meeting data before each stage
                    meeting = self._meeting_store.get_meeting(meeting_id)
                    if not meeting:
                        _logger.warning("run_stages_now: meeting %s not found", meeting_id)
                        return
                    
                    audio_path = meeting.get("audio_path")
                    transcript = meeting.get("transcript", {})
                    segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
                    
                    try:
                        if stage == "diarization":
                            self._run_diarization_stage(meeting_id, audio_path, segments)
                        elif stage == "speaker_names":
                            self._run_speaker_names_stage(meeting_id, segments)
                        elif stage == "summary":
                            self._run_summary_stage(meeting_id)
                        else:
                            _logger.warning("run_stages_now: unknown stage %s", stage)
                    except Exception as exc:
                        _logger.exception(
                            "run_stages_now failed: meeting=%s stage=%s error=%s",
                            meeting_id, stage, exc
                        )
                        # Continue to next stage even if one fails
                
                _logger.info("run_stages_now: completed for meeting %s", meeting_id)
        
        thread = threading.Thread(
            target=_run,
            name=f"manual-finalize-{meeting_id[:8]}",
            daemon=True,
        )
        thread.start()
        _logger.info("run_stages_now: started thread for meeting %s stages %s", meeting_id, ordered_stages)
    
    def _run_diarization_stage(self, meeting_id: str, audio_path: str, segments: list) -> None:
        """Run diarization stage."""
        from app.services.transcription_pipeline import apply_diarization
        
        self._meeting_store.publish_finalization_status(meeting_id, "Diarization...", 0.1)
        self._meeting_store.publish_status_log(meeting_id, "diarization", "started", {"audio_path": audio_path})
        
        if not audio_path or not self._diarization.is_enabled():
            self._meeting_store.mark_finalization_stage(meeting_id, "diarization")
            self._meeting_store.publish_status_log(meeting_id, "diarization", "skipped",
                {"reason": "no audio or diarization disabled"})
            return
        
        try:
            diarization_segments = self._diarization.run(audio_path)
            if diarization_segments:
                updated_segments = apply_diarization(segments, diarization_segments)
                self._meeting_store.update_transcript_speakers(meeting_id, updated_segments)
            self._meeting_store.mark_finalization_stage(meeting_id, "diarization")
            self._meeting_store.publish_status_log(meeting_id, "diarization", "completed",
                {"segments_count": len(diarization_segments) if diarization_segments else 0})
            self._meeting_store.publish_event("meeting_updated", meeting_id)
        except Exception as exc:
            error_detail = f"{type(exc).__name__}: {str(exc)}"
            self._meeting_store.mark_finalization_stage_failed(meeting_id, "diarization", error_detail)
            self._meeting_store.publish_status_log(meeting_id, "diarization", "failed", {"error": error_detail})
            raise
    
    def _run_speaker_names_stage(self, meeting_id: str, segments: list) -> None:
        """Run speaker names identification stage."""
        self._meeting_store.publish_finalization_status(meeting_id, "Speaker Names...", 0.3)
        self._meeting_store.publish_status_log(meeting_id, "speaker_names", "started")
        
        try:
            self._identify_speaker_names(meeting_id, segments)
            self._meeting_store.mark_finalization_stage(meeting_id, "speaker_names")
            self._meeting_store.publish_status_log(meeting_id, "speaker_names", "completed")
            self._meeting_store.publish_event("meeting_updated", meeting_id)
        except Exception as exc:
            error_detail = f"{type(exc).__name__}: {str(exc)}"
            self._meeting_store.mark_finalization_stage_failed(meeting_id, "speaker_names", error_detail)
            self._meeting_store.publish_status_log(meeting_id, "speaker_names", "failed", {"error": error_detail})
            raise
    
    def _run_summary_stage(self, meeting_id: str) -> None:
        """Run summary generation stage.

        Streams tokens from the LLM, accumulates them, then parses the
        structured JSON result.  If the JSON includes a ``title`` field the
        title is applied immediately (eliminating a separate LLM call).
        """
        from app.services.summarization import SummarizationService

        self._meeting_store.publish_finalization_status(meeting_id, "Summary...", 0.6)
        self._meeting_store.publish_status_log(meeting_id, "summary", "started")

        meeting = self._meeting_store.get_meeting(meeting_id)
        if not meeting:
            return

        transcript = meeting.get("transcript", {})
        segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
        user_notes = meeting.get("user_notes", [])

        summary_text = "\n".join(
            seg.get("text", "") for seg in segments if isinstance(seg, dict)
        )

        if not summary_text.strip():
            self._meeting_store.mark_finalization_stage(meeting_id, "summary")
            self._meeting_store.publish_status_log(meeting_id, "summary", "skipped", {"reason": "no transcript text"})
            return

        try:
            accumulated = ""
            for token in self._summarization.summarize_stream(summary_text, user_notes=user_notes):
                accumulated += token
                self._meeting_store.publish_event("summary_token", meeting_id, {"text": accumulated})

            result = SummarizationService.parse_structured_summary(accumulated)

            self._meeting_store.add_summary(
                meeting_id,
                summary_data=result,
                provider="default",
            )

            self._meeting_store.publish_event(
                "summary_complete", meeting_id, {"structured": result}
            )
            self._meeting_store.mark_finalization_stage(meeting_id, "summary")
            self._meeting_store.publish_status_log(meeting_id, "summary", "completed",
                {"summary_length": len(result.get("overview", ""))})

            if result.get("title"):
                self._meeting_store.set_title_from_summary(meeting_id, result["title"])
                self._meeting_store.publish_event(
                    "title_updated", meeting_id,
                    {"title": result["title"], "source": "auto"},
                )

            self._meeting_store.publish_event("meeting_updated", meeting_id)
        except Exception as exc:
            error_detail = f"{type(exc).__name__}: {str(exc)}"
            self._meeting_store.mark_finalization_stage_failed(meeting_id, "summary", error_detail)
            self._meeting_store.publish_status_log(meeting_id, "summary", "failed", {"error": error_detail})
            raise
    
    def wake(self) -> None:
        """Wake the finalizer to process pending meetings immediately."""
        self._wake_event.set()
    
    def get_status(self) -> dict:
        """Get current status of the background finalizer.
        
        Returns:
            Dict with:
                - running: bool - whether the service is running
                - active: bool - whether currently processing a meeting
                - current_meeting_id: str or None
                - current_stage: str or None
                - pending_count: int - number of meetings waiting to be finalized
        """
        with self._lock:
            pending = []
            try:
                pending = self._meeting_store.list_meetings_needing_finalization()
            except Exception:
                pass
            
            return {
                "running": self._running,
                "active": self._current_meeting_id is not None,
                "current_meeting_id": self._current_meeting_id,
                "current_stage": self._current_stage,
                "pending_count": len(pending),
            }
    
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
                    # Wait before processing next meeting (but can be woken)
                    self._wake_event.clear()
                    self._wake_event.wait(self._delay_between_meetings)
                    if self._stop_event.is_set():
                        break
                else:
                    # No meetings need finalization, wait and check again
                    _logger.debug(
                        "BackgroundFinalizer: no meetings need finalization, "
                        "sleeping %ds",
                        self._idle_check_interval,
                    )
                    self._wake_event.clear()
                    self._wake_event.wait(self._idle_check_interval)
                    if self._stop_event.is_set():
                        break
            except Exception as exc:
                _logger.exception(
                    "BackgroundFinalizer sweep loop error: %s",
                    exc,
                )
                # Wait before retrying on error
                self._wake_event.clear()
                self._wake_event.wait(60.0)
    
    def _find_next_incomplete(self) -> Optional[dict]:
        """Find the oldest meeting that needs finalization.
        
        Skips meetings that are already being processed (recording or finalizing).
        
        Returns:
            Meeting dict or None if no meetings need finalization
        """
        try:
            meetings = self._meeting_store.list_meetings_needing_finalization()
            for meeting in meetings:
                meeting_id = meeting.get("id")
                if meeting_id and not self._tracker.is_active(meeting_id):
                    return meeting
            return None
        except Exception as exc:
            _logger.warning(
                "BackgroundFinalizer: error finding incomplete meetings: %s",
                exc,
            )
        return None
    
    def _set_current_work(self, meeting_id: Optional[str], stage: Optional[str]) -> None:
        """Update current work tracking."""
        with self._lock:
            prev_meeting_id = self._current_meeting_id
            self._current_meeting_id = meeting_id
            self._current_stage = stage
        
        # Update global tracker
        if meeting_id and stage:
            self._tracker.update_stage(meeting_id, stage)
    
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
        
        # Register with global tracker (acts as mutex)
        if not self._tracker.register(
            meeting_id,
            MeetingState.BACKGROUND_FINALIZING,
            stage="starting",
        ):
            _logger.info(
                "BackgroundFinalizer: skipping %s - already active in tracker",
                meeting_id,
            )
            return
        
        self._set_current_work(meeting_id, "starting")
        errors_occurred = []
        
        # Acquire per-meeting lock to serialize with manual stage requests
        meeting_lock = self._get_meeting_lock(meeting_id)
        meeting_lock.acquire()
        _logger.info(
            "BackgroundFinalizer: acquired lock for meeting %s",
            meeting_id,
        )
        
        try:
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
            
            pending_stages = self._meeting_store.get_pending_finalization_stages(meeting)
            failed_stages = self._meeting_store.get_failed_finalization_stages(meeting)
            _logger.info(
                "BackgroundFinalizer: meeting %s - pending: %s, failed: %s",
                meeting_id,
                pending_stages,
                failed_stages,
            )
            # Stage 1: Diarization
            diarization_segments = []
            if needs_diarization and audio_path and self._diarization.is_enabled():
                self._set_current_work(meeting_id, "diarization")
                self._meeting_store.publish_finalization_status(
                    meeting_id, "Diarization...", 0.1
                )
                self._meeting_store.publish_status_log(
                    meeting_id, "diarization", "started",
                    {"audio_path": audio_path}
                )
                try:
                    diarization_segments = self._diarization.run(audio_path)
                    if diarization_segments:
                        segments = apply_diarization(segments, diarization_segments)
                        self._meeting_store.update_transcript_speakers(meeting_id, segments)
                    self._meeting_store.mark_finalization_stage(meeting_id, "diarization")
                    self._meeting_store.publish_status_log(
                        meeting_id, "diarization", "completed",
                        {"segments_count": len(diarization_segments)}
                    )
                    _logger.info(
                        "BackgroundFinalizer: diarization complete for %s (%d segments)",
                        meeting_id, len(diarization_segments),
                    )
                except Exception as exc:
                    _logger.warning(
                        "BackgroundFinalizer: diarization failed for %s: %s",
                        meeting_id, exc,
                    )
                    error_detail = f"{type(exc).__name__}: {str(exc)}"
                    self._meeting_store.mark_finalization_stage_failed(
                        meeting_id, "diarization", error_detail
                    )
                    self._meeting_store.publish_status_log(
                        meeting_id, "diarization", "failed",
                        {"error": error_detail}
                    )
                    errors_occurred.append(("diarization", str(exc)))
            elif needs_diarization:
                # No audio or diarization disabled, mark as done
                self._meeting_store.mark_finalization_stage(meeting_id, "diarization")
                self._meeting_store.publish_status_log(
                    meeting_id, "diarization", "skipped",
                    {"reason": "no audio or diarization disabled"}
                )
            
            # Stage 2: Speaker name identification
            if needs_speaker_names and diarization_segments:
                self._set_current_work(meeting_id, "speaker_names")
                self._meeting_store.publish_finalization_status(
                    meeting_id, "Speaker Names...", 0.3
                )
                self._meeting_store.publish_status_log(
                    meeting_id, "speaker_names", "started",
                    {"speakers_count": len(set(s.get("speaker") for s in diarization_segments if s.get("speaker")))}
                )
                try:
                    self._identify_speaker_names(meeting_id, segments)
                    self._meeting_store.mark_finalization_stage(meeting_id, "speaker_names")
                    self._meeting_store.publish_status_log(
                        meeting_id, "speaker_names", "completed"
                    )
                except Exception as exc:
                    _logger.warning(
                        "BackgroundFinalizer: speaker identification failed for %s: %s",
                        meeting_id, exc,
                    )
                    error_detail = f"{type(exc).__name__}: {str(exc)}"
                    self._meeting_store.mark_finalization_stage_failed(
                        meeting_id, "speaker_names", error_detail
                    )
                    self._meeting_store.publish_status_log(
                        meeting_id, "speaker_names", "failed",
                        {"error": error_detail}
                    )
                    errors_occurred.append(("speaker_names", str(exc)))
            elif needs_speaker_names:
                # No diarization segments to identify, mark as done
                self._meeting_store.mark_finalization_stage(meeting_id, "speaker_names")
                self._meeting_store.publish_status_log(
                    meeting_id, "speaker_names", "skipped",
                    {"reason": "no diarization segments"}
                )
            
            # Stage 3: Summary generation (produces structured JSON with title)
            if needs_summary:
                from app.services.summarization import SummarizationService as _SS

                self._set_current_work(meeting_id, "summary")
                self._meeting_store.publish_finalization_status(
                    meeting_id, "Summary...", 0.6
                )
                self._meeting_store.publish_status_log(
                    meeting_id, "summary", "started"
                )
                meeting = self._meeting_store.get_meeting(meeting_id)
                if meeting:
                    transcript = meeting.get("transcript", {})
                    segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
                    user_notes = meeting.get("user_notes", [])

                    summary_text = "\n".join(
                        seg.get("text", "") for seg in segments if isinstance(seg, dict)
                    )

                    if summary_text.strip():
                        self._meeting_store.publish_status_log(
                            meeting_id, "summary", "input",
                            {"transcript_length": len(summary_text)}
                        )
                        try:
                            accumulated = ""
                            for token in self._summarization.summarize_stream(summary_text, user_notes=user_notes):
                                accumulated += token
                                self._meeting_store.publish_event(
                                    "summary_token", meeting_id, {"text": accumulated}
                                )

                            result = _SS.parse_structured_summary(accumulated)

                            self._meeting_store.add_summary(
                                meeting_id,
                                summary_data=result,
                                provider="default",
                            )
                            self._meeting_store.publish_event(
                                "summary_complete", meeting_id, {"structured": result}
                            )
                            self._meeting_store.mark_finalization_stage(meeting_id, "summary")
                            self._meeting_store.publish_status_log(
                                meeting_id, "summary", "completed",
                                {"summary_length": len(result.get("overview", ""))}
                            )
                            _logger.info(
                                "BackgroundFinalizer: summary generated for %s",
                                meeting_id,
                            )

                            if result.get("title"):
                                self._meeting_store.set_title_from_summary(meeting_id, result["title"])
                                self._meeting_store.publish_event(
                                    "title_updated", meeting_id,
                                    {"title": result["title"], "source": "auto"},
                                )

                        except Exception as exc:
                            _logger.warning(
                                "BackgroundFinalizer: summary generation failed for %s: %s",
                                meeting_id, exc,
                            )
                            error_detail = f"{type(exc).__name__}: {str(exc)}"
                            self._meeting_store.mark_finalization_stage_failed(
                                meeting_id, "summary", error_detail
                            )
                            self._meeting_store.publish_status_log(
                                meeting_id, "summary", "failed",
                                {"error": error_detail}
                            )
                            errors_occurred.append(("summary", str(exc)))
                    else:
                        self._meeting_store.mark_finalization_stage(meeting_id, "summary")
                        self._meeting_store.publish_status_log(
                            meeting_id, "summary", "skipped",
                            {"reason": "no transcript text"}
                        )
            
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
            errors_occurred.append(("unknown", str(exc)))
        finally:
            # Release meeting lock
            meeting_lock.release()
            _logger.info(
                "BackgroundFinalizer: released lock for meeting %s",
                meeting_id,
            )
            
            # Unregister from global tracker
            self._tracker.unregister(meeting_id)
            
            # Publish completion or failure event
            self._set_current_work(None, None)
            
            # Get meeting title for notification
            meeting = self._meeting_store.get_meeting(meeting_id)
            meeting_title = "Unknown meeting"
            if meeting:
                meeting_title = meeting.get("title") or meeting_id[:8]
            
            if errors_occurred:
                self._meeting_store.publish_event(
                    "finalization_failed",
                    meeting_id,
                    {
                        "meeting_title": meeting_title,
                        "errors": [{"stage": s, "error": e} for s, e in errors_occurred],
                    },
                )
            else:
                self._meeting_store.publish_event(
                    "finalization_complete",
                    meeting_id,
                    {"meeting_title": meeting_title},
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
