"""
FileReadService — decodes any audio file via ffmpeg and fires a callback
with raw PCM bytes, mimicking sounddevice's callback for microphone input.

This allows AudioCaptureService to treat file playback identically to mic
capture: the same _audio_callback, queues, writer loop, and live tap are
reused without conditionals.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from typing import Callable, Optional

_logger = logging.getLogger("notetaker.file_read_service")


class FileReadService:
    """Stream-decode an audio file and fire a callback with raw PCM blocks.

    The callback signature matches sounddevice's RawInputStream callback:
        callback(indata: bytes, frames: int, time_info, status)

    Audio is normalised to the requested sample rate / channel count via
    ffmpeg, so the downstream pipeline always sees a consistent format
    regardless of the source file's encoding.
    """

    def __init__(
        self,
        file_path: str,
        callback: Callable,
        *,
        samplerate: int = 48000,
        channels: int = 2,
        blocksize: int = 4096,
        speed_percent: int = 300,
        on_complete: Optional[Callable] = None,
    ) -> None:
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Audio file not found: {file_path}")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg not found on PATH")

        self._file_path = file_path
        self._callback = callback
        self._samplerate = samplerate
        self._channels = channels
        self._blocksize = blocksize
        self._speed_percent = speed_percent
        self._ffmpeg_path = ffmpeg

        self._on_complete = on_complete
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stopped = False
        self._complete = False
        self._cancel_event = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch ffmpeg and begin firing callbacks from a background thread."""
        self._proc = subprocess.Popen(
            [
                self._ffmpeg_path,
                "-hide_banner",
                "-loglevel", "error",
                "-i", self._file_path,
                "-f", "s16le",
                "-acodec", "pcm_s16le",
                "-ar", str(self._samplerate),
                "-ac", str(self._channels),
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._thread = threading.Thread(
            target=self._reader_loop, daemon=True, name="file-read-service"
        )
        self._thread.start()
        _logger.info(
            "FileReadService started: file=%s sr=%d ch=%d blocksize=%d speed=%d%%",
            os.path.basename(self._file_path),
            self._samplerate,
            self._channels,
            self._blocksize,
            self._speed_percent,
        )

    def stop(self) -> None:
        """Terminate ffmpeg and signal the reader thread to exit."""
        self._stopped = True
        self._cancel_event.set()
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        _logger.info("FileReadService stopped")

    @property
    def is_complete(self) -> bool:
        return self._complete or self._stopped

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _reader_loop(self) -> None:
        bytes_per_block = self._blocksize * self._channels * 2  # int16
        block_duration_sec = self._blocksize / self._samplerate

        try:
            while not self._stopped:
                data = self._proc.stdout.read(bytes_per_block)
                if not data:
                    break
                self._callback(data, self._blocksize, None, None)

                if self._speed_percent > 0:
                    delay = block_duration_sec / (self._speed_percent / 100.0)
                    if delay > 0:
                        self._cancel_event.wait(timeout=delay)
                        if self._cancel_event.is_set():
                            break
        except Exception as exc:
            _logger.warning("FileReadService reader error: %s", exc)
        finally:
            self._complete = True
            _logger.info("FileReadService reader loop finished")
            if self._on_complete:
                try:
                    self._on_complete()
                except Exception:
                    pass
