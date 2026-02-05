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


class TranscriptionProviderError(RuntimeError):
    pass
