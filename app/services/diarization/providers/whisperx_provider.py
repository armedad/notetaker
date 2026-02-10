from __future__ import annotations

import logging
import time

from app.services.diarization.providers.base import DiarizationConfig, DiarizationProvider


class WhisperXProvider(DiarizationProvider):
    def __init__(self, config: DiarizationConfig) -> None:
        self._config = config
        self._logger = logging.getLogger("notetaker.diarization.whisperx")

    def diarize(self, audio_path: str) -> list[dict]:
        try:
            import whisperx
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("whisperx is not installed") from exc
        try:
            import torch
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("torch is not installed") from exc

        device = self._config.device or "cpu"
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA device selected but not available")
        start_time = time.perf_counter()
        self._logger.info(
            "WhisperX diarization start: device=%s performance=%.2f",
            device,
            self._config.performance_level,
        )
        try:
            diarize_pipeline = whisperx.DiarizationPipeline(
                use_auth_token=self._config.hf_token,
                device=device,
            )
            diarization = diarize_pipeline(audio_path)
        except Exception as exc:
            error_str = str(exc).lower()
            if "403" in error_str or "forbidden" in error_str or "gated" in error_str:
                self._logger.error(
                    "HuggingFace returned 403 Forbidden. The pyannote models "
                    "require accepting license agreements. Please visit BOTH URLs, "
                    "log in with your HuggingFace account, and accept the terms: "
                    "(1) https://huggingface.co/pyannote/speaker-diarization-3.1 "
                    "(2) https://huggingface.co/pyannote/segmentation-3.0"
                )
                raise RuntimeError(
                    "HuggingFace 403: Accept pyannote licenses at "
                    "https://huggingface.co/pyannote/speaker-diarization-3.1 AND "
                    "https://huggingface.co/pyannote/segmentation-3.0"
                ) from exc
            raise RuntimeError("WhisperX diarization failed") from exc

        segments: list[dict] = []
        for segment in diarization.itersegments():
            segments.append(
                {
                    "start": float(segment.start),
                    "end": float(segment.end),
                    "speaker": str(segment.label),
                }
            )
        duration = time.perf_counter() - start_time
        self._logger.info(
            "WhisperX diarization complete: segments=%s duration=%.2fs",
            len(segments),
            duration,
        )
        return segments
