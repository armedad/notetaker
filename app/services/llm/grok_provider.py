"""Grok LLM provider using xAI's OpenAI-compatible API."""
from __future__ import annotations

import logging

from app.services.llm.openai_provider import OpenAIProvider


class GrokProvider(OpenAIProvider):
    """LLM provider for xAI Grok models.
    
    Grok uses an OpenAI-compatible API, so we extend OpenAIProvider
    with the correct default base URL.
    """
    
    def __init__(
        self, api_key: str, model: str, base_url: str = "https://api.x.ai"
    ) -> None:
        super().__init__(api_key=api_key, model=model, base_url=base_url)
        self._logger = logging.getLogger("notetaker.llm.grok")
