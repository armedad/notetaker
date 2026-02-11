"""Gemini LLM provider using Google's Generative AI API."""
from __future__ import annotations

import requests

from app.services.llm.base import BaseLLMProvider, LLMProviderError


class GeminiProvider(BaseLLMProvider):
    """LLM provider for Google Gemini models."""
    
    def __init__(
        self, api_key: str, model: str, base_url: str = "https://generativelanguage.googleapis.com"
    ) -> None:
        super().__init__(logger_name="notetaker.llm.gemini")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")

    def _call_api(
        self,
        prompt: str,
        temperature: float = 0.2,
        timeout: int = 120,
        system_prompt: str | None = None,
        json_mode: bool = False,
    ) -> str:
        """Make a call to the Gemini API and return the response text."""
        # Handle model name format (may include "models/" prefix)
        model_name = self._model
        if not model_name.startswith("models/"):
            model_name = f"models/{model_name}"
        
        url = f"{self._base_url}/v1/{model_name}:generateContent?key={self._api_key}"
        
        # Build the prompt with optional system instructions
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"
        
        try:
            response = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": full_prompt}]}],
                    "generationConfig": {"temperature": temperature},
                },
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise LLMProviderError("Failed to reach Gemini API") from exc

        if response.status_code != 200:
            self._logger.error("Gemini error: %s - %s", response.status_code, response.text[:500])
            raise LLMProviderError(f"Gemini error: {response.status_code}")

        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise LLMProviderError("Gemini response missing candidates")
        
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        if not parts:
            raise LLMProviderError("Gemini response missing parts")
        
        return parts[0].get("text", "").strip()
