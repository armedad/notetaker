from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: Optional[str] = None


@dataclass(frozen=True)
class TranscriptionResult:
    language: Optional[str]
    duration: float
    segments: list[TranscriptSegment]


class TranscriptionProvider(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str) -> TranscriptionResult:
        raise NotImplementedError

    def get_chunk_size(self) -> float:
        """Get the optimal chunk size in seconds for this provider.
        
        This is used by live transcription to determine how much audio
        to accumulate before sending to the provider. Different providers
        have different optimal chunk sizes:
        
        - Whisper: 30 seconds (fixed encoder window, smaller inputs are padded)
        - Parakeet: 2 seconds (configurable streaming)
        - Vosk: 0.5 seconds (native streaming)
        
        Returns:
            Optimal chunk size in seconds
        """
        return 30.0  # Default to Whisper's window size


class TranscriptionProviderError(RuntimeError):
    pass
