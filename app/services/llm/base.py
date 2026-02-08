from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProviderError(RuntimeError):
    pass


class LLMProvider(ABC):
    @abstractmethod
    def summarize(self, transcript: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def generate_title(self, summary: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def classify_subject_confidence(self, summary: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def cleanup_transcript(self, transcript: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def segment_topics(self, transcript: str) -> list[dict]:
        raise NotImplementedError
