from __future__ import annotations

import logging
import json
import os
import time

from app.services.diarization.providers.base import DiarizationConfig, DiarizationProvider
from app.services.debug_logging import dbg


def _dbg(location: str, message: str, data: dict, run_id: str, hypothesis_id: str) -> None:
    try:
        dbg(
            logging.getLogger("notetaker.debug"),
            location=location,
            message=message,
            data=data,
            run_id=run_id,
            hypothesis_id=hypothesis_id,
        )
    except Exception:
        pass


def _patch_torch_load() -> None:
    """Patch torch.load to use weights_only=False for pyannote model compatibility.
    
    PyTorch 2.6+ defaults to weights_only=True which breaks pyannote.audio model loading.
    This patch must be applied before importing whisperx/pyannote.
    """
    import torch
    import torch.serialization
    
    if getattr(torch, "_notetaker_load_patched", False):
        return  # Already patched
    
    _original_load = torch.serialization.load
    
    def _patched_load(f, *args, **kwargs):
        # Force weights_only=False for pyannote compatibility
        kwargs["weights_only"] = False
        return _original_load(f, *args, **kwargs)
    
    torch.serialization.load = _patched_load
    torch.load = _patched_load
    
    # Also patch lightning_fabric if already imported
    try:
        import lightning_fabric.utilities.cloud_io as cloud_io
        cloud_io.torch.load = _patched_load
    except ImportError:
        pass
    
    torch._notetaker_load_patched = True


class WhisperXProvider(DiarizationProvider):
    def __init__(self, config: DiarizationConfig) -> None:
        self._config = config
        self._logger = logging.getLogger("notetaker.diarization.whisperx")

    def diarize(self, audio_path: str) -> list[dict]:
        _dbg(
            "app/services/diarization/providers/whisperx_provider.py:diarize",
            "whisperx_diarize_enter",
            {
                "device": self._config.device or "cpu",
                "hf_token_present": bool(self._config.hf_token),
                "audio_basename": os.path.basename(audio_path or ""),
            },
            run_id="pre-fix",
            hypothesis_id="H2",
        )
        # Apply torch.load patch before importing whisperx (which imports pyannote)
        _patch_torch_load()
        
        try:
            import whisperx
        except Exception as exc:  # pragma: no cover
            _dbg(
                "app/services/diarization/providers/whisperx_provider.py:diarize",
                "whisperx_import_error",
                {"exc_type": type(exc).__name__, "exc_str": str(exc)[:500]},
                run_id="pre-fix",
                hypothesis_id="H4",
            )
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
            _dbg(
                "app/services/diarization/providers/whisperx_provider.py:diarize",
                "whisperx_pipeline_error",
                {"exc_type": type(exc).__name__, "exc_str": str(exc)[:800]},
                run_id="pre-fix",
                hypothesis_id="H1",
            )
            # Check for license/access issues (various error formats from HuggingFace/pyannote)
            if any(keyword in error_str for keyword in [
                "403", "forbidden", "gated", "accept", "user conditions", 
                "could not download", "access to model"
            ]):
                self._logger.error(
                    "HuggingFace model access denied. The pyannote models "
                    "require accepting license agreements. Please visit BOTH URLs, "
                    "log in with your HuggingFace account, and accept the terms: "
                    "(1) https://huggingface.co/pyannote/speaker-diarization-3.1 "
                    "(2) https://huggingface.co/pyannote/segmentation-3.0"
                )
                raise RuntimeError(
                    "HuggingFace access denied: Accept pyannote licenses at "
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
        _dbg(
            "app/services/diarization/providers/whisperx_provider.py:diarize",
            "whisperx_diarize_complete",
            {"segments": len(segments), "duration_s": round(duration, 3)},
            run_id="pre-fix",
            hypothesis_id="H2",
        )
        return segments
