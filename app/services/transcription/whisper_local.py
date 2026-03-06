from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional, Union

import numpy as np

# Workaround for tqdm threading issue in huggingface_hub downloads
# This must be set before importing faster_whisper
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

from faster_whisper import WhisperModel

from app.services.transcription.base import (
    TranscriptSegment,
    TranscriptionProvider,
    TranscriptionProviderError,
    TranscriptionResult,
)
from app.services.diarization import DiarizationService


def _get_locally_installed_models() -> list[str]:
    """Return list of Whisper models that are fully downloaded locally.
    
    Checks the HuggingFace cache for Systran/faster-whisper-* models
    that have no .incomplete files (fully downloaded).
    """
    from pathlib import Path
    
    cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
    if not cache_dir.exists():
        return []
    
    installed = []
    for model_dir in cache_dir.glob("models--Systran--faster-whisper-*"):
        # Extract model name from directory (e.g., "models--Systran--faster-whisper-base.en" -> "base.en")
        dir_name = model_dir.name
        if not dir_name.startswith("models--Systran--faster-whisper-"):
            continue
        model_id = dir_name.replace("models--Systran--faster-whisper-", "")
        
        # Check if model is fully downloaded (no .incomplete files)
        blobs_dir = model_dir / "blobs"
        if blobs_dir.exists():
            incomplete_files = list(blobs_dir.glob("*.incomplete"))
            if not incomplete_files:
                installed.append(model_id)
    
    return sorted(installed)


def get_available_whisper_models() -> list[str]:
    """Return list of Whisper model IDs that are installed locally."""
    return _get_locally_installed_models()


