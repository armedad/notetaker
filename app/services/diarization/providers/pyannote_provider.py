from __future__ import annotations

import logging

from app.services.diarization.providers.base import DiarizationConfig, DiarizationProvider


class PyannoteProvider(DiarizationProvider):
    def __init__(self, config: DiarizationConfig) -> None:
        self._config = config
        self._logger = logging.getLogger("notetaker.diarization.pyannote")
        self._pipeline = None

    def diarize(self, audio_path: str) -> list[dict]:
        if not self._config.hf_token:
            raise RuntimeError("Missing Hugging Face token for diarization")
        try:
            from pyannote.audio import Pipeline
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("pyannote.audio is not installed") from exc

        if self._pipeline is None:
            self._logger.info(
                "Loading diarization model: %s (device=%s)",
                self._config.model,
                self._config.device,
            )
            self._pipeline = Pipeline.from_pretrained(
                self._config.model,
                use_auth_token=self._config.hf_token,
            )
            self._pipeline.to(self._config.device)

        diarization = self._pipeline(audio_path)
        segments: list[dict] = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append(
                {
                    "start": float(turn.start),
                    "end": float(turn.end),
                    "speaker": str(speaker),
                }
            )
        self._logger.info("Diarization segments=%s", len(segments))
        return segments
