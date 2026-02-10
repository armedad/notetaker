import logging

from app.services.diarization.providers.base import DiarizationConfig
from app.services.diarization.providers.null_provider import NullProvider
from app.services.diarization.providers.pyannote_provider import PyannoteProvider
from app.services.diarization.providers.whisperx_provider import WhisperXProvider


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
    """
    
    def __init__(self, config: DiarizationConfig) -> None:
        self._config = config
        self._logger = logging.getLogger("notetaker.diarization")
        self._provider = None

    def update_config(self, config: DiarizationConfig) -> None:
        self._config = config
        self._provider = None

    def is_enabled(self) -> bool:
        return bool(self._config.enabled)
    
    def get_provider_name(self) -> str:
        """Get the configured provider name."""
        return (self._config.provider or "pyannote").lower()

    def _load_provider(self):
        if self._provider is not None:
            return self._provider
        provider_name = self.get_provider_name()
        if provider_name == "none":
            self._provider = NullProvider()
            return self._provider
        if provider_name == "pyannote":
            self._provider = PyannoteProvider(self._config)
            return self._provider
        if provider_name == "whisperx":
            self._provider = WhisperXProvider(self._config)
            return self._provider
        if provider_name == "diart":
            # Diart can also be used for batch processing
            from app.services.diarization.providers.diart_provider import DiartProvider
            self._provider = DiartProvider(self._config)
            return self._provider
        raise DiarizationError(f"Unsupported diarization provider: {provider_name}")

    def run(self, audio_path: str) -> list[dict]:
        if not self._config.enabled:
            return []
        provider = self._load_provider()
        try:
            return provider.diarize(audio_path)
        except Exception as exc:
            self._logger.exception("Diarization failed: %s", exc)
            raise
