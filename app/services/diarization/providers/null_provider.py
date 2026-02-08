from __future__ import annotations

from app.services.diarization.providers.base import DiarizationProvider


class NullProvider(DiarizationProvider):
    def diarize(self, audio_path: str) -> list[dict]:
        return []
