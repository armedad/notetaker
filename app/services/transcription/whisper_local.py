from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

# Workaround for tqdm threading issue in huggingface_hub downloads
# This must be set before importing faster_whisper
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

from faster_whisper import WhisperModel, available_models

from app.services.transcription.base import (
    TranscriptSegment,
    TranscriptionProvider,
    TranscriptionProviderError,
    TranscriptionResult,
)
from app.services.diarization import DiarizationService


# Static registry of Whisper model metadata for UI display
# Models are grouped by category for better organization
WHISPER_MODEL_INFO: dict[str, dict] = {
    # Standard multilingual models
    "tiny": {
        "name": "Tiny",
        "params": "39M",
        "speed": "fastest",
        "description": "Fastest model, lowest accuracy. Good for quick drafts or testing.",
    },
    "tiny.en": {
        "name": "Tiny (English)",
        "params": "39M",
        "speed": "fastest",
        "description": "English-only tiny model. Slightly better for English than multilingual.",
    },
    "base": {
        "name": "Base",
        "params": "74M",
        "speed": "very fast",
        "description": "Fast with basic accuracy. Good default for live transcription.",
    },
    "base.en": {
        "name": "Base (English)",
        "params": "74M",
        "speed": "very fast",
        "description": "English-only base model. Better for English content.",
    },
    "small": {
        "name": "Small",
        "params": "244M",
        "speed": "fast",
        "description": "Balanced speed and accuracy. Good for general use.",
    },
    "small.en": {
        "name": "Small (English)",
        "params": "244M",
        "speed": "fast",
        "description": "English-only small model. Recommended for English content.",
    },
    "medium": {
        "name": "Medium",
        "params": "769M",
        "speed": "moderate",
        "description": "High accuracy, slower. Good for final transcription pass.",
    },
    "medium.en": {
        "name": "Medium (English)",
        "params": "769M",
        "speed": "moderate",
        "description": "English-only medium model. Best quality for English without going to large.",
    },
    "large-v1": {
        "name": "Large v1",
        "params": "1.5B",
        "speed": "slow",
        "description": "Original large model. High accuracy, resource intensive.",
    },
    "large-v2": {
        "name": "Large v2",
        "params": "1.5B",
        "speed": "slow",
        "description": "Improved large model. Better accuracy than v1.",
    },
    "large-v3": {
        "name": "Large v3",
        "params": "1.5B",
        "speed": "slow",
        "description": "Latest large model. Highest accuracy, requires significant resources.",
    },
    "large": {
        "name": "Large",
        "params": "1.5B",
        "speed": "slow",
        "description": "Alias for latest large model (v3). Highest accuracy available.",
    },
    # Turbo models
    "large-v3-turbo": {
        "name": "Large v3 Turbo",
        "params": "809M",
        "speed": "fast",
        "description": "Optimized large-v3 with 4 decoder layers. Near large-v2 accuracy at much higher speed.",
    },
    "turbo": {
        "name": "Turbo",
        "params": "809M",
        "speed": "fast",
        "description": "Alias for large-v3-turbo. Best speed/accuracy balance for most use cases.",
    },
    # Distil models (English only, knowledge-distilled)
    "distil-small.en": {
        "name": "Distil Small",
        "params": "166M",
        "speed": "very fast",
        "description": "Distilled small model. 6x faster than large, English only. Good for constrained environments.",
    },
    "distil-medium.en": {
        "name": "Distil Medium",
        "params": "394M",
        "speed": "very fast",
        "description": "Distilled medium model. 6x faster than large, English only.",
    },
    "distil-large-v2": {
        "name": "Distil Large v2",
        "params": "756M",
        "speed": "fast",
        "description": "Distilled large-v2. 6x faster, within 1% accuracy of large. English only.",
    },
    "distil-large-v3": {
        "name": "Distil Large v3",
        "params": "756M",
        "speed": "fast",
        "description": "Distilled large-v3. Best distil model, 6x faster than large. English only.",
    },
    "distil-large-v3.5": {
        "name": "Distil Large v3.5",
        "params": "756M",
        "speed": "fast",
        "description": "Latest distilled model. Improved accuracy over v3. English only.",
    },
}


def get_available_whisper_models() -> list[str]:
    """Return list of available Whisper model IDs from faster-whisper."""
    return available_models()


def get_whisper_model_info() -> dict[str, dict]:
    """Return model info for all available models.
    
    Filters WHISPER_MODEL_INFO to only include models that are
    actually available in the installed faster-whisper version.
    """
    available = set(available_models())
    return {
        model_id: info
        for model_id, info in WHISPER_MODEL_INFO.items()
        if model_id in available
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
                diarization_segments = self._diarization.run(audio_path)
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

    def stream_segments(self, audio_path: str):
        if not os.path.exists(audio_path):
            raise TranscriptionProviderError("Audio file not found")

        # #region agent log
        _dbg_logger.debug("WHISPER_STREAM_START: audio_path=%s", audio_path)
        # #endregion
        model = self._get_model()
        # #region agent log
        _dbg_logger.debug("WHISPER_STREAM_GOT_MODEL: audio_path=%s calling transcribe", audio_path)
        _transcribe_start = time.perf_counter()
        # #endregion
        try:
            result = model.transcribe(audio_path)
            # #region agent log
            _transcribe_elapsed = time.perf_counter() - _transcribe_start
            _dbg_logger.debug("WHISPER_STREAM_TRANSCRIBE_RETURNED: audio_path=%s elapsed_sec=%.2f", audio_path, _transcribe_elapsed)
            # #endregion
            return result
        except Exception as exc:
            # #region agent log
            _dbg_logger.debug("WHISPER_STREAM_ERROR: audio_path=%s exc_type=%s exc=%s", audio_path, type(exc).__name__, str(exc)[:500])
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
