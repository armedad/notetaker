from __future__ import annotations

import json
import os
from typing import Generator

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

    def _call_api_stream(
        self,
        prompt: str,
        temperature: float = 0.2,
        timeout: int = 120,
        system_prompt: str | None = None,
    ) -> Generator[str, None, None]:
        """Make a streaming call to the Ollama API, yielding tokens as they arrive."""
        # #region agent log
        import time as _time
        _log_path = os.path.join(os.getcwd(), "logs", "debug.log")
        def _dbg(msg, data=None):
            import json as _json
            with open(_log_path, "a") as _f:
                _f.write(_json.dumps({"location":"ollama_provider.py:_call_api_stream","message":msg,"data":data or {},"timestamp":int(_time.time()*1000),"hypothesisId":"H1,H4"})+"\n")
        _dbg("stream_start", {"model": self._model})
        # #endregion
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"
        
        request_body = {
            "model": self._model,
            "prompt": full_prompt,
            "stream": True,
        }
        
        try:
            response = requests.post(
                f"{self._base_url}/api/generate",
                json=request_body,
                timeout=timeout,
                stream=True,
            )
        except requests.RequestException as exc:
            raise LLMProviderError("Failed to reach Ollama") from exc

        if response.status_code != 200:
            raise LLMProviderError(f"Ollama error: {response.status_code}")

        # #region agent log
        _token_count = 0
        # #endregion
        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line)
                    if token := data.get("response"):
                        # #region agent log
                        _token_count += 1
                        if _token_count <= 5 or _token_count % 20 == 0:
                            _dbg("token_yielded", {"token_num": _token_count, "token_preview": token[:20] if len(token) > 20 else token})
                        # #endregion
                        yield token
                    if data.get("done"):
                        # #region agent log
                        _dbg("stream_done", {"total_tokens": _token_count})
                        # #endregion
                        break
                except json.JSONDecodeError:
                    continue
