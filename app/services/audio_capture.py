import os
import queue
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import logging
import sounddevice as sd
import soundfile as sf
import numpy as np


@dataclass
class RecordingState:
    recording_id: Optional[str] = None
    started_at: Optional[datetime] = None
    file_path: Optional[str] = None
    samplerate: Optional[int] = None
    channels: Optional[int] = None
    dtype: Optional[str] = None


class AudioCaptureService:
    def __init__(self, recordings_dir: str) -> None:
        self._recordings_dir = recordings_dir
        self._state = RecordingState()
        self._lock = threading.RLock()
        self._audio_queue: "queue.Queue[bytes]" = queue.Queue()
        self._live_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=60)
        self._writer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stream: Optional[sd.RawInputStream] = None
        self._logger = logging.getLogger("notetaker.audio")
        self._callback_counter = 0
        self._first_callback_logged = False
        self._live_enabled = False
        self._config = {
            "device_index": None,
            "samplerate": 48000,
            "channels": 2,
        }

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

    def enable_live_tap(self) -> None:
        with self._lock:
            self._logger.debug("Live tap enabled")
            self._live_enabled = True

    def disable_live_tap(self) -> None:
        with self._lock:
            self._logger.debug("Live tap disabled")
            self._live_enabled = False
            while not self._live_queue.empty():
                try:
                    self._live_queue.get_nowait()
                except queue.Empty:
                    break

    def get_live_chunk(self, timeout: float = 0.5) -> Optional[bytes]:
        try:
            return self._live_queue.get(timeout=timeout)
        except queue.Empty:
            return None

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
                raise RuntimeError("Invalid audio device index") from exc

            self._logger.debug("Device info: %s", device_info)
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

            os.makedirs(self._recordings_dir, exist_ok=True)
            recording_id = str(uuid.uuid4())
            filename = f"{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}-{recording_id}.wav"
            file_path = os.path.join(self._recordings_dir, filename)

            self._state = RecordingState(
                recording_id=recording_id,
                started_at=datetime.utcnow(),
                file_path=file_path,
                samplerate=samplerate,
                channels=channels,
                dtype="int16",
            )

            self._logger.info(
                "Recording start: id=%s device=%s samplerate=%s channels=%s file=%s",
                recording_id,
                device_index,
                samplerate,
                channels,
                file_path,
            )

            self._stop_event.clear()
            self._writer_thread = threading.Thread(
                target=self._writer_loop, daemon=True
            )
            self._writer_thread.start()
            self._logger.debug("Writer thread started")

            try:
                self._logger.debug("Opening RawInputStream (dtype=int16)")
                self._stream = sd.RawInputStream(
                    device=device_index,
                    samplerate=samplerate,
                    channels=channels,
                    dtype="int16",
                    callback=self._audio_callback,
                )
                self._logger.debug("Starting RawInputStream")
                self._stream.start()
                self._logger.info("RawInputStream started")
            except Exception as exc:
                self._logger.exception("Failed to start audio stream: %s", exc)
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

            self._state = RecordingState()
            return final_state

    def _audio_callback(self, indata, frames, time, status) -> None:
        if status:
            self._logger.warning("Audio callback status: %s", status)
        self._callback_counter += 1
        if not self._first_callback_logged:
            self._logger.info("First audio callback received")
            self._first_callback_logged = True
        if self._callback_counter % 50 == 0:
            self._logger.debug("Audio callback frames=%s", frames)
        payload = bytes(indata)
        self._audio_queue.put(payload)
        if self._live_enabled:
            try:
                self._live_queue.put_nowait(payload)
            except queue.Full:
                if self._callback_counter % 100 == 0:
                    self._logger.warning("Live queue full; dropping chunk")

    def _writer_loop(self) -> None:
        file_path = self._state.file_path
        samplerate = self._state.samplerate
        channels = self._state.channels
        if not file_path or not samplerate or not channels:
            self._logger.error("Writer loop missing file path or audio parameters")
            return

        self._logger.debug("Writer loop start: %s", file_path)

        with sf.SoundFile(
            file_path,
            mode="w",
            samplerate=samplerate,
            channels=channels,
            subtype="PCM_16",
        ) as sound_file:
            while not self._stop_event.is_set() or not self._audio_queue.empty():
                try:
                    data = self._audio_queue.get(timeout=0.1)
                    frames = np.frombuffer(data, dtype=np.int16)
                    if channels > 1:
                        frames = frames.reshape(-1, channels)
                    sound_file.write(frames)
                except queue.Empty:
                    continue
                except Exception as exc:
                    self._logger.exception("Failed to write audio data: %s", exc)
                    break

        self._logger.debug("Writer loop complete: %s", file_path)
