"""
Live transcription service with decoupled audio capture and transcription.

This service separates audio accumulation from transcription processing,
allowing for responsive stop behavior where:
1. Audio capture stops immediately when requested
2. Remaining buffered audio is queued for transcription
3. Transcription continues in background until queue is drained
"""

from __future__ import annotations

import logging
import os
import queue
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional, TYPE_CHECKING

import numpy as np
import soundfile as sf

if TYPE_CHECKING:
    from app.services.audio_capture import AudioCaptureService
    from app.services.transcription_pipeline import TranscriptionPipeline
    from app.services.realtime_diarization import RealtimeDiarizationService


@dataclass
class TranscriptionChunk:
    """A chunk of audio to be transcribed."""
    audio_bytes: bytes
    offset_seconds: float
    is_final: bool = False


@dataclass 
class TranscriptionSegment:
    """A transcribed segment result."""
    segment: dict
    language: Optional[str]


class LiveTranscriptionService:
    """Manages live transcription with decoupled capture and processing.
    
    Architecture:
    - Accumulator thread: Pulls audio from capture service, buffers until
      chunk threshold, queues chunks for transcription
    - Worker thread: Pulls chunks from queue, runs transcription, emits
      segments via callback
    
    This allows:
    - Immediate response to stop requests (capture stops, queue drains)
    - Background completion of transcription
    - Model-specific chunk sizes (Whisper: 30s, Parakeet: 2s, etc.)
    """
    
    def __init__(
        self,
        audio_service: "AudioCaptureService",
        pipeline: "TranscriptionPipeline",
        realtime_diarization: Optional["RealtimeDiarizationService"] = None,
        chunk_seconds: float = 30.0,
    ) -> None:
        self._audio_service = audio_service
        self._pipeline = pipeline
        self._realtime_diarization = realtime_diarization
        self._chunk_seconds = chunk_seconds
        self._logger = logging.getLogger("notetaker.live_transcription")
        
        # Threading state
        self._lock = threading.RLock()
        self._stop_requested = threading.Event()
        self._accumulator_thread: Optional[threading.Thread] = None
        self._worker_thread: Optional[threading.Thread] = None
        
        # Queues
        self._chunk_queue: queue.Queue[TranscriptionChunk] = queue.Queue(maxsize=10)
        self._segment_queue: queue.Queue[TranscriptionSegment] = queue.Queue()
        
        # State
        self._is_active = False
        self._capture_stopped = False
        self._transcription_complete = False
        self._samplerate: int = 48000
        self._channels: int = 2
        self._meeting_id: Optional[str] = None
        self._last_language: Optional[str] = None
        
        # Callbacks
        self._on_segment: Optional[Callable[[dict, Optional[str]], None]] = None
        self._on_complete: Optional[Callable[[], None]] = None
        self._on_error: Optional[Callable[[Exception], None]] = None

    def start(
        self,
        samplerate: int,
        channels: int,
        meeting_id: Optional[str] = None,
        on_segment: Optional[Callable[[dict, Optional[str]], None]] = None,
        on_complete: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> bool:
        """Start live transcription.
        
        Args:
            samplerate: Audio sample rate
            channels: Number of audio channels
            meeting_id: Optional meeting ID for segment storage
            on_segment: Callback for each transcribed segment (segment, language)
            on_complete: Callback when transcription is fully complete
            on_error: Callback on error
            
        Returns:
            True if started successfully
        """
        with self._lock:
            if self._is_active:
                self._logger.warning("Live transcription already active")
                return False
            
            self._samplerate = samplerate
            self._channels = channels
            self._meeting_id = meeting_id
            self._on_segment = on_segment
            self._on_complete = on_complete
            self._on_error = on_error
            
            self._stop_requested.clear()
            self._capture_stopped = False
            self._transcription_complete = False
            self._last_language = None
            
            # Clear queues
            while not self._chunk_queue.empty():
                try:
                    self._chunk_queue.get_nowait()
                except queue.Empty:
                    break
            while not self._segment_queue.empty():
                try:
                    self._segment_queue.get_nowait()
                except queue.Empty:
                    break
            
            # Enable live tap
            self._audio_service.enable_live_tap()
            
            # Start real-time diarization if available
            rt_active = False
            if self._realtime_diarization:
                rt_active = self._realtime_diarization.start(samplerate, channels)
            
            # Start threads
            self._accumulator_thread = threading.Thread(
                target=self._accumulator_loop,
                daemon=True,
                name="live-transcription-accumulator",
            )
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                daemon=True,
                name="live-transcription-worker",
            )
            
            self._is_active = True
            self._accumulator_thread.start()
            self._worker_thread.start()
            
            self._logger.info(
                "Live transcription started: samplerate=%s channels=%s chunk_seconds=%.1f rt_diarization=%s",
                samplerate,
                channels,
                self._chunk_seconds,
                rt_active,
            )
            
            return True

    def request_stop(self) -> dict:
        """Request stop - returns immediately, transcription continues in background.
        
        Returns:
            Status dict with capture_stopped and transcription_pending flags
        """
        with self._lock:
            if not self._is_active:
                return {
                    "status": "not_active",
                    "capture_stopped": True,
                    "transcription_pending": False,
                }
            
            self._stop_requested.set()
            self._audio_service.signal_capture_stopped()
            
            self._logger.info("Stop requested - capture will stop, transcription continues")
            
            return {
                "status": "stopping",
                "capture_stopped": True,
                "transcription_pending": not self._transcription_complete,
            }

    def get_status(self) -> dict:
        """Get current transcription status."""
        with self._lock:
            pending_chunks = self._chunk_queue.qsize()
            
            if not self._is_active:
                status = "inactive"
            elif self._transcription_complete:
                status = "complete"
            elif self._capture_stopped:
                status = "finishing"
            else:
                status = "transcribing"
            
            return {
                "status": status,
                "capture_stopped": self._capture_stopped,
                "transcription_complete": self._transcription_complete,
                "chunks_pending": pending_chunks,
            }

    def is_active(self) -> bool:
        """Check if live transcription is active."""
        with self._lock:
            return self._is_active

    def is_complete(self) -> bool:
        """Check if transcription is fully complete."""
        with self._lock:
            return self._transcription_complete

    def get_next_segment(self, timeout: float = 0.5) -> Optional[TranscriptionSegment]:
        """Get next transcribed segment from queue.
        
        Args:
            timeout: How long to wait for a segment
            
        Returns:
            TranscriptionSegment or None if queue empty/timeout
        """
        try:
            return self._segment_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _accumulator_loop(self) -> None:
        """Accumulates audio chunks and queues them for transcription."""
        bytes_per_second = self._samplerate * self._channels * 2  # int16
        chunk_threshold = int(bytes_per_second * self._chunk_seconds)
        buffer = bytearray()
        offset_seconds = 0.0
        
        self._logger.debug(
            "Accumulator started: chunk_threshold=%d bytes (%.1f sec)",
            chunk_threshold,
            self._chunk_seconds,
        )
        
        try:
            while not self._stop_requested.is_set():
                # Check if still recording
                if not self._audio_service.is_recording():
                    # Recording stopped externally, drain remaining
                    break
                
                # Get audio chunk
                chunk = self._audio_service.get_live_chunk(timeout=0.5)
                if chunk:
                    buffer.extend(chunk)
                
                # Check if we have enough for a transcription chunk
                if len(buffer) >= chunk_threshold:
                    audio_bytes = bytes(buffer)
                    self._queue_chunk(audio_bytes, offset_seconds, is_final=False)
                    offset_seconds += len(buffer) / bytes_per_second
                    buffer.clear()
            
            # Stop requested or recording ended - drain remaining audio
            self._capture_stopped = True
            self._logger.debug("Accumulator draining remaining audio")
            
            # Get any remaining audio from the live queue
            remaining = self._audio_service.drain_live_queue()
            if remaining:
                buffer.extend(remaining)
            
            # Queue final chunk if we have any buffered audio
            if buffer:
                audio_bytes = bytes(buffer)
                self._queue_chunk(audio_bytes, offset_seconds, is_final=True)
                self._logger.debug(
                    "Queued final chunk: %.2f seconds",
                    len(buffer) / bytes_per_second,
                )
            else:
                # No remaining audio, still need to signal completion
                self._queue_chunk(b"", offset_seconds, is_final=True)
            
        except Exception as exc:
            self._logger.exception("Accumulator error: %s", exc)
            if self._on_error:
                self._on_error(exc)
        finally:
            self._capture_stopped = True
            self._logger.debug("Accumulator loop ended")

    def _queue_chunk(self, audio_bytes: bytes, offset_seconds: float, is_final: bool) -> None:
        """Queue a chunk for transcription."""
        chunk = TranscriptionChunk(
            audio_bytes=audio_bytes,
            offset_seconds=offset_seconds,
            is_final=is_final,
        )
        try:
            self._chunk_queue.put(chunk, timeout=5.0)
        except queue.Full:
            self._logger.warning("Chunk queue full, dropping chunk")

    def _worker_loop(self) -> None:
        """Processes queued chunks through transcription."""
        self._logger.debug("Worker started")
        
        try:
            while True:
                # Get next chunk
                try:
                    chunk = self._chunk_queue.get(timeout=1.0)
                except queue.Empty:
                    # Check if we should exit
                    if self._capture_stopped and self._chunk_queue.empty():
                        break
                    continue
                
                # Process chunk
                if chunk.audio_bytes:
                    self._process_chunk(chunk)
                
                # Check if this was the final chunk
                if chunk.is_final:
                    self._logger.debug("Final chunk processed")
                    break
                    
        except Exception as exc:
            self._logger.exception("Worker error: %s", exc)
            if self._on_error:
                self._on_error(exc)
        finally:
            self._finalize()

    def _process_chunk(self, chunk: TranscriptionChunk) -> None:
        """Process a single audio chunk through transcription."""
        temp_path = None
        
        try:
            # Write audio to temp file
            temp_path = self._write_temp_wav(chunk.audio_bytes)
            
            # Feed audio to real-time diarization if active
            if self._realtime_diarization and self._realtime_diarization.is_active():
                self._realtime_diarization.feed_audio(chunk.audio_bytes)
            
            # Transcribe
            segments, language, _ = self._pipeline.transcribe_chunk(
                temp_path,
                chunk.offset_seconds,
            )
            
            if language:
                self._last_language = language
            
            # Emit segments
            for segment in segments:
                # Try to get speaker from real-time diarization
                if self._realtime_diarization and self._realtime_diarization.is_active():
                    speaker = self._realtime_diarization.get_speaker_at(segment["start"])
                    if speaker:
                        segment["speaker"] = speaker
                
                # Queue segment
                self._segment_queue.put(TranscriptionSegment(
                    segment=segment,
                    language=self._last_language,
                ))
                
                # Call callback
                if self._on_segment:
                    self._on_segment(segment, self._last_language)
                    
        except Exception as exc:
            self._logger.warning("Chunk processing error: %s", exc)
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def _write_temp_wav(self, audio_bytes: bytes) -> str:
        """Write audio bytes to a temporary WAV file."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        
        audio = np.frombuffer(audio_bytes, dtype=np.int16)
        if self._channels > 1:
            audio = audio.reshape(-1, self._channels)
        
        with sf.SoundFile(
            tmp_path,
            mode="w",
            samplerate=self._samplerate,
            channels=self._channels,
            subtype="PCM_16",
        ) as f:
            f.write(audio)
        
        return tmp_path

    def _finalize(self) -> None:
        """Finalize transcription - cleanup and callbacks."""
        with self._lock:
            # Stop real-time diarization
            if self._realtime_diarization and self._realtime_diarization.is_active():
                final_annotations = self._realtime_diarization.stop()
                self._logger.info(
                    "Real-time diarization stopped: %d annotations",
                    len(final_annotations),
                )
            
            # Disable live tap
            self._audio_service.disable_live_tap()
            
            self._transcription_complete = True
            self._is_active = False
            
            self._logger.info("Live transcription complete")
            
            # Call completion callback
            if self._on_complete:
                try:
                    self._on_complete()
                except Exception as exc:
                    self._logger.warning("Completion callback error: %s", exc)
