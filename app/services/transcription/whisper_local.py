from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

from faster_whisper import WhisperModel

from app.services.transcription.base import (
    TranscriptSegment,
    TranscriptionProvider,
    TranscriptionProviderError,
    TranscriptionResult,
)


@dataclass(frozen=True)
class WhisperConfig:
    model_size: str = "base"
    device: str = "cpu"
    compute_type: str = "int8"


class FasterWhisperProvider(TranscriptionProvider):
    def __init__(self, config: WhisperConfig) -> None:
        self._config = config
        self._logger = logging.getLogger("notetaker.transcription.whisper")
        self._model: WhisperModel | None = None

    def _get_model(self) -> WhisperModel:
        if self._model is None:
            self._logger.info(
                "Loading whisper model: size=%s device=%s compute_type=%s",
                self._config.model_size,
                self._config.device,
                self._config.compute_type,
            )
            self._model = WhisperModel(
                self._config.model_size,
                device=self._config.device,
                compute_type=self._config.compute_type,
            )
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

        model = self._get_model()
        try:
            return model.transcribe(audio_path)
        except Exception as exc:
            self._logger.exception("Transcription stream failed: %s", exc)
            raise TranscriptionProviderError("Transcription failed") from exc
