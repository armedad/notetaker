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
from typing import Optional, TYPE_CHECKING, Union

from app.services.debug_logging import dbg
from app.services.ndjson_debug import dbg as nd_dbg

if TYPE_CHECKING:
    from app.services.diarization.providers.base import DiarizationConfig, RealtimeDiarizationConfig


class RealtimeDiarizationService:
    """Service for managing real-time speaker diarization.
    
    This service:
    - Starts/stops diart pipeline with audio capture sessions
    - Processes audio chunks and maintains current speaker state
    - Provides speaker lookups by timestamp
    - Thread-safe for concurrent access
    
    Accepts either:
    - RealtimeDiarizationConfig (new format)
    - DiarizationConfig (legacy format for backwards compatibility)
    """
    
    def __init__(self, config: Union["DiarizationConfig", "RealtimeDiarizationConfig"]) -> None:
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
        self._dbg_feed_count: int = 0
    
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
            nd_dbg(
                "app/services/realtime_diarization.py:start",
                "rt_start_enter",
                {
                    "enabled": bool(self._config.enabled),
                    "provider": str(getattr(self._config, "provider", "") or ""),
                    "is_enabled": bool(self.is_enabled()),
                    "device": str(getattr(self._config, "device", "") or ""),
                    "hf_token_present": bool(getattr(self._config, "hf_token", None)),
                    "sample_rate": sample_rate,
                    "channels": channels,
                },
                run_id="pre-fix",
                hypothesis_id="H1",
            )
            dbg(
                self._logger,
                location="app/services/realtime_diarization.py:start",
                message="rt_start_enter",
                data={
                    "enabled": bool(self._config.enabled),
                    "provider": str(getattr(self._config, "provider", "") or ""),
                    "is_enabled": bool(self.is_enabled()),
                    "device": str(getattr(self._config, "device", "") or ""),
                    "hf_token_present": bool(getattr(self._config, "hf_token", None)),
                    "sample_rate": sample_rate,
                    "channels": channels,
                },
                run_id="pre-fix",
                hypothesis_id="H1",
            )
            if self._is_active:
                self._logger.warning("Real-time diarization already active")
                return True
            
            if not self.is_enabled():
                self._logger.debug("Real-time diarization not enabled")
                nd_dbg(
                    "app/services/realtime_diarization.py:start",
                    "rt_start_not_enabled",
                    {"enabled": bool(self._config.enabled), "provider": str(self._config.provider)},
                    run_id="pre-fix",
                    hypothesis_id="H1",
                )
                dbg(
                    self._logger,
                    location="app/services/realtime_diarization.py:start",
                    message="rt_start_not_enabled",
                    data={"enabled": bool(self._config.enabled), "provider": str(self._config.provider)},
                    run_id="pre-fix",
                    hypothesis_id="H1",
                )
                return False
            
            try:
                from app.services.diarization.providers.diart_provider import DiartProvider
                from app.services.diarization.providers.base import DiarizationConfig, RealtimeDiarizationConfig
                
                # Convert RealtimeDiarizationConfig to legacy DiarizationConfig for the provider
                if hasattr(self._config, "performance_level") and not hasattr(self._config, "model"):
                    # This is a RealtimeDiarizationConfig
                    legacy_config = DiarizationConfig.from_realtime(self._config)
                else:
                    legacy_config = self._config
                
                self._provider = DiartProvider(legacy_config)
                self._provider.start_stream(sample_rate=16000)  # Diart needs 16kHz
                
                self._sample_rate = sample_rate
                self._channels = channels
                self._start_time = time.time()
                self._annotations = []
                self._total_audio_duration = 0.0
                self._is_active = True
                self._dbg_feed_count = 0
                
                self._logger.info(
                    "Real-time diarization started: sample_rate=%s channels=%s",
                    sample_rate,
                    channels,
                )
                nd_dbg(
                    "app/services/realtime_diarization.py:start",
                    "rt_start_ok",
                    {"started": True},
                    run_id="pre-fix",
                    hypothesis_id="H2",
                )
                dbg(
                    self._logger,
                    location="app/services/realtime_diarization.py:start",
                    message="rt_start_ok",
                    data={"started": True},
                    run_id="pre-fix",
                    hypothesis_id="H2",
                )
                return True
                
            except Exception as exc:
                self._logger.exception("Failed to start real-time diarization: %s", exc)
                nd_dbg(
                    "app/services/realtime_diarization.py:start",
                    "rt_start_error",
                    {"exc_type": type(exc).__name__, "exc_str": str(exc)[:800]},
                    run_id="pre-fix",
                    hypothesis_id="H2",
                )
                dbg(
                    self._logger,
                    location="app/services/realtime_diarization.py:start",
                    message="rt_start_error",
                    data={"exc_type": type(exc).__name__, "exc_str": str(exc)[:800]},
                    run_id="pre-fix",
                    hypothesis_id="H2",
                )
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

                # Log only first few feed calls to avoid spamming.
                if self._dbg_feed_count < 3:
                    self._dbg_feed_count += 1
                    nd_dbg(
                        "app/services/realtime_diarization.py:feed_audio",
                        "rt_feed",
                        {
                            "bytes": len(audio_bytes),
                            "chunk_duration_s": round(chunk_duration, 3),
                            "total_audio_s": round(self._total_audio_duration, 3),
                            "annotations": len(self._annotations),
                        },
                        run_id="pre-fix",
                        hypothesis_id="H3",
                    )
                    dbg(
                        self._logger,
                        location="app/services/realtime_diarization.py:feed_audio",
                        message="rt_feed",
                        data={
                            "bytes": len(audio_bytes),
                            "chunk_duration_s": round(chunk_duration, 3),
                            "total_audio_s": round(self._total_audio_duration, 3),
                            "annotations": len(self._annotations),
                        },
                        run_id="pre-fix",
                        hypothesis_id="H3",
                    )
                
                return self._annotations
                
            except Exception as exc:
                self._logger.warning("Failed to process audio chunk: %s", exc)
                nd_dbg(
                    "app/services/realtime_diarization.py:feed_audio",
                    "rt_feed_error",
                    {"exc_type": type(exc).__name__, "exc_str": str(exc)[:800]},
                    run_id="pre-fix",
                    hypothesis_id="H3",
                )
                dbg(
                    self._logger,
                    location="app/services/realtime_diarization.py:feed_audio",
                    message="rt_feed_error",
                    data={"exc_type": type(exc).__name__, "exc_str": str(exc)[:800]},
                    run_id="pre-fix",
                    hypothesis_id="H3",
                )
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
                nd_dbg(
                    "app/services/realtime_diarization.py:stop",
                    "rt_stop_error",
                    {"exc_type": type(exc).__name__, "exc_str": str(exc)[:800]},
                    run_id="pre-fix",
                    hypothesis_id="H4",
                )
                dbg(
                    self._logger,
                    location="app/services/realtime_diarization.py:stop",
                    message="rt_stop_error",
                    data={"exc_type": type(exc).__name__, "exc_str": str(exc)[:800]},
                    run_id="pre-fix",
                    hypothesis_id="H4",
                )
            
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
            nd_dbg(
                "app/services/realtime_diarization.py:stop",
                "rt_stop_stats",
                {
                    "session_duration_s": round(session_duration, 3),
                    "audio_s": round(self._total_audio_duration, 3),
                    "speakers": speaker_count,
                    "annotations": len(final_annotations),
                },
                run_id="pre-fix",
                hypothesis_id="H4",
            )
            dbg(
                self._logger,
                location="app/services/realtime_diarization.py:stop",
                message="rt_stop_stats",
                data={
                    "session_duration_s": round(session_duration, 3),
                    "audio_s": round(self._total_audio_duration, 3),
                    "speakers": speaker_count,
                    "annotations": len(final_annotations),
                },
                run_id="pre-fix",
                hypothesis_id="H4",
            )
            
            # Clean up
            self._provider = None
            self._is_active = False
            self._start_time = None
            self._annotations = []
            self._total_audio_duration = 0.0
            
            return final_annotations
    
    def update_config(self, config: Union["DiarizationConfig", "RealtimeDiarizationConfig"]) -> None:
        """Update the configuration.
        
        Note: Changes won't affect an active session. Stop and restart
        to apply new configuration.
        """
        with self._lock:
            self._config = config
            self._logger.debug("Config updated: enabled=%s provider=%s",
                              config.enabled, config.provider)
