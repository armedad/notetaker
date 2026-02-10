"""
Real-time diarization service for live audio streams.

This service manages the lifecycle of real-time speaker diarization
during live recording sessions. It coordinates with the audio capture
service to receive audio chunks and provides speaker labels in real-time.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.diarization.providers.base import DiarizationConfig


class RealtimeDiarizationService:
    """Service for managing real-time speaker diarization.
    
    This service:
    - Starts/stops diart pipeline with audio capture sessions
    - Processes audio chunks and maintains current speaker state
    - Provides speaker lookups by timestamp
    - Thread-safe for concurrent access
    """
    
    def __init__(self, config: "DiarizationConfig") -> None:
        self._config = config
        self._logger = logging.getLogger("notetaker.realtime_diarization")
        self._lock = threading.RLock()
        self._provider = None
        self._is_active = False
        self._start_time: Optional[float] = None
        self._sample_rate: int = 16000
        self._channels: int = 1
        self._annotations: list[dict] = []
        self._total_audio_duration: float = 0.0
    
    def is_active(self) -> bool:
        """Check if real-time diarization is currently active."""
        with self._lock:
            return self._is_active
    
    def is_enabled(self) -> bool:
        """Check if real-time diarization is enabled in config."""
        return (
            self._config.enabled 
            and self._config.provider.lower() == "diart"
        )
    
    def start(
        self,
        sample_rate: int = 48000,
        channels: int = 2,
    ) -> bool:
        """Start real-time diarization for a new recording session.
        
        Args:
            sample_rate: Audio sample rate from the microphone
            channels: Number of audio channels
            
        Returns:
            True if started successfully, False otherwise
        """
        with self._lock:
            if self._is_active:
                self._logger.warning("Real-time diarization already active")
                return True
            
            if not self.is_enabled():
                self._logger.debug("Real-time diarization not enabled")
                return False
            
            try:
                from app.services.diarization.providers.diart_provider import DiartProvider
                
                self._provider = DiartProvider(self._config)
                self._provider.start_stream(sample_rate=16000)  # Diart needs 16kHz
                
                self._sample_rate = sample_rate
                self._channels = channels
                self._start_time = time.time()
                self._annotations = []
                self._total_audio_duration = 0.0
                self._is_active = True
                
                self._logger.info(
                    "Real-time diarization started: sample_rate=%s channels=%s",
                    sample_rate,
                    channels,
                )
                return True
                
            except Exception as exc:
                self._logger.exception("Failed to start real-time diarization: %s", exc)
                self._provider = None
                return False
    
    def feed_audio(self, audio_bytes: bytes) -> list[dict]:
        """Feed an audio chunk for real-time diarization.
        
        Args:
            audio_bytes: Raw audio bytes (int16 format)
            
        Returns:
            Current speaker annotations after processing this chunk
        """
        with self._lock:
            if not self._is_active or self._provider is None:
                return []
            
            try:
                # Calculate chunk duration
                bytes_per_sample = 2  # int16
                samples = len(audio_bytes) // (bytes_per_sample * self._channels)
                chunk_duration = samples / self._sample_rate
                self._total_audio_duration += chunk_duration
                
                # Process through diart
                annotations = self._provider.feed_chunk(
                    audio_bytes,
                    sample_rate=self._sample_rate,
                    channels=self._channels,
                )
                
                if annotations:
                    self._annotations = annotations
                
                return self._annotations
                
            except Exception as exc:
                self._logger.warning("Failed to process audio chunk: %s", exc)
                return self._annotations
    
    def get_speaker_at(self, timestamp: float) -> Optional[str]:
        """Get the speaker label at a given timestamp.
        
        Args:
            timestamp: Time in seconds from recording start
            
        Returns:
            Speaker label (e.g., "SPEAKER_00") or None
        """
        with self._lock:
            if not self._is_active:
                return None
            
            # Search annotations for matching time range
            for ann in self._annotations:
                if ann["start"] <= timestamp < ann["end"]:
                    return ann["speaker"]
            
            return None
    
    def get_current_annotations(self) -> list[dict]:
        """Get all current speaker annotations.
        
        Returns:
            List of annotation dicts with start, end, speaker keys
        """
        with self._lock:
            return list(self._annotations)
    
    def stop(self) -> list[dict]:
        """Stop real-time diarization and return final annotations.
        
        Returns:
            Final speaker annotations for the session
        """
        with self._lock:
            if not self._is_active:
                return []
            
            final_annotations = []
            
            try:
                if self._provider is not None:
                    final_annotations = self._provider.stop_stream()
            except Exception as exc:
                self._logger.warning("Error stopping diart stream: %s", exc)
                final_annotations = list(self._annotations)
            
            # Calculate session stats
            session_duration = time.time() - self._start_time if self._start_time else 0
            speaker_count = len(set(a.get("speaker") for a in final_annotations))
            
            self._logger.info(
                "Real-time diarization stopped: duration=%.1fs audio=%.1fs speakers=%s annotations=%s",
                session_duration,
                self._total_audio_duration,
                speaker_count,
                len(final_annotations),
            )
            
            # Clean up
            self._provider = None
            self._is_active = False
            self._start_time = None
            self._annotations = []
            self._total_audio_duration = 0.0
            
            return final_annotations
    
    def update_config(self, config: "DiarizationConfig") -> None:
        """Update the configuration.
        
        Note: Changes won't affect an active session. Stop and restart
        to apply new configuration.
        """
        with self._lock:
            self._config = config
            self._logger.debug("Config updated: enabled=%s provider=%s",
                              config.enabled, config.provider)
