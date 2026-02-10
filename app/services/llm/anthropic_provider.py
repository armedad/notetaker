from __future__ import annotations

import json
import logging

import requests

from app.services.llm.base import LLMProvider, LLMProviderError


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._logger = logging.getLogger("notetaker.llm.anthropic")

    def summarize(self, transcript: str) -> dict:
        prompt = (
            "Summarize the meeting and extract action items.\n\n"
            "Return JSON with keys: summary (string) and action_items (array of objects "
            "with keys: description, assignee, due_date).\n\n"
            f"Transcript:\n{transcript}"
        )
        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=120,
            )
        except requests.RequestException as exc:
            raise LLMProviderError("Failed to reach Anthropic") from exc

        if response.status_code != 200:
            raise LLMProviderError(f"Anthropic error: {response.status_code}")

        data = response.json()
        content_blocks = data.get("content", [])
        if not content_blocks:
            raise LLMProviderError("Anthropic response missing content")
        content = content_blocks[0].get("text", "")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            self._logger.warning("Anthropic returned non-JSON response")
            return {"summary": content.strip(), "action_items": []}
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
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": 128,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=60,
            )
        except requests.RequestException as exc:
            raise LLMProviderError("Failed to reach Anthropic") from exc

        if response.status_code != 200:
            raise LLMProviderError(f"Anthropic error: {response.status_code}")

        data = response.json()
        content_blocks = data.get("content", [])
        if not content_blocks:
            raise LLMProviderError("Anthropic response missing content")
        return content_blocks[0].get("text", "").strip().strip('"')

    def classify_subject_confidence(self, summary: str) -> bool:
        prompt = (
            "Determine if the following summary clearly identifies the main subject "
            "of the conversation. Reply with only YES or NO.\n\n"
            f"Summary:\n{summary}"
        )
        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": 4,
                    "temperature": 0.0,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise LLMProviderError("Failed to reach Anthropic") from exc

        if response.status_code != 200:
            raise LLMProviderError(f"Anthropic error: {response.status_code}")

        data = response.json()
        content_blocks = data.get("content", [])
        if not content_blocks:
            raise LLMProviderError("Anthropic response missing content")
        text = str(content_blocks[0].get("text", "")).strip().lower()
        return text.startswith("yes")

    def cleanup_transcript(self, transcript: str) -> str:
        prompt = (
            "Clean up the following live transcription text. Fix obvious transcription "
            "errors, normalize punctuation, and preserve meaning. Return plain text only.\n\n"
            f"Transcript:\n{transcript}"
        )
        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": 1024,
                    "temperature": 0.1,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=60,
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

    def segment_topics(self, transcript: str) -> list[dict]:
        prompt = (
            "Split the transcript into topic blocks. For each block, return JSON with "
            "keys: topic (string), summary (string), transcript (string). "
            "Return ONLY a valid JSON array, no markdown code blocks, no explanation.\n\n"
            f"Transcript:\n{transcript}"
        )
        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": 2048,
                    "temperature": 0.1,
                    "system": "You are a JSON-only assistant. Return only valid JSON arrays, no markdown formatting.",
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=90,
            )
        except requests.RequestException as exc:
            raise LLMProviderError("Failed to reach Anthropic") from exc

        if response.status_code != 200:
            raise LLMProviderError(f"Anthropic error: {response.status_code}")

        data = response.json()
        content_blocks = data.get("content", [])
        if not content_blocks:
            raise LLMProviderError("Anthropic response missing content")
        content = content_blocks[0].get("text", "")
        
        # Try to extract JSON from content (may be wrapped in markdown)
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```"):
                    in_block = not in_block
                    continue
                if in_block or not line.startswith("```"):
                    json_lines.append(line)
            text = "\n".join(json_lines).strip()
        
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(f"Anthropic returned non-JSON for topic segmentation: {text[:200]}") from exc
        
        # Handle object wrapper
        if isinstance(parsed, dict):
            if "topics" in parsed:
                parsed = parsed["topics"]
            elif len(parsed) == 1:
                parsed = list(parsed.values())[0]
        
        if not isinstance(parsed, list):
            raise LLMProviderError("Topic segmentation response is not a list")
        return parsed
