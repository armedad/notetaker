from __future__ import annotations

import logging
import os

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

    def diarize(self, audio_path: str) -> list[dict]:
        # #region agent log
        _dbg_logger.debug("PYANNOTE_DIARIZE_ENTER: audio_path=%s model=%s device=%s",
                        audio_path, self._config.model, self._config.device)
        _logpath = "/Users/chee/zapier ai project/.cursor/debug.log"
        import json as _json
        import os as _os
        with open(_logpath, "a") as _f:
            _f.write(_json.dumps({"location": "pyannote_provider.py:diarize:enter", "message": "pyannote_diarize_enter", "hypothesisId": "H2", "data": {"audio_path": audio_path, "model": self._config.model, "device": self._config.device, "HF_HUB_OFFLINE": _os.environ.get("HF_HUB_OFFLINE", "not_set")}, "timestamp": int(__import__('time').time()*1000)}) + "\n")
        # #endregion
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
            # #region agent log
            _dbg_logger.debug("PYANNOTE_MODEL_LOAD_START: model=%s device=%s", self._config.model, self._config.device)
            import time as _pytime
            _model_load_t0 = _pytime.perf_counter()
            # #endregion
            original_torch_load = _patch_torch_load_for_pyannote()
            # HF_HUB_OFFLINE is set globally at boot (main.py).
            # No per-call override needed — the settings UI handles downloads.
            try:
                # #region agent log
                with open(_logpath, "a") as _f:
                    _f.write(_json.dumps({"location": "pyannote_provider.py:before_from_pretrained", "message": "about_to_call_Pipeline_from_pretrained", "hypothesisId": "H2", "data": {"model": self._config.model, "HF_HUB_OFFLINE": _os.environ.get("HF_HUB_OFFLINE", "not_set")}, "timestamp": int(__import__('time').time()*1000)}) + "\n")
                # #endregion
                self._pipeline = Pipeline.from_pretrained(
                    self._config.model,
                    use_auth_token=self._config.hf_token,
                )
                import torch as _torch
                _dev = _torch.device(self._config.device)
                # #region agent log
                self._logger.debug("pipeline.to device: config_device=%s torch_device=%s", self._config.device, str(_dev))
                _dbg_logger.debug("PYANNOTE_PIPELINE_TO_DEVICE: device=%s", str(_dev))
                # #endregion
                self._pipeline.to(_dev)
                # #region agent log
                _model_load_elapsed = _pytime.perf_counter() - _model_load_t0
                _dbg_logger.debug("PYANNOTE_MODEL_LOAD_DONE: model=%s elapsed_sec=%.2f", self._config.model, _model_load_elapsed)
                # #endregion
            except Exception as exc:
                # #region agent log
                _dbg_logger.debug("PYANNOTE_MODEL_LOAD_ERROR: exc_type=%s exc=%s", type(exc).__name__, str(exc)[:500])
                with open(_logpath, "a") as _f:
                    _f.write(_json.dumps({"location": "pyannote_provider.py:from_pretrained_exception", "message": "Pipeline_from_pretrained_failed", "hypothesisId": "H2", "data": {"exc_type": type(exc).__name__, "exc_str": str(exc)[:500], "model": self._config.model}, "timestamp": int(__import__('time').time()*1000)}) + "\n")
                # #endregion
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
        else:
            # #region agent log
            _dbg_logger.debug("PYANNOTE_MODEL_CACHED: model=%s", self._config.model)
            # #endregion

        # #region agent log
        import time as _tpy, os as _ospy
        _t0 = _tpy.time()
        _audio_size_mb = round(_ospy.path.getsize(audio_path)/1024/1024,2) if _ospy.path.isfile(audio_path) else None
        self._logger.debug("PIPELINE_CALL_START: audio_path=%s audio_size_mb=%s", _ospy.path.basename(audio_path), _audio_size_mb)
        _dbg_logger.debug("PYANNOTE_PIPELINE_RUN_START: audio_path=%s audio_size_mb=%s", audio_path, _audio_size_mb)
        # #endregion
        diarization = self._pipeline(audio_path)
        # #region agent log
        _diar_elapsed = _tpy.time() - _t0
        _dbg_logger.debug("PYANNOTE_PIPELINE_RUN_DONE: elapsed_sec=%.2f", _diar_elapsed)
        # #endregion
        # #region agent log
        self._logger.debug("PIPELINE_CALL_DONE: elapsed_s=%s", round(_tpy.time()-_t0,1))
        # #endregion
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
