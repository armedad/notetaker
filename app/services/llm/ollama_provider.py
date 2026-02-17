from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import time
from typing import Generator

import requests

from app.services.llm.base import BaseLLMProvider, LLMProviderError

_logger = logging.getLogger("notetaker.llm.ollama")

_LAUNCH_WAIT_MAX = 30  # seconds
_LAUNCH_POLL_INTERVAL = 1  # seconds


def _find_ollama_launch_cmd() -> list:
    """Return the platform-appropriate command to start Ollama."""
    system = platform.system()

    if system == "Darwin":
        # macOS — prefer the .app bundle, fall back to CLI
        if os.path.isdir("/Applications/Ollama.app"):
            return ["open", "-a", "/Applications/Ollama.app"]

    if system == "Windows":
        # Windows — check common install location, then PATH
        local_exe = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"
        )
        if os.path.isfile(local_exe):
            return [local_exe, "serve"]

    # Any OS — fall back to ollama on PATH
    if shutil.which("ollama"):
        return ["ollama", "serve"]

    return []


def _is_local_url(url: str) -> bool:
    """Return True if the URL points to the local machine."""
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def ensure_ollama_running(base_url: str = "http://127.0.0.1:11434") -> None:
    """Launch Ollama if it isn't already running. Blocks until ready.
    
    Only attempts a local launch when base_url points to localhost.
    If the user has configured a remote Ollama server, this function
    will check reachability but never try to start a local process.
    
    Works on macOS, Windows, and Linux. Call this at boot (when selected
    provider is Ollama) and when the user switches to an Ollama model.
    """
    base_url = base_url.rstrip("/")
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=3)
        if resp.status_code == 200:
            _logger.info("Ollama is already running at %s", base_url)
            return
    except requests.RequestException:
        pass

    if not _is_local_url(base_url):
        _logger.warning(
            "Ollama not reachable at %s (remote host) — will not attempt local launch",
            base_url,
        )
        return

    cmd = _find_ollama_launch_cmd()
    if not cmd:
        _logger.warning("Ollama not reachable and no installation found — cannot auto-launch")
        return

    _logger.info("Ollama not reachable — launching: %s", " ".join(cmd))
    try:
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(cmd, **kwargs)
    except Exception as exc:
        _logger.warning("Failed to launch Ollama: %s", exc)
        return

    # Poll until reachable or timeout
    deadline = time.monotonic() + _LAUNCH_WAIT_MAX
    while time.monotonic() < deadline:
        time.sleep(_LAUNCH_POLL_INTERVAL)
        try:
            resp = requests.get(f"{base_url}/api/tags", timeout=3)
            if resp.status_code == 200:
                _logger.info("Ollama is now reachable")
                return
        except requests.RequestException:
            pass

    _logger.warning("Launched Ollama but it didn't become reachable within %ds", _LAUNCH_WAIT_MAX)


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
