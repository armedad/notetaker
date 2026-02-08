from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass(frozen=True)
class DiarizationConfig:
    enabled: bool
    provider: str
    model: str
    device: str
    hf_token: Optional[str]
    performance_level: float


class DiarizationProvider(Protocol):
    def diarize(self, audio_path: str) -> list[dict]:
        ...
