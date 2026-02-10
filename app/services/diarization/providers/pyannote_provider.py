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
            try:
                self._pipeline = Pipeline.from_pretrained(
                    self._config.model,
                    use_auth_token=self._config.hf_token,
                )
                self._pipeline.to(self._config.device)
            except Exception as exc:
                error_str = str(exc).lower()
                if "403" in error_str or "forbidden" in error_str or "gated" in error_str:
                    model_url = f"https://huggingface.co/{self._config.model}"
                    self._logger.error(
                        "HuggingFace returned 403 Forbidden. The pyannote model "
                        "requires accepting a license agreement at: %s "
                        "Please visit this URL, log in with your HuggingFace account, "
                        "and accept the license terms.", model_url
                    )
                    raise RuntimeError(
                        f"HuggingFace 403: Accept the pyannote license at {model_url}"
                    ) from exc
                raise

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
