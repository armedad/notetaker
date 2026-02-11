from __future__ import annotations

import requests

from app.services.llm.base import BaseLLMProvider, LLMProviderError


class OllamaProvider(BaseLLMProvider):
    """LLM provider for local Ollama models."""
    
    def __init__(self, base_url: str, model: str) -> None:
        super().__init__(logger_name="notetaker.llm.ollama")
        self._base_url = base_url.rstrip("/")
        self._model = model

    def _call_api(
        self,
        prompt: str,
        temperature: float = 0.2,
        timeout: int = 120,
        system_prompt: str | None = None,
        json_mode: bool = False,
    ) -> str:
        """Make a call to the Ollama API and return the response text."""
        # Prepend system prompt to the user prompt if provided
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"
        
        request_body = {
            "model": self._model,
            "prompt": full_prompt,
            "stream": False,
        }
        
        if json_mode:
            request_body["format"] = "json"
        
        try:
            response = requests.post(
                f"{self._base_url}/api/generate",
                json=request_body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise LLMProviderError("Failed to reach Ollama") from exc

        if response.status_code != 200:
            raise LLMProviderError(f"Ollama error: {response.status_code}")

        data = response.json()
        return data.get("response", "").strip()
