"""
AudioDataSource abstraction for unified audio pipeline.

This module provides a common interface for audio sources (microphone or file),
allowing the transcription pipeline to process audio identically regardless of origin.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional
import os
import threading
import uuid

import soundfile as sf

if TYPE_CHECKING:
    from app.services.audio_capture import AudioCaptureService


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
    def is_complete(self) -> bool:
        """Return True if all audio has been delivered."""
        pass
    
    @abstractmethod
    def stop(self) -> None:
        """Signal that processing should stop."""
        pass


class MicAudioSource(AudioDataSource):
    """
    Audio source that reads from a live microphone via AudioCaptureService.
    
    Chunks are delivered in real-time as they are captured.
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
        """
        if self._stopped or self._audio_service.is_capture_stopped():
            return None
        return self._audio_service.get_live_chunk(timeout=timeout_sec)
    
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
    
    def is_complete(self) -> bool:
        """Check if microphone capture has stopped."""
        return self._stopped or self._audio_service.is_capture_stopped()
    
    def stop(self) -> None:
        """Signal capture to stop and stop the recording device."""
        self._stopped = True
        self._audio_service.signal_capture_stopped()
        # Also stop the physical recording device
        try:
            self._audio_service.stop_recording()
        except Exception:
            pass  # Recording may have already stopped


class FileAudioSource(AudioDataSource):
    """
    Audio source that reads from an audio file.
    
    Supports configurable playback speed to control how quickly chunks are delivered:
    - 0 = no delay (as fast as possible)
    - 100 = real-time (wait full chunk duration between chunks)
    - 300 = 3x faster (wait 1/3 of chunk duration) [DEFAULT]
    """
    
    def __init__(
        self,
        file_path: str,
        chunk_duration_sec: float = 5.0,
        speed_percent: int = 300,
    ):
        """
        Initialize file audio source.
        
        Args:
            file_path: Path to the audio file.
            chunk_duration_sec: Duration of each chunk in seconds.
            speed_percent: Playback speed percentage. 0 = no delay, 100 = real-time,
                          300 = 3x faster (default).
        """
        self._file_path = file_path
        self._chunk_duration = chunk_duration_sec
        self._speed_percent = speed_percent
        self._session_id = str(uuid.uuid4())
        self._stopped = False
        self._complete = False
        self._cancel_event = threading.Event()
        
        # Load file metadata
        info = sf.info(file_path)
        self._samplerate = info.samplerate
        self._channels = info.channels
        self._chunk_samples = int(self._samplerate * chunk_duration_sec)
        
        # Create chunk generator
        self._chunk_gen = self._read_chunks()
    
    def _read_chunks(self):
        """Generator that yields audio chunks from the file.
        
        Reads as int16 to match MicAudioSource format (which provides int16 from RawInputStream).
        The transcription pipeline expects 16-bit PCM audio data.
        """
        # #region agent log
        import json
        def _dbg(msg, data):
            try:
                with open(os.path.join(os.getcwd(), "logs", "debug.log"), "a") as f:
                    f.write(json.dumps({"location": "audio_source.py:_read_chunks", "message": msg, "data": data, "timestamp": __import__("time").time() * 1000, "runId": "post-fix", "hypothesisId": "H1"}) + "\n")
            except: pass
        # #endregion
        chunk_num = 0
        with sf.SoundFile(self._file_path) as f:
            # #region agent log
            _dbg("file_opened", {"path": self._file_path, "samplerate": f.samplerate, "channels": f.channels, "frames": f.frames, "format": f.format, "subtype": f.subtype})
            # #endregion
            while not self._stopped:
                # Read as int16 to match MicAudioSource format (16-bit PCM)
                data = f.read(self._chunk_samples, dtype='int16')
                if len(data) == 0:
                    break
                chunk_bytes = data.tobytes()
                chunk_num += 1
                # #region agent log
                if chunk_num <= 3:
                    _dbg("chunk_read", {"chunk_num": chunk_num, "data_shape": list(data.shape) if hasattr(data, 'shape') else len(data), "data_dtype": str(data.dtype), "bytes_len": len(chunk_bytes), "samples_in_chunk": len(data), "expected_samples": self._chunk_samples})
                # #endregion
                yield chunk_bytes
    
    def get_chunk(self, timeout_sec: float = 0.5) -> Optional[bytes]:
        """
        Get the next audio chunk from the file.
        
        Applies speed delay if configured. A speed_percent of 0 returns chunks
        as fast as possible; higher values introduce proportional delays.
        """
        if self._stopped or self._complete:
            return None
        
        try:
            chunk = next(self._chunk_gen)
            
            # Apply speed delay if configured (speed_percent > 0)
            if self._speed_percent > 0:
                # At 100%, delay = chunk_duration (real-time)
                # At 300%, delay = chunk_duration / 3
                delay = self._chunk_duration / (self._speed_percent / 100.0)
                if delay > 0:
                    # Use cancel_event.wait() so stop() can interrupt the delay
                    self._cancel_event.wait(timeout=delay)
                    if self._cancel_event.is_set():
                        # stop() was called during delay
                        return None
            
            return chunk
        except StopIteration:
            self._complete = True
            return None
    
    def get_metadata(self) -> AudioMetadata:
        """Return audio metadata from the file."""
        return AudioMetadata(
            samplerate=self._samplerate,
            channels=self._channels,
            session_id=self._session_id,
        )
    
    def is_complete(self) -> bool:
        """Check if all file audio has been read."""
        return self._complete or self._stopped
    
    def stop(self) -> None:
        """Signal that processing should stop."""
        self._stopped = True
        self._cancel_event.set()  # Interrupt any active delay
