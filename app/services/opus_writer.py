"""
Opus stream writer for direct recording to Opus format.

Uses PyOgg to encode PCM audio directly to Opus without intermediate WAV files,
enabling immediate finalization after recording stops.
"""

from __future__ import annotations

import logging
from typing import Optional

_logger = logging.getLogger("notetaker.opus_writer")

# Track whether PyOgg is available
_PYOGG_AVAILABLE = False
try:
    from pyogg import OpusBufferedEncoder, OggOpusWriter
    _PYOGG_AVAILABLE = True
except ImportError:
    _logger.warning("PyOgg not available - will fall back to WAV recording")
    OpusBufferedEncoder = None
    OggOpusWriter = None


def is_opus_recording_available() -> bool:
    """Check if direct Opus recording is available."""
    return _PYOGG_AVAILABLE


class OpusStreamWriter:
    """Stream PCM audio directly to an Opus file.
    
    Encodes audio in real-time using the Opus codec, which provides excellent
    compression for speech (32kbps = ~3.5MB/hour vs ~115MB/hour for WAV).
    
    Usage:
        with OpusStreamWriter("output.opus", sample_rate=48000, channels=1) as writer:
            while recording:
                writer.write(pcm_bytes)
    
    Args:
        path: Output file path (should end in .opus)
        sample_rate: Audio sample rate in Hz (default 48000, Opus native rate)
        channels: Number of audio channels (1=mono, 2=stereo)
        bitrate: Target bitrate in kbps (default 32, excellent for speech)
        frame_size_ms: Opus frame size in milliseconds (default 20)
    """
    
    def __init__(
        self,
        path: str,
        sample_rate: int = 48000,
        channels: int = 1,
        bitrate: int = 32,
        frame_size_ms: int = 20,
    ) -> None:
        if not _PYOGG_AVAILABLE:
            raise RuntimeError("PyOgg is not installed - cannot create OpusStreamWriter")
        
        self._path = path
        self._sample_rate = sample_rate
        self._channels = channels
        self._closed = False
        
        # Create and configure the encoder
        self._encoder = OpusBufferedEncoder()
        self._encoder.set_application("voip")  # Optimized for speech
        self._encoder.set_sampling_frequency(sample_rate)
        self._encoder.set_channels(channels)
        self._encoder.set_frame_size(frame_size_ms)  # Frame size in ms
        
        # Create the OggOpus file writer
        self._writer = OggOpusWriter(path, self._encoder)
        
        _logger.debug(
            "OpusStreamWriter initialized: path=%s rate=%d ch=%d bitrate=%dk frame=%dms",
            path, sample_rate, channels, bitrate, frame_size_ms
        )
    
    def write(self, pcm_bytes: bytes) -> None:
        """Write PCM audio bytes to the Opus stream.
        
        Args:
            pcm_bytes: Raw PCM audio as bytes (signed 16-bit integers, interleaved for stereo)
        
        Raises:
            RuntimeError: If the writer has been closed
        """
        if self._closed:
            raise RuntimeError("OpusStreamWriter is closed")
        
        if not pcm_bytes:
            return
        
        # PyOgg's write method expects a memoryview of a bytearray
        self._writer.write(memoryview(bytearray(pcm_bytes)))
    
    def close(self) -> None:
        """Finalize and close the Opus file.
        
        This flushes any buffered audio and writes the final Ogg page.
        Safe to call multiple times.
        """
        if self._closed:
            return
        
        try:
            self._writer.close()
            _logger.debug("OpusStreamWriter closed: %s", self._path)
        except Exception as exc:
            _logger.error("Error closing OpusStreamWriter: %s", exc)
            raise
        finally:
            self._closed = True
    
    def __enter__(self) -> "OpusStreamWriter":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
    
    @property
    def path(self) -> str:
        """Return the output file path."""
        return self._path
    
    @property
    def is_closed(self) -> bool:
        """Return whether the writer has been closed."""
        return self._closed
