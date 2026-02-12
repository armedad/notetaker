import logging
import json
import os
import time
from typing import Union

from app.services.diarization.providers.base import (
    DiarizationConfig,
    BatchDiarizationConfig,
    RealtimeDiarizationConfig,
    parse_diarization_config,
)
from app.services.diarization.providers.null_provider import NullProvider
from app.services.diarization.providers.pyannote_provider import PyannoteProvider
from app.services.diarization.providers.whisperx_provider import WhisperXProvider
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


class DiarizationError(RuntimeError):
    pass


class DiarizationService:
    """Service for batch (offline) speaker diarization.
    
    Supports multiple providers:
    - pyannote: Direct pyannote.audio diarization
    - whisperx: WhisperX-based diarization
    - diart: Diart-based diarization (also supports real-time via RealtimeDiarizationService)
    - none: Disabled/null provider
    
    For real-time diarization during live recording, use RealtimeDiarizationService
    with provider=diart.
    
    Accepts either:
    - BatchDiarizationConfig (new format)
    - DiarizationConfig (legacy format for backwards compatibility)
    """
    
    def __init__(self, config: Union[DiarizationConfig, BatchDiarizationConfig]) -> None:
        self._config = config
        self._logger = logging.getLogger("notetaker.diarization")
        self._provider = None

    def update_config(self, config: Union[DiarizationConfig, BatchDiarizationConfig]) -> None:
        self._config = config
        self._provider = None

    def is_enabled(self) -> bool:
        return bool(self._config.enabled)
    
    def get_provider_name(self) -> str:
        """Get the configured provider name."""
        return (self._config.provider or "pyannote").lower()
    
    def get_model(self) -> str:
        """Get the configured model name."""
        return getattr(self._config, "model", "") or ""

    def _load_provider(self):
        if self._provider is not None:
            return self._provider
        provider_name = self.get_provider_name()
        if provider_name == "none":
            self._provider = NullProvider()
            return self._provider
        
        # For providers, we need a DiarizationConfig
        # Convert BatchDiarizationConfig to DiarizationConfig if needed
        if isinstance(self._config, BatchDiarizationConfig):
            legacy_config = DiarizationConfig.from_batch(self._config)
        else:
            legacy_config = self._config
        
        if provider_name == "pyannote":
            self._provider = PyannoteProvider(legacy_config)
            return self._provider
        if provider_name == "whisperx":
            self._provider = WhisperXProvider(legacy_config)
            return self._provider
        if provider_name == "diart":
            # Diart can also be used for batch processing
            from app.services.diarization.providers.diart_provider import DiartProvider
            self._provider = DiartProvider(legacy_config)
            return self._provider
        raise DiarizationError(f"Unsupported diarization provider: {provider_name}")

    def run(self, audio_path: str) -> list[dict]:
        if not self._config.enabled:
            return []
        _dbg(
            "app/services/diarization/__init__.py:run",
            "diarization_run_enter",
            {
                "provider": self.get_provider_name(),
                "device": self._config.device,
                "model": self._config.model,
                "hf_token_present": bool(self._config.hf_token),
                "audio_basename": os.path.basename(audio_path or ""),
            },
            run_id="pre-fix",
            hypothesis_id="H3",
        )
        provider = self._load_provider()
        try:
            return provider.diarize(audio_path)
        except Exception as exc:
            _dbg(
                "app/services/diarization/__init__.py:run",
                "diarization_run_error",
                {
                    "provider": self.get_provider_name(),
                    "exc_type": type(exc).__name__,
                    "exc_str": str(exc)[:500],
                },
                run_id="pre-fix",
                hypothesis_id="H1",
            )
            self._logger.exception("Diarization failed: %s", exc)
            raise
