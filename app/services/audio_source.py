"""
AudioDataSource abstraction for unified audio pipeline.

This module provides a common interface for audio sources (microphone or file),
allowing the transcription pipeline to process audio identically regardless of origin.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.services.audio_capture import AudioCaptureService

_dbg_logger = logging.getLogger("notetaker.debug")


@dataclass
class AudioMetadata:
    """Metadata about an audio source."""
    samplerate: int
    channels: int
    session_id: str


class AudioDataSource(ABC):
    """
    Abstract base class for audio data sources.
    
    Provides a unified interface for retrieving audio chunks from either
    a microphone (real-time) or a file (pre-recorded). The transcription
    pipeline uses this interface without knowing the underlying source.
    """
    
    @abstractmethod
    def get_chunk(self, timeout_sec: float = 0.5) -> Optional[bytes]:
        """
        Return the next audio chunk.
        
        Blocks up to timeout_sec waiting for data.
        
        Args:
            timeout_sec: Maximum time to wait for a chunk.
            
        Returns:
            Audio data as bytes, or None if no data available or source is complete/stopped.
        """
        pass
    
    @abstractmethod
    def get_metadata(self) -> AudioMetadata:
        """Return audio metadata (samplerate, channels, source type, session ID)."""
        pass
    
    @abstractmethod
    def is_stopped(self) -> bool:
        """Return True if stop has been signaled (but audio may still be buffered)."""
        pass
    
    @abstractmethod
    def is_complete(self) -> bool:
        """Return True if all audio has been delivered (stopped AND buffer empty)."""
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """Signal that processing should stop."""
        pass
    
    def drain_remaining(self) -> bytes:
        """Drain any remaining buffered audio.
        
        Call this after is_complete() returns True to retrieve any audio
        that was buffered but not yet consumed via get_chunk().
        
        Returns:
            Concatenated remaining audio bytes, or empty bytes if none.
        """
        return b""


class LiveAudioSource(AudioDataSource):
    """
    Audio source that reads from AudioCaptureService's live queue.

    Source-agnostic: works identically for both microphone capture and
    file playback, since both modes feed the same _audio_callback and
    _live_queue inside AudioCaptureService.
    """
    
    def __init__(self, audio_service: "AudioCaptureService", session_id: str):
        """
        Initialize mic audio source.
        
        Args:
            audio_service: The AudioCaptureService managing the microphone.
            session_id: Unique identifier for this recording session.
        """
        self._audio_service = audio_service
        self._session_id = session_id
        self._stopped = False
        self._metadata: Optional[AudioMetadata] = None
    
    def get_chunk(self, timeout_sec: float = 0.5) -> Optional[bytes]:
        """
        Get the next audio chunk from the live microphone queue.
        
        Blocks until audio is available or timeout expires.
        Always tries to get from queue, even after capture stops,
        to ensure all buffered audio is consumed.
        """
        # Always try to get from queue - don't early-exit when stopped
        # The queue may still have buffered audio to process
        chunk = self._audio_service.get_live_chunk(timeout=timeout_sec)
        # #region agent log
        _dbg_logger.debug("GET_CHUNK_RESULT: chunk_len=%d chunk_is_none=%s stopped=%s capture_stopped=%s", 
                         len(chunk) if chunk else 0, chunk is None, self._stopped, self._audio_service.is_capture_stopped())
        # #endregion
        return chunk
    
    def get_metadata(self) -> AudioMetadata:
        """Return audio metadata from the capture service."""
        if self._metadata is None:
            status = self._audio_service.current_status()
            self._metadata = AudioMetadata(
                samplerate=status.get("samplerate") or 48000,
                channels=status.get("channels") or 2,
                session_id=self._session_id,
            )
        return self._metadata
    
    def is_stopped(self) -> bool:
        """Check if recording has been stopped (user pressed stop or capture ended).
        
        This returns True as soon as the stop signal is received, regardless of
        whether there's still buffered audio to process. Use this for UI status
        updates or to know when to stop accepting new audio.
        
        For the transcription loop, use is_complete() instead.
        """
        return self._stopped or self._audio_service.is_capture_stopped()
    
    def is_complete(self) -> bool:
        """Check if all audio has been delivered.
        
        Returns True only when:
        1. Recording has stopped (user hit stop OR capture finished), AND
        2. The audio queue is empty (all buffered audio has been consumed)
        
        This ensures the transcription loop processes all audio, even if
        recording stopped before the loop started (e.g., during model loading).
        
        Use is_stopped() if you only need to know whether the user pressed stop.
        """
        stopped = self.is_stopped()
        has_buffered = self._audio_service.has_buffered_audio()
        result = stopped and not has_buffered
        # #region agent log
        _dbg_logger.debug("IS_COMPLETE: stopped=%s has_buffered=%s result=%s", stopped, has_buffered, result)
        # #endregion
        return result
    
    def stop(self) -> None:
        """Signal capture to stop and stop the recording device."""
        self._stopped = True
        self._audio_service.signal_capture_stopped()
        # Also stop the physical recording device
        try:
            self._audio_service.stop_recording()
        except Exception:
            pass  # Recording may have already stopped
    
    def drain_remaining(self) -> bytes:
        """Drain any remaining audio from the live queue.
        
        This is critical for handling the case where the transcription thread
        starts after recording has already stopped. Audio may have accumulated
        in the queue during model loading and initialization.
        
        Returns:
            Concatenated remaining audio bytes.
        """
        remaining = self._audio_service.drain_live_queue()
        # #region agent log
        _dbg_logger.debug("DRAINED: bytes=%d", len(remaining))
        # #endregion
        return remaining


