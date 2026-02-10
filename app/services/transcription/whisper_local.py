from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

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


@dataclass(frozen=True)
class WhisperConfig:
    model_size: str = "base"
    device: str = "cpu"
    compute_type: str = "int8"


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

        model = self._get_model()
        try:
            return model.transcribe(audio_path)
        except Exception as exc:
            self._logger.exception("Transcription stream failed: %s", exc)
            raise TranscriptionProviderError("Transcription failed") from exc


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
