from __future__ import annotations

import logging
import os
from typing import Union

from app.services.diarization.providers.base import DiarizationConfig, DiarizationProvider


def _patch_torch_load_for_pyannote():
    """PyTorch 2.6+ defaults torch.load to weights_only=True.
    pyannote model checkpoints contain custom classes (Specifications,
    TorchVersion, etc.) that aren't in the safe-globals allowlist,
    so loading them with weights_only=True raises UnpicklingError.
    We temporarily set weights_only=False for the trusted HuggingFace
    models used by pyannote."""
    import torch
    _original = torch.load

    def _patched_load(*args, **kwargs):
        if kwargs.get("weights_only") is None:
            kwargs["weights_only"] = False
        return _original(*args, **kwargs)

    torch.load = _patched_load
    return _original


def _restore_torch_load(original):
    import torch
    torch.load = original


_dbg_logger = logging.getLogger("notetaker.debug")


class PyannoteProvider(DiarizationProvider):
    def __init__(self, config: DiarizationConfig) -> None:
        self._config = config
        self._logger = logging.getLogger("notetaker.diarization.pyannote")
        self._pipeline = None

    def diarize(self, audio_source: Union[str, dict]) -> list[dict]:
        """Run diarization on audio.
        
        Args:
            audio_source: Either a file path (str) or a dict with
                {"waveform": torch.Tensor, "sample_rate": int} for in-memory
                audio. Using the dict format avoids temp file creation when
                processing compressed formats like Opus.
        """
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
            original_torch_load = _patch_torch_load_for_pyannote()
            # HF_HUB_OFFLINE is set globally at boot (main.py).
            # No per-call override needed — the settings UI handles downloads.
            try:
                self._pipeline = Pipeline.from_pretrained(
                    self._config.model,
                    use_auth_token=self._config.hf_token,
                )
                import torch as _torch
                _dev = _torch.device(self._config.device)
                self._pipeline.to(_dev)
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
            finally:
                _restore_torch_load(original_torch_load)

        diarization = self._pipeline(audio_source)
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
