from __future__ import annotations

import json
from typing import Generator

import requests

from app.services.llm.base import BaseLLMProvider, LLMProviderError


class AnthropicProvider(BaseLLMProvider):
    """LLM provider for Anthropic Claude models."""
    
    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(logger_name="notetaker.llm.anthropic")
        self._api_key = api_key
        self._model = model

    def _call_api(
        self,
        prompt: str,
        temperature: float = 0.2,
        timeout: int = 120,
        system_prompt: str | None = None,
        json_mode: bool = False,
    ) -> str:
        """Make a call to the Anthropic API and return the response text."""
        request_body = {
            "model": self._model,
            "max_tokens": 2048,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        
        if system_prompt:
            request_body["system"] = system_prompt
        
        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=request_body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise LLMProviderError("Failed to reach Anthropic") from exc

        if response.status_code != 200:
            raise LLMProviderError(f"Anthropic error: {response.status_code}")

        data = response.json()
        content_blocks = data.get("content", [])
        if not content_blocks:
            raise LLMProviderError("Anthropic response missing content")
        
        return str(content_blocks[0].get("text", "")).strip()

    def _call_api_stream(
        self,
        prompt: str,
        temperature: float = 0.2,
        timeout: int = 120,
        system_prompt: str | None = None,
    ) -> Generator[str, None, None]:
        """Make a streaming call to the Anthropic API, yielding tokens as they arrive."""
        request_body = {
            "model": self._model,
            "max_tokens": 2048,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        
        if system_prompt:
            request_body["system"] = system_prompt
        
        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=request_body,
                timeout=timeout,
                stream=True,
            )
        except requests.RequestException as exc:
            raise LLMProviderError("Failed to reach Anthropic") from exc

        if response.status_code != 200:
            raise LLMProviderError(f"Anthropic error: {response.status_code}")

        for line in response.iter_lines():
            if line:
                line_str = line.decode("utf-8") if isinstance(line, bytes) else line
                if line_str.startswith("data: "):
                    data_str = line_str[6:]
                    try:
                        data = json.loads(data_str)
                        event_type = data.get("type")
                        if event_type == "content_block_delta":
                            delta = data.get("delta", {})
                            if text := delta.get("text"):
                                yield text
                        elif event_type == "message_stop":
                            break
                    except json.JSONDecodeError:
                        continue
