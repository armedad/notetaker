import os
import queue
import subprocess
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, TYPE_CHECKING

import logging
import sounddevice as sd
import soundfile as sf
import numpy as np

from app.services.file_read_service import FileReadService
from app.services.ndjson_debug import dbg as nd_dbg

if TYPE_CHECKING:
    from app.services.meeting_store import MeetingStore


@dataclass
class RecordingState:
    recording_id: Optional[str] = None
    started_at: Optional[datetime] = None
    file_path: Optional[str] = None
    samplerate: Optional[int] = None
    channels: Optional[int] = None
    dtype: Optional[str] = None


class AudioCaptureService:
    def __init__(self, ctx) -> None:
        self._ctx = ctx
        self._state = RecordingState()
        self._lock = threading.RLock()
        self._audio_queue: "queue.Queue[bytes]" = queue.Queue()
        # #region agent log
        # Increased from 60 to 200 to handle Diart initialization delay (~5s)
        # At 4096 blocksize / 48kHz = ~85ms per callback, 200 slots = ~17s buffer
        # #endregion
        self._live_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=200)
        self._writer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._capture_stopped = threading.Event()  # Signals capture has stopped but transcription may continue
        self._stream: Optional[sd.RawInputStream] = None
        self._file_reader: Optional[FileReadService] = None
        self._logger = logging.getLogger("notetaker.audio")
        self._callback_counter = 0
        self._first_callback_logged = False
        self._live_enabled = False
        self._config = {
            "device_index": None,
            "samplerate": 48000,
            "channels": 2,
        }
        self._meeting_id: Optional[str] = None
        self._meeting_store = None
        self._existing_audio_path: Optional[str] = None  # For resumed meetings
        self._compression_complete_event: Optional[threading.Event] = None  # Signals when compression/concatenation is done
        self._compression_result_path: Optional[str] = None  # Path to compressed audio after completion

    def list_devices(self) -> list[dict]:
        self._logger.debug("Listing audio input devices")
        devices = sd.query_devices()
        return [
            {
                "index": idx,
                "name": device["name"],
                "max_input_channels": device["max_input_channels"],
                "default_samplerate": device["default_samplerate"],
            }
            for idx, device in enumerate(devices)
            if device["max_input_channels"] > 0
        ]

    def get_device(self, device_index: int) -> dict:
        device_info = sd.query_devices(device_index)
        return {
            "index": device_index,
            "name": device_info["name"],
            "max_input_channels": int(device_info.get("max_input_channels", 0)),
            "default_samplerate": int(device_info.get("default_samplerate", 0)),
        }

    def is_recording(self) -> bool:
        with self._lock:
            return self._state.recording_id is not None

    def is_capture_stopped(self) -> bool:
        """Check if audio capture has stopped (but transcription may still be processing)."""
        return self._capture_stopped.is_set()
    
    def has_buffered_audio(self) -> bool:
        """Check if there is audio buffered in the live queue."""
        return not self._live_queue.empty()

    def set_meeting_context(
        self,
        meeting_id: str,
        meeting_store,
        existing_audio_path: Optional[str] = None,
    ) -> None:
        """Set the meeting context for audio level publishing and compression.
        
        Args:
            meeting_id: The meeting ID
            meeting_store: The MeetingStore instance
            existing_audio_path: For resumed meetings, path to existing audio to concatenate with
        """
        with self._lock:
            self._meeting_id = meeting_id
            self._meeting_store = meeting_store
            self._existing_audio_path = existing_audio_path

    def clear_meeting_context(self) -> None:
        """Clear the meeting context."""
        with self._lock:
            self._meeting_id = None
            self._meeting_store = None
            self._existing_audio_path = None

    def enable_live_tap(self) -> None:
        with self._lock:
            self._logger.debug("Live tap enabled")
            self._live_enabled = True
            # #region agent log
            was_stopped = self._capture_stopped.is_set()
            self._logger.debug("ENABLE_LIVE_TAP: was_stopped_before_clear=%s", was_stopped)
            # #endregion
            self._capture_stopped.clear()
            # Debug: visible output
            print(f"[RESUME-DBG] enable_live_tap() called: _live_enabled={self._live_enabled} capture_stopped_was={was_stopped}")

    def disable_live_tap(self) -> None:
        with self._lock:
            self._logger.debug("Live tap disabled")
            self._live_enabled = False
            while not self._live_queue.empty():
                try:
                    self._live_queue.get_nowait()
                except queue.Empty:
                    break

    def signal_capture_stopped(self) -> None:
        """Signal that audio capture has stopped. Call this when user requests stop."""
        # #region agent log
        import traceback as _tb
        self._logger.debug("SIGNAL_CAPTURE_STOPPED: stack=%s", _tb.format_stack()[-5:])
        # #endregion
        self._capture_stopped.set()
        self._logger.debug("Capture stopped signal set")

    def get_live_chunk(self, timeout: float = 0.5) -> Optional[bytes]:
        # #region agent log
        qsize = self._live_queue.qsize()
        self._logger.debug("GET_LIVE_CHUNK_ENTER: queue_size=%d live_enabled=%s", qsize, self._live_enabled)
        # #endregion
        try:
            chunk = self._live_queue.get(timeout=timeout)
            # #region agent log
            self._logger.debug("GET_LIVE_CHUNK_GOT: chunk_len=%d", len(chunk) if chunk else 0)
            # #endregion
            return chunk
        except queue.Empty:
            # #region agent log
            self._logger.debug("GET_LIVE_CHUNK_EMPTY: queue_size=%d", self._live_queue.qsize())
            # #endregion
            return None

    def drain_live_queue(self) -> bytes:
        """Drain all remaining audio from the live queue.
        
        Call this after capture stops to get any buffered audio that
        should still be transcribed.
        
        Returns:
            Concatenated bytes of all remaining audio chunks
        """
        chunks = []
        while True:
            try:
                chunk = self._live_queue.get_nowait()
                chunks.append(chunk)
            except queue.Empty:
                break
        
        total_bytes = sum(len(c) for c in chunks)
        self._logger.debug("Drained live queue: %d chunks, %d bytes", len(chunks), total_bytes)
        return b"".join(chunks)

    def current_status(self) -> dict:
        with self._lock:
            self._logger.debug("Current status requested: %s", self._state)
            return {
                "recording": self._state.recording_id is not None,
                "recording_id": self._state.recording_id,
                "started_at": self._state.started_at.isoformat()
                if self._state.started_at
                else None,
                "file_path": self._state.file_path,
                "samplerate": self._state.samplerate,
                "channels": self._state.channels,
                "dtype": self._state.dtype,
            }

    def start_recording(
        self,
        device_index: int,
        samplerate: int = 48000,
        channels: int = 2,
    ) -> dict:
        with self._lock:
            nd_dbg(
                "app/services/audio_capture.py:start_recording",
                "mic_start_enter",
                {"device_index": device_index, "samplerate": samplerate, "channels": channels},
                run_id="pre-fix",
                hypothesis_id="M1",
            )
            self._logger.debug(
                "Start request: device=%s samplerate=%s channels=%s",
                device_index,
                samplerate,
                channels,
            )
            self._config.update(
                {
                    "device_index": device_index,
                    "samplerate": samplerate,
                    "channels": channels,
                }
            )
            # Pre-import numpy on the main thread to avoid callback-thread import crash on macOS.
            _ = np.__version__
            self._first_callback_logged = False
            if self._state.recording_id is not None:
                self._logger.warning("Start requested while already recording")
                raise RuntimeError("Recording already in progress")

            try:
                device_info = sd.query_devices(device_index)
            except Exception as exc:
                self._logger.exception("Invalid audio device index: %s", device_index)
                nd_dbg(
                    "app/services/audio_capture.py:start_recording",
                    "mic_device_query_error",
                    {"exc_type": type(exc).__name__, "exc_str": str(exc)[:800]},
                    run_id="pre-fix",
                    hypothesis_id="M1",
                )
                raise RuntimeError("Invalid audio device index") from exc

            self._logger.debug("Device info: %s", device_info)
            nd_dbg(
                "app/services/audio_capture.py:start_recording",
                "mic_device_info",
                {
                    "name": str(device_info.get("name")),
                    "max_input_channels": int(device_info.get("max_input_channels", 0)),
                    "default_samplerate": float(device_info.get("default_samplerate", 0.0)),
                },
                run_id="pre-fix",
                hypothesis_id="M1",
            )
            max_channels = int(device_info.get("max_input_channels", 0))
            if max_channels < 1:
                raise RuntimeError("Selected device has no input channels")
            if channels < 1 or channels > max_channels:
                raise RuntimeError(
                    f"Invalid channel count for device (max {max_channels})"
                )
            if samplerate <= 0:
                samplerate = int(device_info.get("default_samplerate", 48000))

            self._logger.debug(
                "Selected device: name=%s max_channels=%s default_samplerate=%s",
                device_info.get("name"),
                max_channels,
                device_info.get("default_samplerate"),
            )

            sd.default.device = device_index
            sd.default.samplerate = samplerate
            sd.default.channels = channels

            os.makedirs(self._ctx.recordings_dir, exist_ok=True)
            recording_id = str(uuid.uuid4())
            
            # Use Opus format directly if available, otherwise fall back to WAV
            from app.services.opus_writer import is_opus_recording_available
            use_direct_opus = is_opus_recording_available()
            file_ext = ".opus" if use_direct_opus else ".wav"
            filename = f"{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}-{recording_id}{file_ext}"
            file_path = os.path.join(self._ctx.recordings_dir, filename)
            
            # Notify if falling back to WAV (PyOgg not available)
            if not use_direct_opus and self._meeting_store and self._meeting_id:
                self._meeting_store.publish_event(
                    "recording_warning",
                    self._meeting_id,
                    {
                        "warning": "pyogg_unavailable",
                        "message": "PyOgg library not available. Recording to WAV format (will convert to Opus after recording, adding ~5-15s delay before finalization).",
                    }
                )

            self._state = RecordingState(
                recording_id=recording_id,
                started_at=datetime.utcnow(),
                file_path=file_path,
                samplerate=samplerate,
                channels=channels,
                dtype="int16",
            )

            self._logger.info(
                "Recording start: id=%s device=%s samplerate=%s channels=%s file=%s (direct_opus=%s)",
                recording_id,
                device_index,
                samplerate,
                channels,
                file_path,
                is_opus_recording_available(),
            )

            self._stop_event.clear()
            self._capture_stopped.clear()
            self._writer_thread = threading.Thread(
                target=self._writer_loop, daemon=True
            )
            self._writer_thread.start()
            self._logger.debug("Writer thread started")
            nd_dbg(
                "app/services/audio_capture.py:start_recording",
                "mic_writer_thread_started",
                {"file_path": file_path},
                run_id="pre-fix",
                hypothesis_id="M4",
            )

            try:
                self._logger.debug("Opening RawInputStream (dtype=int16)")
                nd_dbg(
                    "app/services/audio_capture.py:start_recording",
                    "mic_stream_opening",
                    {"dtype": "int16"},
                    run_id="pre-fix",
                    hypothesis_id="M2",
                )
                self._stream = sd.RawInputStream(
                    device=device_index,
                    samplerate=samplerate,
                    channels=channels,
                    dtype="int16",
                    # Avoid tiny callback blocks (e.g. 512 frames) that can overwhelm live queue.
                    blocksize=4096,
                    callback=self._audio_callback,
                )
                self._logger.debug("Starting RawInputStream")
                self._stream.start()
                self._logger.info("RawInputStream started")
                nd_dbg(
                    "app/services/audio_capture.py:start_recording",
                    "mic_stream_started",
                    {"ok": True},
                    run_id="pre-fix",
                    hypothesis_id="M2",
                )
            except Exception as exc:
                self._logger.exception("Failed to start audio stream: %s", exc)
                nd_dbg(
                    "app/services/audio_capture.py:start_recording",
                    "mic_stream_start_error",
                    {"exc_type": type(exc).__name__, "exc_str": str(exc)[:800]},
                    run_id="pre-fix",
                    hypothesis_id="M2",
                )
                self._stop_event.set()
                if self._writer_thread is not None:
                    self._writer_thread.join(timeout=5)
                    self._writer_thread = None
                self._state = RecordingState()
                raise

            return self.current_status()

    def get_config(self) -> dict:
        with self._lock:
            return dict(self._config)

    def update_config(
        self,
        device_index: Optional[int],
        samplerate: Optional[int],
        channels: Optional[int],
    ) -> None:
        with self._lock:
            if device_index is not None:
                self._config["device_index"] = device_index
            if samplerate is not None:
                self._config["samplerate"] = samplerate
            if channels is not None:
                self._config["channels"] = channels

    def stop_recording(self) -> dict:
        with self._lock:
            self._logger.debug("Stop request received")
            if self._state.recording_id is None:
                self._logger.warning("Stop requested with no active recording")
                raise RuntimeError("No recording in progress")

            if self._stream is not None:
                self._logger.debug("Stopping InputStream")
                self._stream.stop()
                self._stream.close()
                self._stream = None
                self._logger.debug("InputStream stopped")

            if self._file_reader is not None:
                self._logger.debug("Stopping FileReadService")
                self._file_reader.stop()
                self._file_reader = None
                self._logger.debug("FileReadService stopped")

            self._stop_event.set()
            if self._writer_thread is not None:
                self._logger.debug(
                    "Waiting for writer thread (queue size=%s)",
                    self._audio_queue.qsize(),
                )
                self._writer_thread.join(timeout=5)
                if self._writer_thread.is_alive():
                    self._logger.warning("Writer thread still running after timeout")
                self._writer_thread = None
                self._logger.debug("Writer thread stopped")

            final_state = self.current_status()
            self._logger.info("Recording stop: id=%s file=%s", final_state["recording_id"], final_state["file_path"])

            # Capture meeting context before clearing for compression callback
            meeting_id = self._meeting_id
            meeting_store = self._meeting_store
            existing_audio_path = self._existing_audio_path
            audio_path = final_state.get("file_path")

            # Clear meeting context for audio level publishing
            self._meeting_id = None
            self._meeting_store = None
            self._existing_audio_path = None

            self._state = RecordingState()
            
            # Handle audio file finalization
            if audio_path and os.path.isfile(audio_path):
                if audio_path.endswith(".opus"):
                    # Direct Opus recording - file is already in final format
                    if existing_audio_path and os.path.isfile(existing_audio_path):
                        # Resumed meeting: need to concatenate existing + new opus
                        self._concat_opus_async(existing_audio_path, audio_path, meeting_id, meeting_store)
                    else:
                        # Normal recording: Opus file is ready immediately
                        self._compression_result_path = audio_path
                        if meeting_id and meeting_store:
                            meeting_store.update_audio_path(meeting_id, audio_path)
                            self._logger.info(
                                "Direct Opus recording complete: meeting=%s opus=%s",
                                meeting_id, audio_path
                            )
                        # Signal completion immediately since no conversion needed
                        if self._compression_complete_event is None:
                            self._compression_complete_event = threading.Event()
                        self._compression_complete_event.set()
                else:
                    # WAV fallback - need to compress to Opus (non-blocking)
                    # For resumed meetings, this will concatenate existing + new audio
                    self._compress_to_opus_async(audio_path, meeting_id, meeting_store, existing_audio_path)
            
            return final_state

    def _compress_to_opus_async(
        self,
        wav_path: str,
        meeting_id: Optional[str],
        meeting_store: Optional["MeetingStore"],
        existing_audio_path: Optional[str] = None,
    ) -> threading.Event:
        """Start background thread to compress WAV to Opus.
        
        If existing_audio_path is provided (resumed meeting), concatenates
        existing audio with new wav before compressing to opus.
        
        Returns:
            threading.Event that is set when compression completes.
            The result path can be retrieved via get_compression_result().
        """
        # Create event for this compression operation
        completion_event = threading.Event()
        self._compression_complete_event = completion_event
        self._compression_result_path = None
        
        # #region agent log
        import json as _json_c; import time as _time_c
        try:
            with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f:
                _f.write(_json_c.dumps({"location":"audio_capture.py:_compress_to_opus_async:entry","message":"Starting compression","data":{"meeting_id":meeting_id,"wav_path":wav_path,"existing_audio_path":existing_audio_path,"is_resumed":bool(existing_audio_path)},"timestamp":int(_time_c.time()*1000),"hypothesisId":"A,D"})+"\n")
        except: pass
        # #endregion
        
        def _compress():
            try:
                # #region agent log
                try:
                    with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f:
                        _f.write(_json_c.dumps({"location":"audio_capture.py:_compress:thread_start","message":"Compression thread started","data":{"meeting_id":meeting_id,"existing_audio_path":existing_audio_path,"existing_exists":os.path.isfile(existing_audio_path) if existing_audio_path else False},"timestamp":int(_time_c.time()*1000),"hypothesisId":"D"})+"\n")
                except: pass
                # #endregion
                
                if existing_audio_path and os.path.isfile(existing_audio_path):
                    # Resumed meeting: concatenate existing + new, then compress
                    # #region agent log
                    try:
                        with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f:
                            _f.write(_json_c.dumps({"location":"audio_capture.py:_compress:before_concat","message":"About to concatenate","data":{"meeting_id":meeting_id,"existing_audio_path":existing_audio_path,"wav_path":wav_path},"timestamp":int(_time_c.time()*1000),"hypothesisId":"D"})+"\n")
                    except: pass
                    # #endregion
                    opus_path = self._concat_and_compress(existing_audio_path, wav_path)
                    # #region agent log
                    try:
                        with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f:
                            _f.write(_json_c.dumps({"location":"audio_capture.py:_compress:after_concat","message":"Concatenation returned","data":{"meeting_id":meeting_id,"opus_path":opus_path,"opus_exists":os.path.isfile(opus_path) if opus_path else False},"timestamp":int(_time_c.time()*1000),"hypothesisId":"D"})+"\n")
                    except: pass
                    # #endregion
                    self._logger.info(
                        "Audio concatenation complete: meeting=%s existing=%s new=%s -> %s",
                        meeting_id, existing_audio_path, wav_path, opus_path
                    )
                else:
                    # Normal single-file compression
                    opus_path = self._convert_wav_to_opus(wav_path)
                
                if opus_path and meeting_id and meeting_store:
                    # #region agent log
                    try:
                        with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f:
                            _f.write(_json_c.dumps({"location":"audio_capture.py:_compress:before_update_path","message":"About to update audio_path","data":{"meeting_id":meeting_id,"opus_path":opus_path},"timestamp":int(_time_c.time()*1000),"hypothesisId":"B"})+"\n")
                    except: pass
                    # #endregion
                    meeting_store.update_audio_path(meeting_id, opus_path)
                    # #region agent log
                    try:
                        with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f:
                            _f.write(_json_c.dumps({"location":"audio_capture.py:_compress:after_update_path","message":"audio_path updated","data":{"meeting_id":meeting_id,"opus_path":opus_path},"timestamp":int(_time_c.time()*1000),"hypothesisId":"B"})+"\n")
                    except: pass
                    # #endregion
                    self._logger.info(
                        "Opus compression complete: meeting=%s opus=%s",
                        meeting_id, opus_path
                    )
                    # Store result path for retrieval
                    self._compression_result_path = opus_path
                    # Delete original WAV after successful compression
                    try:
                        os.remove(wav_path)
                        self._logger.debug("Deleted original WAV: %s", wav_path)
                    except OSError as e:
                        self._logger.warning("Failed to delete WAV %s: %s", wav_path, e)
            except Exception as exc:
                # #region agent log
                try:
                    with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f:
                        _f.write(_json_c.dumps({"location":"audio_capture.py:_compress:exception","message":"Compression failed","data":{"meeting_id":meeting_id,"exc_type":type(exc).__name__,"exc_str":str(exc)[:500]},"timestamp":int(_time_c.time()*1000),"hypothesisId":"D"})+"\n")
                except: pass
                # #endregion
                self._logger.error(
                    "Opus compression failed for %s: %s (keeping WAV)",
                    wav_path, exc
                )
                # On failure, result path is the original WAV
                self._compression_result_path = wav_path
            finally:
                # #region agent log
                try:
                    with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f:
                        _f.write(_json_c.dumps({"location":"audio_capture.py:_compress:finally","message":"Setting completion event","data":{"meeting_id":meeting_id,"result_path":self._compression_result_path},"timestamp":int(_time_c.time()*1000),"hypothesisId":"A"})+"\n")
                except: pass
                # #endregion
                # Always signal completion, even on failure
                completion_event.set()
                self._logger.debug("Compression complete event set")
        
        thread = threading.Thread(target=_compress, name="opus-compress", daemon=True)
        thread.start()
        return completion_event
    
    def wait_for_compression(self, timeout: Optional[float] = None) -> Optional[str]:
        """Wait for the background compression to complete.
        
        Args:
            timeout: Maximum time to wait in seconds. None means wait forever.
            
        Returns:
            Path to the compressed audio file, or None if no compression is pending
            or if timeout expired.
        """
        # #region agent log
        import json as _json_w; import time as _time_w
        try:
            with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f:
                _f.write(_json_w.dumps({"location":"audio_capture.py:wait_for_compression:entry","message":"Wait called","data":{"timeout":timeout,"event_exists":self._compression_complete_event is not None,"event_is_set":self._compression_complete_event.is_set() if self._compression_complete_event else None},"timestamp":int(_time_w.time()*1000),"hypothesisId":"A"})+"\n")
        except: pass
        # #endregion
        
        if self._compression_complete_event is None:
            # #region agent log
            try:
                with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f:
                    _f.write(_json_w.dumps({"location":"audio_capture.py:wait_for_compression:no_event","message":"No compression event exists","data":{},"timestamp":int(_time_w.time()*1000),"hypothesisId":"A"})+"\n")
            except: pass
            # #endregion
            return None
        
        completed = self._compression_complete_event.wait(timeout=timeout)
        # #region agent log
        try:
            with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f:
                _f.write(_json_w.dumps({"location":"audio_capture.py:wait_for_compression:after_wait","message":"Wait returned","data":{"completed":completed,"result_path":self._compression_result_path},"timestamp":int(_time_w.time()*1000),"hypothesisId":"A"})+"\n")
        except: pass
        # #endregion
        if completed:
            return self._compression_result_path
        else:
            self._logger.warning("Compression wait timed out after %s seconds", timeout)
            return None
    
    def is_compression_pending(self) -> bool:
        """Check if there's a compression operation in progress."""
        if self._compression_complete_event is None:
            return False
        return not self._compression_complete_event.is_set()
    
    def _concat_opus_async(
        self,
        existing_opus_path: str,
        new_opus_path: str,
        meeting_id: Optional[str],
        meeting_store: Optional["MeetingStore"],
    ) -> threading.Event:
        """Start background thread to concatenate two Opus files.
        
        Used when resuming a meeting with direct Opus recording.
        The result overwrites the existing opus file.
        
        Returns:
            threading.Event that is set when concatenation completes.
        """
        completion_event = threading.Event()
        self._compression_complete_event = completion_event
        self._compression_result_path = None
        
        def _concat():
            try:
                output_path = self._concat_opus_files(existing_opus_path, new_opus_path)
                
                if output_path and meeting_id and meeting_store:
                    meeting_store.update_audio_path(meeting_id, output_path)
                    self._logger.info(
                        "Opus concatenation complete: meeting=%s opus=%s",
                        meeting_id, output_path
                    )
                    self._compression_result_path = output_path
                    
                    # Delete the new opus file after successful concatenation
                    try:
                        os.remove(new_opus_path)
                        self._logger.debug("Deleted new Opus segment: %s", new_opus_path)
                    except OSError as e:
                        self._logger.warning("Failed to delete new Opus %s: %s", new_opus_path, e)
            except Exception as exc:
                self._logger.error(
                    "Opus concatenation failed for %s + %s: %s (keeping both files)",
                    existing_opus_path, new_opus_path, exc
                )
                # On failure, result path is the new opus file
                self._compression_result_path = new_opus_path
            finally:
                completion_event.set()
                self._logger.debug("Opus concatenation complete event set")
        
        thread = threading.Thread(target=_concat, name="opus-concat", daemon=True)
        thread.start()
        return completion_event
    
    def _concat_opus_files(self, existing_path: str, new_path: str) -> str:
        """Concatenate two Opus files using ffmpeg.
        
        Args:
            existing_path: Path to existing Opus file
            new_path: Path to new Opus file to append
            
        Returns:
            Path to the output opus file (same as existing_path)
        """
        output_path = existing_path
        
        # Use a temp file to avoid overwriting while reading
        temp_output = output_path.rsplit(".", 1)[0] + ".concat-temp.opus"
        
        # Concatenate opus files - simpler than mixed formats since both are opus
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-i", existing_path,
            "-i", new_path,
            "-filter_complex",
            "[0:a][1:a]concat=n=2:v=0:a=1[out]",
            "-map", "[out]",
            "-c:a", "libopus",
            "-b:a", "32k",
            "-application", "voip",
            "-vbr", "on",
            temp_output,
        ]
        
        self._logger.info(
            "Concatenating Opus files: %s + %s -> %s",
            os.path.basename(existing_path),
            os.path.basename(new_path),
            os.path.basename(output_path),
        )
        start_time = datetime.utcnow()
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=600,  # 10 min timeout for potentially long audio
            )
            
            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace")
                raise RuntimeError(f"ffmpeg opus concat failed: {stderr[-500:]}")
            
            # Replace original with temp
            os.replace(temp_output, output_path)
            
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            output_size = os.path.getsize(output_path)
            
            self._logger.info(
                "Opus concatenation complete: %.1fs, output %.1f MB",
                elapsed,
                output_size / 1024 / 1024,
            )
            
            return output_path
            
        except subprocess.TimeoutExpired:
            self._logger.error("ffmpeg timed out concatenating opus files")
            if os.path.exists(temp_output):
                os.remove(temp_output)
            raise
        except Exception:
            if os.path.exists(temp_output):
                os.remove(temp_output)
            raise
    
    def _concat_and_compress(self, existing_path: str, new_wav_path: str) -> str:
        """Concatenate existing audio with new WAV and compress to Opus.
        
        Uses ffmpeg's concat filter to handle mixed formats (opus + wav).
        The result overwrites the existing opus file.
        
        Args:
            existing_path: Path to existing audio file (opus or wav)
            new_wav_path: Path to new WAV file to append
            
        Returns:
            Path to the output opus file (same as existing_path but with .opus extension)
        """
        # Output path is the existing path but ensure .opus extension
        if existing_path.lower().endswith(".opus"):
            output_path = existing_path
        else:
            output_path = existing_path.rsplit(".", 1)[0] + ".opus"
        
        # Use a temp file to avoid overwriting while reading
        # Use .opus extension (not .tmp) so ffmpeg recognizes the output format
        temp_output = output_path.rsplit(".", 1)[0] + ".concat-temp.opus"
        
        # Use filter_complex to decode both inputs, normalize sample rates, and concat
        # The aformat filter ensures both streams have matching sample rate/channels
        # before concatenation (opus may have different rate than wav)
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-i", existing_path,
            "-i", new_wav_path,
            "-filter_complex",
            "[0:a]aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=mono[a0];"
            "[1:a]aformat=sample_fmts=s16:sample_rates=48000:channel_layouts=mono[a1];"
            "[a0][a1]concat=n=2:v=0:a=1[out]",
            "-map", "[out]",
            "-c:a", "libopus",
            "-b:a", "32k",
            "-application", "voip",
            "-vbr", "on",
            temp_output,
        ]
        
        self._logger.info(
            "Concatenating audio: %s + %s -> %s",
            os.path.basename(existing_path),
            os.path.basename(new_wav_path),
            os.path.basename(output_path),
        )
        # #region agent log
        import json as _json_cc; import time as _time_cc
        try:
            with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f:
                _f.write(_json_cc.dumps({"location":"audio_capture.py:_concat_and_compress:cmd","message":"ffmpeg command","data":{"cmd":" ".join(cmd),"existing_path":existing_path,"new_wav_path":new_wav_path},"timestamp":int(_time_cc.time()*1000),"hypothesisId":"D"})+"\n")
        except: pass
        # #endregion
        start_time = datetime.utcnow()
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=600,  # 10 min timeout for potentially long audio
            )
            
            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace")
                # #region agent log
                try:
                    with open("/Users/chee/zapier ai project/.cursor/debug.log", "a") as _f:
                        _f.write(_json_cc.dumps({"location":"audio_capture.py:_concat_and_compress:ffmpeg_error","message":"ffmpeg failed","data":{"returncode":result.returncode,"stderr_full":stderr[-2000:]},"timestamp":int(_time_cc.time()*1000),"hypothesisId":"D"})+"\n")
                except: pass
                # #endregion
                raise RuntimeError(f"ffmpeg concat failed: {stderr[-500:]}")
            
            # Replace original with temp
            os.replace(temp_output, output_path)
            
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            output_size = os.path.getsize(output_path)
            
            self._logger.info(
                "Audio concatenation complete: %.1fs, output %.1f MB",
                elapsed,
                output_size / 1024 / 1024,
            )
            
            return output_path
            
        except subprocess.TimeoutExpired:
            self._logger.error("ffmpeg timed out concatenating audio")
            # Clean up temp file if exists
            if os.path.exists(temp_output):
                os.remove(temp_output)
            raise
        except Exception as exc:
            # Clean up temp file if exists
            if os.path.exists(temp_output):
                os.remove(temp_output)
            raise

    def _convert_wav_to_opus(self, wav_path: str) -> Optional[str]:
        """Convert WAV file to Opus using ffmpeg.
        
        Uses Opus at 32kbps which is excellent for speech (85-90% smaller than WAV).
        
        Returns:
            Path to the Opus file, or None if conversion failed.
        """
        opus_path = wav_path.rsplit(".", 1)[0] + ".opus"
        
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-i", wav_path,
            "-c:a", "libopus",
            "-b:a", "32k",  # 32kbps is excellent for speech
            "-application", "voip",  # Optimized for speech
            "-vbr", "on",
            opus_path,
        ]
        
        self._logger.info("Converting to Opus: %s -> %s", wav_path, opus_path)
        start_time = datetime.utcnow()
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )
            
            if result.returncode != 0:
                self._logger.error(
                    "ffmpeg failed (code %d): %s",
                    result.returncode,
                    result.stderr[:500] if result.stderr else "no stderr"
                )
                return None
            
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            
            # Log size reduction
            wav_size = os.path.getsize(wav_path)
            opus_size = os.path.getsize(opus_path)
            reduction = (1 - opus_size / wav_size) * 100 if wav_size > 0 else 0
            
            self._logger.info(
                "Opus conversion complete: %.1fs, %.1f MB -> %.1f MB (%.0f%% smaller)",
                elapsed,
                wav_size / 1024 / 1024,
                opus_size / 1024 / 1024,
                reduction,
            )
            
            return opus_path
            
        except subprocess.TimeoutExpired:
            self._logger.error("ffmpeg timed out converting %s", wav_path)
            return None
        except FileNotFoundError:
            self._logger.error("ffmpeg not found - install ffmpeg to enable Opus compression")
            return None
        except Exception as exc:
            self._logger.exception("Opus conversion error: %s", exc)
            return None

    def start_file_playback(
        self,
        file_path: str,
        speed_percent: int = 300,
        samplerate: int = 48000,
        channels: int = 2,
    ) -> dict:
        """Start streaming audio from a file through the shared pipeline.

        Sets up the same infrastructure as start_recording() (recording ID,
        WAV output path, queues, writer thread, live tap) but uses
        FileReadService instead of sounddevice to produce raw PCM blocks.

        Returns the same dict shape as start_recording() / current_status().
        """
        with self._lock:
            self._first_callback_logged = False
            if self._state.recording_id is not None:
                raise RuntimeError("Recording already in progress")

            os.makedirs(self._ctx.recordings_dir, exist_ok=True)
            recording_id = str(uuid.uuid4())
            
            # Use Opus format directly if available, otherwise fall back to WAV
            from app.services.opus_writer import is_opus_recording_available
            use_direct_opus = is_opus_recording_available()
            file_ext = ".opus" if use_direct_opus else ".wav"
            filename = f"{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}-{recording_id}{file_ext}"
            output_path = os.path.join(self._ctx.recordings_dir, filename)
            
            # Notify if falling back to WAV (PyOgg not available)
            if not use_direct_opus and self._meeting_store and self._meeting_id:
                self._meeting_store.publish_event(
                    "recording_warning",
                    self._meeting_id,
                    {
                        "warning": "pyogg_unavailable",
                        "message": "PyOgg library not available. Recording to WAV format (will convert to Opus after recording, adding ~5-15s delay before finalization).",
                    }
                )

            self._state = RecordingState(
                recording_id=recording_id,
                started_at=datetime.utcnow(),
                file_path=output_path,
                samplerate=samplerate,
                channels=channels,
                dtype="int16",
            )

            self._logger.info(
                "File playback start: id=%s source=%s output=%s sr=%s ch=%s speed=%s%% (direct_opus=%s)",
                recording_id, os.path.basename(file_path), output_path,
                samplerate, channels, speed_percent, use_direct_opus,
            )

            self._stop_event.clear()
            self._capture_stopped.clear()
            self._callback_counter = 0

            self._writer_thread = threading.Thread(
                target=self._writer_loop, daemon=True
            )
            self._writer_thread.start()

            self._live_enabled = True

            self._file_reader = FileReadService(
                file_path,
                callback=self._audio_callback,
                samplerate=samplerate,
                channels=channels,
                blocksize=4096,
                speed_percent=speed_percent,
                on_complete=self._capture_stopped.set,
            )
            self._file_reader.start()

            return self.current_status()

    def _audio_callback(self, indata, frames, time, status) -> None:
        if status:
            self._logger.warning("Audio callback status: %s", status)
        self._callback_counter += 1
        if not self._first_callback_logged:
            self._logger.info("First audio callback received")
            self._first_callback_logged = True
            try:
                payload = bytes(indata)
                samples = np.frombuffer(payload, dtype=np.int16)
                # RMS as a quick “is this silent?” signal. Keep it lightweight (first callback only).
                rms = float(np.sqrt(np.mean((samples.astype(np.float32)) ** 2))) if samples.size else 0.0
                peak = int(np.max(np.abs(samples))) if samples.size else 0
            except Exception:
                rms = -1.0
                peak = -1
            nd_dbg(
                "app/services/audio_capture.py:_audio_callback",
                "mic_first_callback",
                {
                    "frames": int(frames),
                    "bytes": len(bytes(indata)),
                    "status_present": bool(status),
                    "rms_int16": round(rms, 2),
                    "peak_int16": peak,
                    "live_enabled": bool(self._live_enabled),
                },
                run_id="pre-fix",
                hypothesis_id="M3",
            )
        if self._callback_counter % 50 == 0:
            self._logger.debug("Audio callback frames=%s", frames)
        payload = bytes(indata)
        self._audio_queue.put(payload)
        # #region agent log
        if self._callback_counter <= 5:
            self._logger.debug("CALLBACK_LIVE_CHECK: callback_counter=%d live_enabled=%s payload_len=%d", 
                              self._callback_counter, self._live_enabled, len(payload))
            # Debug: visible output for audio callback
            print(f"[RESUME-DBG] Audio callback #{self._callback_counter}: live_enabled={self._live_enabled} payload={len(payload)}")
        # #endregion
        if self._live_enabled:
            try:
                self._live_queue.put_nowait(payload)
                # #region agent log
                if self._callback_counter <= 5:
                    self._logger.debug("CALLBACK_PUT_SUCCESS: callback_counter=%d queue_size=%d", 
                                      self._callback_counter, self._live_queue.qsize())
                # #endregion
            except queue.Full:
                if self._callback_counter % 100 == 0:
                    self._logger.warning("Live queue full; dropping chunk")
                    nd_dbg(
                        "app/services/audio_capture.py:_audio_callback",
                        "mic_live_queue_full_drop",
                        {"callback_counter": self._callback_counter, "live_queue_max": 200},
                        run_id="pre-fix",
                        hypothesis_id="M5",
                    )

        # Publish audio level for real-time meter (throttled to ~10-12 Hz)
        if self._callback_counter % 4 == 0 and self._meeting_store and self._meeting_id:
            try:
                samples = np.frombuffer(payload, dtype=np.int16)
                if samples.size:
                    rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
                    level = min(1.0, rms / 8000.0)
                    self._meeting_store.publish_event(
                        "audio_level",
                        self._meeting_id,
                        {"level": round(level, 3)}
                    )
            except Exception:
                pass  # Don't let meter errors affect recording

    def _writer_loop(self) -> None:
        file_path = self._state.file_path
        samplerate = self._state.samplerate
        channels = self._state.channels
        if not file_path or not samplerate or not channels:
            self._logger.error("Writer loop missing file path or audio parameters")
            nd_dbg(
                "app/services/audio_capture.py:_writer_loop",
                "mic_writer_missing_params",
                {"file_path_present": bool(file_path), "samplerate": samplerate, "channels": channels},
                run_id="pre-fix",
                hypothesis_id="M4",
            )
            return

        # Check if we should use direct Opus recording
        from app.services.opus_writer import is_opus_recording_available, OpusStreamWriter
        use_opus = is_opus_recording_available() and file_path.endswith(".opus")

        self._logger.debug("Writer loop start: %s (opus=%s)", file_path, use_opus)
        nd_dbg(
            "app/services/audio_capture.py:_writer_loop",
            "mic_writer_start",
            {"file_path": file_path, "samplerate": int(samplerate), "channels": int(channels), "use_opus": use_opus},
            run_id="pre-fix",
            hypothesis_id="M4",
        )

        if use_opus:
            self._writer_loop_opus(file_path, samplerate, channels)
        else:
            self._writer_loop_wav(file_path, samplerate, channels)

        self._logger.debug("Writer loop complete: %s", file_path)
        nd_dbg(
            "app/services/audio_capture.py:_writer_loop",
            "mic_writer_complete",
            {"file_path": file_path},
            run_id="pre-fix",
            hypothesis_id="M4",
        )

    def _writer_loop_opus(self, file_path: str, samplerate: int, channels: int) -> None:
        """Write audio directly to Opus format using OpusStreamWriter."""
        from app.services.opus_writer import OpusStreamWriter
        
        with OpusStreamWriter(file_path, sample_rate=samplerate, channels=channels) as writer:
            wrote_any = False
            while not self._stop_event.is_set() or not self._audio_queue.empty():
                try:
                    data = self._audio_queue.get(timeout=0.1)
                    writer.write(data)  # PCM bytes go directly to Opus encoder
                    if not wrote_any:
                        wrote_any = True
                        nd_dbg(
                            "app/services/audio_capture.py:_writer_loop_opus",
                            "mic_writer_first_write",
                            {"bytes": len(data)},
                            run_id="pre-fix",
                            hypothesis_id="M4",
                        )
                except queue.Empty:
                    continue
                except Exception as exc:
                    self._logger.exception("Failed to write audio data to Opus: %s", exc)
                    nd_dbg(
                        "app/services/audio_capture.py:_writer_loop_opus",
                        "mic_writer_error",
                        {"exc_type": type(exc).__name__, "exc_str": str(exc)[:800]},
                        run_id="pre-fix",
                        hypothesis_id="M4",
                    )
                    break

    def _writer_loop_wav(self, file_path: str, samplerate: int, channels: int) -> None:
        """Write audio to WAV format using soundfile (fallback if PyOgg unavailable)."""
        with sf.SoundFile(
            file_path,
            mode="w",
            samplerate=samplerate,
            channels=channels,
            subtype="PCM_16",
        ) as sound_file:
            wrote_any = False
            while not self._stop_event.is_set() or not self._audio_queue.empty():
                try:
                    data = self._audio_queue.get(timeout=0.1)
                    frames = np.frombuffer(data, dtype=np.int16)
                    if channels > 1:
                        frames = frames.reshape(-1, channels)
                    sound_file.write(frames)
                    if not wrote_any:
                        wrote_any = True
                        nd_dbg(
                            "app/services/audio_capture.py:_writer_loop_wav",
                            "mic_writer_first_write",
                            {"samples": int(frames.shape[0])},
                            run_id="pre-fix",
                            hypothesis_id="M4",
                        )
                except queue.Empty:
                    continue
                except Exception as exc:
                    self._logger.exception("Failed to write audio data to WAV: %s", exc)
                    nd_dbg(
                        "app/services/audio_capture.py:_writer_loop_wav",
                        "mic_writer_error",
                        {"exc_type": type(exc).__name__, "exc_str": str(exc)[:800]},
                        run_id="pre-fix",
                        hypothesis_id="M4",
                    )
                    break
