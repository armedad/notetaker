import logging
from dataclasses import dataclass

from typing import Optional

from app.services.llm import (
    AnthropicProvider,
    LLMProvider,
    LLMProviderError,
    OllamaProvider,
    OpenAIProvider,
)


@dataclass(frozen=True)
class SummarizationConfig:
    provider: str
    ollama_base_url: str
    ollama_model: str
    openai_api_key: str
    openai_model: str
    anthropic_api_key: str
    anthropic_model: str
    lmstudio_base_url: str
    lmstudio_model: str


class SummarizationService:
    def __init__(self, config: SummarizationConfig) -> None:
        self._config = config
        self._logger = logging.getLogger("notetaker.summarization")
        self._title_logger = logging.getLogger("notetaker.summarization.title")

    def _get_provider(self, override: Optional[str]) -> LLMProvider:
        provider_name = (override or self._config.provider).lower()
        if provider_name == "ollama":
            return OllamaProvider(
                base_url=self._config.ollama_base_url,
                model=self._config.ollama_model,
            )
        if provider_name == "openai":
            if not self._config.openai_api_key:
                raise LLMProviderError("Missing OpenAI API key")
            return OpenAIProvider(
                api_key=self._config.openai_api_key,
                model=self._config.openai_model,
            )
        if provider_name == "anthropic":
            if not self._config.anthropic_api_key:
                raise LLMProviderError("Missing Anthropic API key")
            return AnthropicProvider(
                api_key=self._config.anthropic_api_key,
                model=self._config.anthropic_model,
            )
        if provider_name == "lmstudio":
            return OpenAIProvider(
                api_key="lmstudio",
                model=self._config.lmstudio_model,
                base_url=self._config.lmstudio_base_url,
            )
        raise LLMProviderError(f"Unknown provider: {provider_name}")

    def summarize(
        self, transcript: str, provider_override: Optional[str] = None
    ) -> dict:
        if not transcript.strip():
            raise LLMProviderError("Transcript is empty")
        provider = self._get_provider(provider_override)
        self._logger.info("Summarization using provider=%s", provider.__class__.__name__)
        return provider.summarize(transcript)

    def generate_title(
        self, summary: str, provider_override: Optional[str] = None
    ) -> str:
        if not summary.strip():
            raise LLMProviderError("Summary is empty")
        provider = self._get_provider(provider_override)
        self._title_logger.info(
            "Title generation using provider=%s", provider.__class__.__name__
        )
        return provider.generate_title(summary)

    def is_meaningful_summary(
        self, summary: str, provider_override: Optional[str] = None
    ) -> bool:
        if not summary.strip():
            return False
        provider = self._get_provider(provider_override)
        try:
            return provider.classify_subject_confidence(summary)
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(str(exc)) from exc

    def cleanup_transcript(
        self, transcript: str, provider_override: Optional[str] = None
    ) -> str:
        if not transcript.strip():
            raise LLMProviderError("Transcript is empty")
        provider = self._get_provider(provider_override)
        return provider.cleanup_transcript(transcript)

    def segment_topics(
        self, transcript: str, provider_override: Optional[str] = None
    ) -> list[dict]:
        if not transcript.strip():
            raise LLMProviderError("Transcript is empty")
        provider = self._get_provider(provider_override)
        return provider.segment_topics(transcript)
