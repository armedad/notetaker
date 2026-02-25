"""
Audio utility functions for format conversion.

Centralizes all audio file reading so that downstream consumers (transcription,
diarization) always receive audio in a consistent format, regardless of the
source file format (Opus, WAV, FLAC, etc.).
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from contextlib import contextmanager
from typing import Iterator, Optional, Tuple

import numpy as np

_logger = logging.getLogger("notetaker.audio_utils")


def load_audio_pcm(
    audio_path: str,
    target_sr: int = 16000,
    mono: bool = True,
) -> Tuple[np.ndarray, int]:
    """Load audio file and convert to PCM numpy array.
    
    Uses ffmpeg to handle any audio format (Opus, WAV, FLAC, MP3, etc.)
    and convert to a consistent PCM format.
    
    Args:
        audio_path: Path to audio file (any format ffmpeg supports)
        target_sr: Target sample rate (default 16000 for speech models)
        mono: Convert to mono if True (default True)
        
    Returns:
        Tuple of (audio_data as float32 numpy array, sample_rate)
        Audio is normalized to [-1.0, 1.0] range.
        
    Raises:
        FileNotFoundError: If audio file doesn't exist
        RuntimeError: If ffmpeg conversion fails
    """
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    
    channels = 1 if mono else 2
    
    cmd = [
        "ffmpeg",
        "-i", audio_path,
        "-f", "f32le",  # 32-bit float little-endian PCM
        "-acodec", "pcm_f32le",
        "-ar", str(target_sr),
        "-ac", str(channels),
        "-",  # Output to stdout
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=300,
        )
        
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"ffmpeg failed: {stderr}")
        
        audio = np.frombuffer(result.stdout, dtype=np.float32)
        
        _logger.debug(
            "Loaded audio: %s -> %d samples @ %d Hz",
            os.path.basename(audio_path),
            len(audio),
            target_sr,
        )
        
        return audio, target_sr
        
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffmpeg timed out loading {audio_path}")
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found - please install ffmpeg")


@contextmanager
def as_wav_file(
    audio_path: str,
    target_sr: int = 16000,
    mono: bool = True,
) -> Iterator[str]:
    """Context manager that provides audio as a temporary WAV file.
    
    Converts any audio format to a temporary WAV file, yields the path,
    then cleans up. This allows passing a consistent format to libraries
    that require file paths (faster-whisper, pyannote, etc.).
    
    Args:
        audio_path: Path to source audio file (any format)
        target_sr: Target sample rate (default 16000)
        mono: Convert to mono if True (default True)
        
    Yields:
        Path to temporary WAV file
        
    Example:
        with as_wav_file("recording.opus") as wav_path:
            segments = model.transcribe(wav_path)
    """
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    
    # If already WAV with correct parameters, just use it directly
    if audio_path.lower().endswith(".wav"):
        # Could add validation of sample rate/channels here if needed
        yield audio_path
        return
    
    # Convert to temporary WAV
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav")
    os.close(tmp_fd)
    
    channels = 1 if mono else 2
    
    cmd = [
        "ffmpeg",
        "-y",  # Overwrite output
        "-i", audio_path,
        "-ar", str(target_sr),
        "-ac", str(channels),
        "-c:a", "pcm_s16le",  # 16-bit signed PCM (standard WAV)
        tmp_path,
    ]
    
    try:
        _logger.debug("Converting %s to temp WAV", os.path.basename(audio_path))
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=300,
        )
        
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"ffmpeg conversion failed: {stderr}")
        
        src_size = os.path.getsize(audio_path)
        wav_size = os.path.getsize(tmp_path)
        _logger.debug(
            "Converted %s (%.1f KB) -> temp WAV (%.1f KB)",
            os.path.basename(audio_path),
            src_size / 1024,
            wav_size / 1024,
        )
        
        yield tmp_path
        
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffmpeg timed out converting {audio_path}")
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found - please install ffmpeg")
    finally:
        # Clean up temp file
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except OSError as e:
            _logger.warning("Failed to delete temp WAV %s: %s", tmp_path, e)


def get_audio_duration(audio_path: str) -> Optional[float]:
    """Get duration of audio file in seconds using ffprobe.
    
    Args:
        audio_path: Path to audio file
        
    Returns:
        Duration in seconds, or None if unable to determine
    """
    if not os.path.isfile(audio_path):
        return None
    
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
        return None
        
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        return None
