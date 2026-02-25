"""
Central tracker for active meeting states.

This service provides authoritative real-time state for meetings that are
actively being processed (recording, finalizing, etc.). It replaces distributed
in-memory tracking with a single source of truth.

The tracker is the authoritative source for:
- Meetings currently being recorded
- Meetings in live finalization (post-recording)
- Meetings in background finalization

File-based state in meeting JSON files should only be trusted for completed
meetings. For active meetings, always check this tracker first.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

_logger = logging.getLogger(__name__)


class MeetingState(Enum):
    """States for actively-processing meetings."""
    
    RECORDING = "recording"
    """Meeting is actively being recorded/transcribed."""
    
    FINALIZING = "finalizing"
    """Live finalization in progress (diarization, summary, title after recording stops)."""
    
    BACKGROUND_FINALIZING = "background_finalizing"
    """Background sweep is processing this meeting."""


@dataclass
class ActiveMeeting:
    """Represents an actively-processing meeting."""
    
    meeting_id: str
    state: MeetingState
    started_at: datetime = field(default_factory=datetime.utcnow)
    stage: Optional[str] = None
    """Current finalization stage (e.g., 'diarization', 'summary') if applicable."""
    
    audio_source: Optional[str] = None
    """Audio source type: 'microphone', 'file', etc."""
    
    audio_path: Optional[str] = None
    """Path to the audio file being processed (new WAV for current session)."""
    
    existing_audio_path: Optional[str] = None
    """Path to existing audio file for resumed meetings (for concatenation on stop)."""
    
    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "meeting_id": self.meeting_id,
            "state": self.state.value,
            "started_at": self.started_at.isoformat(),
            "stage": self.stage,
            "audio_source": self.audio_source,
            "audio_path": self.audio_path,
            "existing_audio_path": self.existing_audio_path,
        }


class ActiveMeetingTracker:
    """Thread-safe tracker for active meeting states.
    
    Use this tracker as the authoritative source for whether a meeting is
    currently being processed. It provides:
    
    - register(): Add a meeting to active tracking (returns False if already active)
    - unregister(): Remove a meeting from tracking
    - get_state(): Get the current state of a meeting
    - is_active(): Check if a meeting is being processed
    - get_all_active(): Get all active meetings
    
    The tracker uses mutex semantics: register() will fail if the meeting is
    already registered, preventing race conditions in finalization.
    """
    
    def __init__(self) -> None:
        self._active_meetings: dict[str, ActiveMeeting] = {}
        self._lock = threading.Lock()
    
    def register(
        self,
        meeting_id: str,
        state: MeetingState,
        *,
        stage: Optional[str] = None,
        audio_source: Optional[str] = None,
        audio_path: Optional[str] = None,
        existing_audio_path: Optional[str] = None,
    ) -> bool:
        """Register a meeting as actively processing.
        
        This acts as a mutex: if the meeting is already registered, this
        returns False without modifying the existing registration.
        
        Args:
            meeting_id: Meeting ID to register
            state: The processing state
            stage: Optional current finalization stage
            audio_source: Optional audio source type
            audio_path: Optional audio file path (new WAV for current session)
            existing_audio_path: Optional existing audio path for resumed meetings
            
        Returns:
            True if registration succeeded, False if meeting was already active
        """
        with self._lock:
            if meeting_id in self._active_meetings:
                existing = self._active_meetings[meeting_id]
                _logger.warning(
                    "ActiveMeetingTracker: meeting %s already active in state %s, "
                    "rejecting registration for state %s",
                    meeting_id,
                    existing.state.value,
                    state.value,
                )
                return False
            
            self._active_meetings[meeting_id] = ActiveMeeting(
                meeting_id=meeting_id,
                state=state,
                stage=stage,
                audio_source=audio_source,
                audio_path=audio_path,
                existing_audio_path=existing_audio_path,
            )
            _logger.info(
                "ActiveMeetingTracker: registered meeting %s with state %s (existing_audio=%s)",
                meeting_id,
                state.value,
                existing_audio_path is not None,
            )
            return True
    
    def transition(
        self,
        meeting_id: str,
        new_state: MeetingState,
        *,
        stage: Optional[str] = None,
    ) -> bool:
        """Transition a meeting to a new state.
        
        The meeting must already be registered. Use this for transitions
        like RECORDING -> FINALIZING.
        
        Args:
            meeting_id: Meeting ID to transition
            new_state: The new state
            stage: Optional new stage
            
        Returns:
            True if transition succeeded, False if meeting not found
        """
        with self._lock:
            if meeting_id not in self._active_meetings:
                _logger.warning(
                    "ActiveMeetingTracker: cannot transition meeting %s - not active",
                    meeting_id,
                )
                return False
            
            active = self._active_meetings[meeting_id]
            old_state = active.state
            active.state = new_state
            if stage is not None:
                active.stage = stage
            
            _logger.info(
                "ActiveMeetingTracker: transitioned meeting %s from %s to %s",
                meeting_id,
                old_state.value,
                new_state.value,
            )
            return True
    
    def update_stage(self, meeting_id: str, stage: str) -> bool:
        """Update the current stage of an active meeting.
        
        Args:
            meeting_id: Meeting ID to update
            stage: New stage name (e.g., 'diarization', 'summary')
            
        Returns:
            True if update succeeded, False if meeting not found
        """
        with self._lock:
            if meeting_id not in self._active_meetings:
                return False
            
            self._active_meetings[meeting_id].stage = stage
            return True
    
    def unregister(self, meeting_id: str) -> bool:
        """Remove a meeting from active tracking.
        
        Call this when processing is complete (recording stopped, finalization done).
        
        Args:
            meeting_id: Meeting ID to unregister
            
        Returns:
            True if meeting was removed, False if it wasn't registered
        """
        with self._lock:
            if meeting_id not in self._active_meetings:
                return False
            
            active = self._active_meetings.pop(meeting_id)
            _logger.info(
                "ActiveMeetingTracker: unregistered meeting %s (was %s)",
                meeting_id,
                active.state.value,
            )
            return True
    
    def get_state(self, meeting_id: str) -> Optional[ActiveMeeting]:
        """Get the current state of an active meeting.
        
        Args:
            meeting_id: Meeting ID to check
            
        Returns:
            ActiveMeeting if active, None otherwise
        """
        with self._lock:
            return self._active_meetings.get(meeting_id)
    
    def is_active(self, meeting_id: str) -> bool:
        """Check if a meeting is currently being processed.
        
        Args:
            meeting_id: Meeting ID to check
            
        Returns:
            True if meeting is active, False otherwise
        """
        with self._lock:
            return meeting_id in self._active_meetings
    
    def get_all_active(self) -> dict[str, ActiveMeeting]:
        """Get all currently active meetings.
        
        Returns:
            Dict mapping meeting_id to ActiveMeeting
        """
        with self._lock:
            return dict(self._active_meetings)
    
    def get_all_active_dict(self) -> dict[str, dict]:
        """Get all active meetings as JSON-serializable dicts.
        
        Returns:
            Dict mapping meeting_id to meeting info dict
        """
        with self._lock:
            return {
                mid: active.to_dict()
                for mid, active in self._active_meetings.items()
            }
    
    def get_by_state(self, state: MeetingState) -> list[str]:
        """Get meeting IDs in a specific state.
        
        Args:
            state: The state to filter by
            
        Returns:
            List of meeting IDs in that state
        """
        with self._lock:
            return [
                mid for mid, active in self._active_meetings.items()
                if active.state == state
            ]
    
    def clear(self) -> int:
        """Clear all active meetings (for testing/reset).
        
        Returns:
            Number of meetings cleared
        """
        with self._lock:
            count = len(self._active_meetings)
            self._active_meetings.clear()
            _logger.info("ActiveMeetingTracker: cleared %d active meetings", count)
            return count


# Global singleton instance
_tracker: Optional[ActiveMeetingTracker] = None
_tracker_lock = threading.Lock()


def get_tracker() -> ActiveMeetingTracker:
    """Get the global ActiveMeetingTracker singleton.
    
    Returns:
        The global tracker instance
    """
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = ActiveMeetingTracker()
    return _tracker
