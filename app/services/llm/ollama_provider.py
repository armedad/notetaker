from __future__ import annotations

import json
import logging
from typing import Any

import requests

from app.services.llm.base import LLMProvider, LLMProviderError


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._logger = logging.getLogger("notetaker.llm.ollama")

    def summarize(self, transcript: str) -> dict:
        prompt = (
            "Summarize the meeting and extract action items.\n\n"
            "Return JSON with keys: summary (string) and action_items (array of objects "
            "with keys: description, assignee, due_date).\n\n"
            f"Transcript:\n{transcript}"
        )
        try:
            response = requests.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=120,
            )
        except requests.RequestException as exc:
            raise LLMProviderError("Failed to reach Ollama") from exc

        if response.status_code != 200:
            raise LLMProviderError(f"Ollama error: {response.status_code}")

        data = response.json()
        text = data.get("response", "")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            self._logger.warning("Ollama returned non-JSON response")
            return {"summary": text.strip(), "action_items": []}
        return {
            "summary": str(parsed.get("summary", "")).strip(),
            "action_items": parsed.get("action_items", []) or [],
        }

    def generate_title(self, summary: str) -> str:
        prompt = (
            "Create a concise meeting title (max 8 words).\n"
            "Return plain text only.\n\n"
            f"Summary:\n{summary}"
        )
        try:
            response = requests.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=60,
            )
        except requests.RequestException as exc:
            raise LLMProviderError("Failed to reach Ollama") from exc

        if response.status_code != 200:
            raise LLMProviderError(f"Ollama error: {response.status_code}")

        data = response.json()
        text = data.get("response", "").strip()
        return text.strip().strip('"')

    def classify_subject_confidence(self, summary: str) -> bool:
        prompt = (
            "Determine if the following summary clearly identifies the main subject "
            "of the conversation. Reply with only YES or NO.\n\n"
            f"Summary:\n{summary}"
        )
        try:
            response = requests.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise LLMProviderError("Failed to reach Ollama") from exc

        if response.status_code != 200:
            raise LLMProviderError(f"Ollama error: {response.status_code}")

        data = response.json()
        text = data.get("response", "").strip().lower()
        return text.startswith("yes")

    def cleanup_transcript(self, transcript: str) -> str:
        prompt = (
            "Clean up the following live transcription text. Fix obvious transcription "
            "errors, normalize punctuation, and preserve meaning. Return plain text only.\n\n"
            f"Transcript:\n{transcript}"
        )
        try:
            response = requests.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=60,
            )
        except requests.RequestException as exc:
            raise LLMProviderError("Failed to reach Ollama") from exc

        if response.status_code != 200:
            raise LLMProviderError(f"Ollama error: {response.status_code}")

        data = response.json()
        text = data.get("response", "").strip()
        return text

    def segment_topics(self, transcript: str) -> list[dict]:
        prompt = (
            "Split the transcript into topic blocks. For each block, return JSON with "
            "keys: topic (string), summary (string), transcript (string). "
            "Return JSON array only.\n\n"
            f"Transcript:\n{transcript}"
        )
        try:
            response = requests.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=90,
            )
        except requests.RequestException as exc:
            raise LLMProviderError("Failed to reach Ollama") from exc

        if response.status_code != 200:
            raise LLMProviderError(f"Ollama error: {response.status_code}")

        data = response.json()
        text = data.get("response", "").strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMProviderError("Ollama returned non-JSON for topic segmentation") from exc
        if not isinstance(parsed, list):
            raise LLMProviderError("Topic segmentation response is not a list")
        return parsed