def _load_whisper_model_metadata() -> dict[str, dict]:
    """Load whisper model metadata from data/whisper_models.json."""
    import json
    from pathlib import Path
    
    # Try data folder relative to app directory (deployed structure)
    app_dir = Path(__file__).parent.parent.parent  # app/services/transcription -> app
    data_path = app_dir.parent / "data" / "whisper_models.json"
    
    if data_path.exists():
        try:
            with open(data_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def get_whisper_model_info() -> dict[str, dict]:
    """Return model info for locally installed models only.
    
    Loads metadata from data/whisper_models.json and filters to only
    include models that are fully downloaded locally.
    """
    model_metadata = _load_whisper_model_metadata()
    installed = set(_get_locally_installed_models())
    return {
        model_id: info
        for model_id, info in model_metadata.items()
        if model_id in installed
    }


@dataclass(frozen=True)
class WhisperConfig:
    model_size: str = "base"
    device: str = "cpu"
    compute_type: str = "int8"


_dbg_logger = logging.getLogger("notetaker.debug")


class FasterWhisperProvider(TranscriptionProvider):
    def __init__(self, config: WhisperConfig, diarization: DiarizationService) -> None:
        self._config = config
        self._logger = logging.getLogger("notetaker.transcription.whisper")
        self._model: Optional[WhisperModel] = None
        self._diarization = diarization

    def _get_model(self) -> WhisperModel:
        if self._model is None:
            self._logger.info(
                "Loading whisper model: size=%s device=%s compute_type=%s",
                self._config.model_size,
                self._config.device,
                self._config.compute_type,
            )
            # #region agent log
            _dbg_logger.debug("WHISPER_MODEL_LOAD_START: size=%s device=%s compute_type=%s",
                            self._config.model_size, self._config.device, self._config.compute_type)
            _load_start = time.perf_counter()
            # #endregion
            # Check if we should only use local files (HF_HUB_OFFLINE mode)
            local_only = os.environ.get("HF_HUB_OFFLINE", "0") == "1"
            self._model = WhisperModel(
                self._config.model_size,
                device=self._config.device,
                compute_type=self._config.compute_type,
                local_files_only=local_only,
            )
            # #region agent log
            _load_elapsed = time.perf_counter() - _load_start
            _dbg_logger.debug("WHISPER_MODEL_LOAD_DONE: size=%s elapsed_sec=%.2f", self._config.model_size, _load_elapsed)
            # #endregion
        else:
            # #region agent log
            _dbg_logger.debug("WHISPER_MODEL_CACHED: size=%s", self._config.model_size)
            # #endregion
        return self._model

    def transcribe(self, audio_path: str) -> TranscriptionResult:
        if not os.path.exists(audio_path):
            raise TranscriptionProviderError("Audio file not found")

        start_time = time.perf_counter()
        model = self._get_model()

        try:
            segments_iter, info = model.transcribe(audio_path)
            segments: list[TranscriptSegment] = []
            for segment in segments_iter:
                segments.append(
                    TranscriptSegment(
                        start=float(segment.start),
                        end=float(segment.end),
                        text=segment.text.strip(),
                    )
                )
        except Exception as exc:
            self._logger.exception("Transcription failed: %s", exc)
            raise TranscriptionProviderError("Transcription failed") from exc

        if self._diarization.is_enabled():
            try:
                from app.services.audio_utils import load_audio_for_pyannote
                audio_dict = load_audio_for_pyannote(audio_path)
                diarization_segments = self._diarization.run(audio_dict)
                segments = _apply_diarization(segments, diarization_segments)
            except Exception as exc:
                self._logger.exception("Diarization failed: %s", exc)

        duration = time.perf_counter() - start_time
        self._logger.info(
            "Transcription complete: segments=%s duration=%.2fs",
            len(segments),
            duration,
        )

        return TranscriptionResult(
            language=getattr(info, "language", None),
            duration=duration,
            segments=segments,
        )

    def stream_segments(self, audio_source: Union[str, np.ndarray]):
        """Stream transcription segments from audio.
        
        Args:
            audio_source: Either a file path (str) or a numpy array of float32
                audio samples at 16kHz. Numpy arrays avoid temp file creation
                when transcribing from compressed formats like Opus.
        """
        if isinstance(audio_source, str):
            if not os.path.exists(audio_source):
                raise TranscriptionProviderError("Audio file not found")
            # #region agent log
            _dbg_logger.debug("WHISPER_STREAM_START: audio_path=%s", audio_source)
            # #endregion
        else:
            # #region agent log
            _dbg_logger.debug("WHISPER_STREAM_START: numpy_array shape=%s dtype=%s", audio_source.shape, audio_source.dtype)
            # #endregion

        model = self._get_model()
        # #region agent log
        _dbg_logger.debug("WHISPER_STREAM_GOT_MODEL: calling transcribe")
        _transcribe_start = time.perf_counter()
        # #endregion
        try:
            result = model.transcribe(audio_source)
            # #region agent log
            _transcribe_elapsed = time.perf_counter() - _transcribe_start
            _dbg_logger.debug("WHISPER_STREAM_TRANSCRIBE_RETURNED: elapsed_sec=%.2f", _transcribe_elapsed)
            # #endregion
            return result
        except Exception as exc:
            # #region agent log
            _dbg_logger.debug("WHISPER_STREAM_ERROR: exc_type=%s exc=%s", type(exc).__name__, str(exc)[:500])
            # #endregion
            self._logger.exception("Transcription stream failed: %s", exc)
            raise TranscriptionProviderError("Transcription failed") from exc

    def get_chunk_size(self) -> float:
        """Whisper uses a fixed 30-second encoder window.
        
        Smaller inputs are padded with silence to 30 seconds, so there's
        no benefit to using smaller chunks. Using 30 seconds minimizes
        the number of encoder passes and avoids wasted padding computation.
        """
        return 30.0


def _apply_diarization(
    segments: list[TranscriptSegment], diarization_segments: list[dict]
) -> list[TranscriptSegment]:
    if not diarization_segments:
        return segments
    diarization_segments = sorted(diarization_segments, key=lambda seg: seg["start"])
    result: list[TranscriptSegment] = []
    for segment in segments:
        speaker = None
        for diarization in diarization_segments:
            if diarization["start"] <= segment.start < diarization["end"]:
                speaker = diarization["speaker"]
                break
        result.append(
            TranscriptSegment(
                start=segment.start,
                end=segment.end,
                text=segment.text,
                speaker=speaker,
            )
        )
    return result
