"""
Background finalizer service that processes meetings with incomplete finalization.

Event-driven: meetings are enqueued when transcription completes, on retry, or
at boot. A single worker thread processes the queue sequentially (no polling).
"""

from __future__ import annotations

import json
import logging
import os
import queue
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


_BOOT_DELAY_SECONDS = 3.0
_QUEUE_STOP_SENTINEL = object()


class BackgroundFinalizer:
    """Background service that finalizes meetings with incomplete stages.

    Meetings are enqueued explicitly (transcription complete, retry, boot sweep).
    One worker thread drains the queue sequentially.
    """

    def __init__(
        self,
        meeting_store: "MeetingStore",
        summarization_service: "SummarizationService",
        diarization_service: "DiarizationService",
        *,
        config_path: Optional[str] = None,
        delay_between_meetings: float = 30.0,
        idle_check_interval: float = 300.0,
    ) -> None:
        """Initialize the background finalizer.

        Args:
            meeting_store: Meeting store instance
            summarization_service: Summarization service for summary/title generation
            diarization_service: Diarization service for speaker analysis
            config_path: Path to config.json for reading transcription settings
            delay_between_meetings: Seconds to wait between finalizing meetings
            idle_check_interval: Deprecated (unused); kept for call-site compatibility
        """
        self._meeting_store = meeting_store
        self._summarization = summarization_service
        self._diarization = diarization_service
        self._config_path = config_path
        self._delay_between_meetings = delay_between_meetings
        _ = idle_check_interval  # no longer used — finalization is event-driven

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._work_queue: queue.Queue = queue.Queue()
        self._queued_ids: set[str] = set()
        self._queue_lock = threading.Lock()
        
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
    
    def _load_config(self) -> dict:
        """Load config from file."""
        if not self._config_path or not os.path.exists(self._config_path):
            return {}
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            _logger.warning("BackgroundFinalizer: failed to load config: %s", exc)
            return {}
    
    def start(self) -> None:
        """Start the background finalizer thread."""
        if self._running:
            _logger.warning("BackgroundFinalizer already running")
            return
        
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker_loop,
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
        self._work_queue.put(_QUEUE_STOP_SENTINEL)
        if self._thread:
            self._thread.join(timeout=5.0)
        _logger.info("BackgroundFinalizer stopped")

    def enqueue(self, meeting_id: str, *, reason: str = "auto") -> bool:
        """Queue a meeting for finalization if it has pending stages."""
        if not meeting_id:
            return False

        meeting = self._meeting_store.get_meeting(meeting_id)
        if not meeting or not self._meeting_store.needs_finalization(meeting):
            return False

        active = self._tracker.get_state(meeting_id)
        if active and active.state == MeetingState.RECORDING:
            _logger.debug(
                "BackgroundFinalizer: not enqueueing %s — still recording",
                meeting_id,
            )
            return False

        with self._queue_lock:
            if meeting_id in self._queued_ids:
                return True
            self._queued_ids.add(meeting_id)

        self._work_queue.put(meeting_id)
        _logger.info(
            "BackgroundFinalizer: enqueued meeting %s (reason=%s)",
            meeting_id,
            reason,
        )
        return True

    def enqueue_all_pending(self) -> int:
        """Scan disk and enqueue every meeting that needs finalization."""
        count = 0
        try:
            for meeting in self._meeting_store.list_meetings_needing_finalization():
                meeting_id = meeting.get("id")
                if meeting_id and self.enqueue(meeting_id, reason="scan"):
                    count += 1
        except Exception as exc:
            _logger.warning(
                "BackgroundFinalizer: enqueue_all_pending failed: %s",
                exc,
            )
        return count

    def run_stages_now(self, meeting_id: str, stages: list[str]) -> None:
        """Queue a meeting after stages were forced to pending (manual retry)."""
        _ = stages
        self.enqueue(meeting_id, reason="manual_retry")
    
    def _run_transcription_stage(self, meeting_id: str, audio_path: str) -> None:
        """Run transcription stage using final model from config."""
        from app.services.transcription_pipeline import TranscriptionPipeline
        from app.services.transcription.whisper_local import FasterWhisperProvider, WhisperConfig
        
        
        self._meeting_store.publish_finalization_status(meeting_id, "Transcription...", 0.0)
        self._meeting_store.publish_status_log(meeting_id, "transcription", "started", {"audio_path": audio_path})
        
        if not audio_path:
            self._meeting_store.mark_finalization_stage(meeting_id, "transcription")
            self._meeting_store.publish_status_log(meeting_id, "transcription", "skipped",
                {"reason": "no audio file"})
            return
        
        config = self._load_config()
        transcription_config = config.get("transcription", {})
        model_size = transcription_config.get("final_model_size", "medium")
        device = transcription_config.get("final_device", "cpu")
        compute_type = transcription_config.get("final_compute_type", "int8")
        
        if model_size == "none":
            self._meeting_store.mark_finalization_stage(meeting_id, "transcription")
            self._meeting_store.publish_status_log(meeting_id, "transcription", "skipped",
                {"reason": "final model set to none"})
            return
        
        try:
            _logger.info("_run_transcription_stage: meeting=%s model=%s device=%s compute=%s",
                meeting_id, model_size, device, compute_type)
            
            
            whisper_config = WhisperConfig(model_size=model_size, device=device, compute_type=compute_type)
            provider = FasterWhisperProvider(config=whisper_config, diarization=None)
            
            
            pipeline = TranscriptionPipeline(
                provider=provider,
                diarization_service=None,
                meeting_store=self._meeting_store,
                summarization_service=self._summarization,
            )
            
            
            # Pipeline handles audio format conversion internally
            segments, language = pipeline.transcribe_and_format(audio_path)
            
            if segments:
                self._meeting_store.replace_transcript_segments(meeting_id, segments, language)
                _logger.info("_run_transcription_stage: meeting=%s saved %d segments", meeting_id, len(segments))
            
            self._meeting_store.mark_finalization_stage(meeting_id, "transcription")
            self._meeting_store.publish_status_log(meeting_id, "transcription", "completed",
                {"segments_count": len(segments) if segments else 0, "language": language})
            self._meeting_store.publish_event("meeting_updated", meeting_id)
        except Exception as exc:
            import traceback
            error_detail = f"{type(exc).__name__}: {str(exc)}"
            _logger.warning("_run_transcription_stage failed: meeting=%s error=%s\n%s",
                meeting_id, error_detail, traceback.format_exc())
            self._meeting_store.mark_finalization_stage_failed(meeting_id, "transcription", error_detail)
            self._meeting_store.publish_status_log(meeting_id, "transcription", "failed", 
                {"error": error_detail, "traceback": traceback.format_exc()})
            raise
    
    def _run_diarization_stage(self, meeting_id: str, audio_path: str, segments: list) -> None:
        """Run diarization stage."""
        from app.services.transcription_pipeline import apply_diarization
        from app.services.audio_utils import load_audio_for_pyannote
        
        
        self._meeting_store.publish_finalization_status(meeting_id, "Diarization...", 0.1)
        self._meeting_store.publish_status_log(meeting_id, "diarization", "started", {"audio_path": audio_path})
        
        if not audio_path or not self._diarization.is_enabled():
            self._meeting_store.mark_finalization_stage(meeting_id, "diarization")
            self._meeting_store.publish_status_log(meeting_id, "diarization", "skipped",
                {"reason": "no audio or diarization disabled"})
            return
        
        try:
            # Load audio into memory once so diarization doesn't depend on
            # the file path remaining valid throughout processing.
            audio_dict = load_audio_for_pyannote(audio_path)
            diarization_segments = self._diarization.run(audio_dict)
            if diarization_segments:
                updated_segments = apply_diarization(segments, diarization_segments)
                self._meeting_store.update_transcript_speakers(meeting_id, updated_segments)
            self._meeting_store.mark_finalization_stage(meeting_id, "diarization")
            self._meeting_store.publish_status_log(meeting_id, "diarization", "completed",
                {"segments_count": len(diarization_segments) if diarization_segments else 0})
            self._meeting_store.publish_event("meeting_updated", meeting_id)
        except Exception as exc:
            from app.services.diarization import DiarizationError
            from app.services.diarization.validation import format_diarization_start_error
            error_detail = format_diarization_start_error(exc)
            self._meeting_store.mark_finalization_stage_failed(meeting_id, "diarization", error_detail)
            self._meeting_store.publish_status_log(meeting_id, "diarization", "failed", {"error": error_detail})
            raise DiarizationError(error_detail) from exc
    
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
    
    def wake(self) -> None:
        """Enqueue all pending meetings (compat alias for debug/settings restart)."""
        self.enqueue_all_pending()

    def get_status(self) -> dict:
        """Get current status of the background finalizer."""
        with self._lock:
            with self._queue_lock:
                queued_count = len(self._queued_ids)
            return {
                "running": self._running,
                "active": self._current_meeting_id is not None,
                "current_meeting_id": self._current_meeting_id,
                "current_stage": self._current_stage,
                "pending_count": queued_count + (1 if self._current_meeting_id else 0),
            }

    def _enqueue_all_pending_at_boot(self) -> None:
        """One-time boot scan: enqueue meetings left incomplete from a prior run."""
        count = self.enqueue_all_pending()
        _logger.info(
            "BackgroundFinalizer: boot sweep enqueued %d meeting(s)",
            count,
        )

    def _worker_loop(self) -> None:
        """Process enqueued meetings sequentially (blocks on queue — no polling)."""
        _logger.info("BackgroundFinalizer worker started")
        self._stop_event.wait(_BOOT_DELAY_SECONDS)
        if not self._stop_event.is_set():
            self._enqueue_all_pending_at_boot()

        while not self._stop_event.is_set():
            try:
                item = self._work_queue.get()
            except Exception:
                continue

            if item is _QUEUE_STOP_SENTINEL:
                break

            meeting_id = str(item)
            with self._queue_lock:
                self._queued_ids.discard(meeting_id)

            meeting = self._meeting_store.get_meeting(meeting_id)
            if not meeting or not self._meeting_store.needs_finalization(meeting):
                continue

            _logger.info("BackgroundFinalizer processing meeting: %s", meeting_id)
            try:
                self._finalize_meeting(meeting)
            except Exception as exc:
                _logger.exception(
                    "BackgroundFinalizer worker error for %s: %s",
                    meeting_id,
                    exc,
                )
            _logger.info("BackgroundFinalizer completed meeting: %s", meeting_id)

            if self._delay_between_meetings > 0 and not self._stop_event.is_set():
                self._stop_event.wait(self._delay_between_meetings)
    
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

        pending_stages: list[str] = []

        # Register with global tracker (acts as mutex)
        existing = self._tracker.get_state(meeting_id)
        if existing:
            if existing.state == MeetingState.FINALIZING:
                if not self._tracker.transition(
                    meeting_id,
                    MeetingState.BACKGROUND_FINALIZING,
                    stage="starting",
                ):
                    return
            else:
                _logger.info(
                    "BackgroundFinalizer: skipping %s - already active in tracker (%s)",
                    meeting_id,
                    existing.state.value,
                )
                return
        elif not self._tracker.register(
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
            meeting = self._meeting_store.get_meeting(meeting_id)
            if not meeting:
                return
            if meeting.get("status") not in ("completed", "processing"):
                self._meeting_store.update_status(meeting_id, "processing")

            audio_path = meeting.get("audio_path")
            finalization = meeting.get("finalization", {})
            # Migrate old format if needed
            finalization = self._meeting_store._migrate_finalization_state(finalization)
            
            # Get transcript segments
            transcript = meeting.get("transcript", {})
            segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
            
            # Check which stages need to run (only pending, not failed)
            needs_transcription = finalization.get("transcription") == MeetingStore.FINALIZATION_PENDING
            needs_diarization = finalization.get("diarization") == MeetingStore.FINALIZATION_PENDING
            needs_speaker_names = finalization.get("speaker_names") == MeetingStore.FINALIZATION_PENDING
            pending_stages = self._meeting_store.get_pending_finalization_stages(meeting)
            failed_stages = self._meeting_store.get_failed_finalization_stages(meeting)
            _logger.info(
                "BackgroundFinalizer: meeting %s - pending: %s, failed: %s",
                meeting_id,
                pending_stages,
                failed_stages,
            )
            
            # Publish finalization group header for auto-finalization
            if pending_stages:
                self._meeting_store.publish_status_log(
                    meeting_id, "finalization", "started",
                    data={"stages": pending_stages, "label": "Auto-finalization"},
                    trigger="auto"
                )
            
            # Stage 0: Transcription (final model)
            if needs_transcription:
                self._set_current_work(meeting_id, "transcription")
                try:
                    self._run_transcription_stage(meeting_id, audio_path)
                    # Refresh segments after transcription
                    meeting = self._meeting_store.get_meeting(meeting_id)
                    if meeting:
                        transcript = meeting.get("transcript", {})
                        segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
                except Exception as exc:
                    _logger.warning(
                        "BackgroundFinalizer: transcription failed for %s: %s",
                        meeting_id, exc,
                    )
                    errors_occurred.append(("transcription", str(exc)))
            
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
                    from app.services.audio_utils import load_audio_for_pyannote
                    audio_dict = load_audio_for_pyannote(audio_path)
                    diarization_segments = self._diarization.run(audio_dict)
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
            has_speaker_labels = any(seg.get("speaker") for seg in segments)
            if needs_speaker_names and (diarization_segments or has_speaker_labels):
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
            
            # Optional auto-title from transcript (best-effort)
            meeting = self._meeting_store.get_meeting(meeting_id)
            if meeting:
                transcript = meeting.get("transcript", {})
                segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
                existing_attendees = meeting.get("attendees", [])
                has_speakers = any(seg.get("speaker") for seg in segments)
                if has_speakers and not existing_attendees:
                    self._meeting_store.update_transcript_speakers(meeting_id, segments)
                transcript_text = "\n".join(
                    seg.get("text", "") for seg in segments if isinstance(seg, dict)
                )
                if transcript_text.strip():
                    try:
                        self._meeting_store.maybe_auto_title(
                            meeting_id,
                            transcript_text[:4000],
                            self._summarization,
                        )
                    except Exception as exc:
                        _logger.warning(
                            "BackgroundFinalizer: auto title failed for %s: %s",
                            meeting_id,
                            exc,
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
                # Publish finalization group failure
                if pending_stages:
                    self._meeting_store.publish_status_log(
                        meeting_id, "finalization", "failed",
                        data={"stages": pending_stages, "errors": [{"stage": s, "error": e} for s, e in errors_occurred]},
                        trigger="auto"
                    )
                self._meeting_store.publish_event(
                    "finalization_failed",
                    meeting_id,
                    {
                        "meeting_title": meeting_title,
                        "errors": [{"stage": s, "error": e} for s, e in errors_occurred],
                    },
                )
            else:
                # Publish finalization group completion
                if pending_stages:
                    self._meeting_store.publish_status_log(
                        meeting_id, "finalization", "completed",
                        data={"stages": pending_stages},
                        trigger="auto"
                    )
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
