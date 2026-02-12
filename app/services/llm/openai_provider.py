from __future__ import annotations

import json
from typing import Generator

import requests

from app.services.llm.base import BaseLLMProvider, LLMProviderError


class OpenAIProvider(BaseLLMProvider):
    """LLM provider for OpenAI and OpenAI-compatible APIs."""
    
    def __init__(
        self, api_key: str, model: str, base_url: str = "https://api.openai.com"
    ) -> None:
        super().__init__(logger_name="notetaker.llm.openai")
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
        """Make a call to the OpenAI API and return the response text."""
        messages = [
            {"role": "system", "content": system_prompt or "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ]
        
        request_body = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        
        if json_mode:
            request_body["response_format"] = {"type": "json_object"}
        
        try:
            response = requests.post(
                f"{self._base_url}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise LLMProviderError("Failed to reach OpenAI") from exc

        if response.status_code != 200:
            raise LLMProviderError(f"OpenAI error: {response.status_code}")

        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            raise LLMProviderError("OpenAI response missing choices")
        
        content = choices[0].get("message", {}).get("content", "")
        return str(content).strip()

    def _call_api_stream(
        self,
        prompt: str,
        temperature: float = 0.2,
        timeout: int = 120,
        system_prompt: str | None = None,
    ) -> Generator[str, None, None]:
        """Make a streaming call to the OpenAI API, yielding tokens as they arrive."""
        messages = [
            {"role": "system", "content": system_prompt or "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ]
        
        request_body = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        
        try:
            response = requests.post(
                f"{self._base_url}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
                timeout=timeout,
                stream=True,
            )
        except requests.RequestException as exc:
            raise LLMProviderError("Failed to reach OpenAI") from exc

        if response.status_code != 200:
            raise LLMProviderError(f"OpenAI error: {response.status_code}")

        for line in response.iter_lines():
            if line:
                line_str = line.decode("utf-8") if isinstance(line, bytes) else line
                if line_str.startswith("data: "):
                    data_str = line_str[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        if content := delta.get("content"):
                            yield content
                    except json.JSONDecodeError:
                        continue
