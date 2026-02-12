from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Generator


class LLMProviderError(RuntimeError):
    pass


class LLMProvider(ABC):
    @abstractmethod
    def summarize(self, transcript: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def generate_title(self, summary: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def classify_subject_confidence(self, summary: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def cleanup_transcript(self, transcript: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def segment_topics(self, transcript: str) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def prompt(self, prompt: str) -> str:
        """Send a raw prompt and return the response text."""
        raise NotImplementedError

    @abstractmethod
    def prompt_stream(self, prompt: str) -> Generator[str, None, None]:
        """Stream a response from the LLM, yielding tokens as they arrive."""
        raise NotImplementedError


class BaseLLMProvider(LLMProvider):
    """Base implementation with shared prompts, JSON parsing, and response handling.
    
    Subclasses only need to implement _call_api() for their specific API client.
    """
    
    # Shared prompts - single source of truth
    PROMPTS = {
        "summarize": (
            "Summarize the meeting and extract action items.\n\n"
            "Return JSON with keys: summary (string) and action_items (array of objects "
            "with keys: description, assignee, due_date).\n\n"
            "Transcript:\n{transcript}"
        ),
        "generate_title": (
            "Create a concise meeting title (max 8 words).\n"
            "Return plain text only, no quotes.\n\n"
            "Summary:\n{summary}"
        ),
        "classify_subject": (
            "Determine if the following summary clearly identifies the main subject "
            "of the conversation. Reply with only YES or NO.\n\n"
            "Summary:\n{summary}"
        ),
        "cleanup_transcript": (
            "Clean up the following live transcription text. Fix obvious transcription "
            "errors, normalize punctuation, and preserve meaning. Return plain text only.\n\n"
            "Transcript:\n{transcript}"
        ),
        "segment_topics": (
            "Split the transcript into topic blocks. For each block, return JSON with "
            "keys: topic (string), summary (string), transcript (string). "
            "Return ONLY a valid JSON array, no markdown code blocks, no explanation.\n\n"
            "Transcript:\n{transcript}"
        ),
        "segment_topics_system": (
            "You are a JSON-only assistant. Return only valid JSON arrays, no markdown formatting."
        ),
    }
    
    def __init__(self, logger_name: str = "notetaker.llm") -> None:
        self._logger = logging.getLogger(logger_name)
    
    @abstractmethod
    def _call_api(
        self, 
        prompt: str, 
        temperature: float = 0.2, 
        timeout: int = 120,
        system_prompt: str | None = None,
        json_mode: bool = False,
    ) -> str:
        """Make an API call and return the raw response text.
        
        Args:
            prompt: The user prompt to send
            temperature: Sampling temperature (0.0-1.0)
            timeout: Request timeout in seconds
            system_prompt: Optional system prompt
            json_mode: Request JSON-formatted response if supported
            
        Returns:
            The response text content
        """
        raise NotImplementedError

    def _call_api_stream(
        self,
        prompt: str,
        temperature: float = 0.2,
        timeout: int = 120,
        system_prompt: str | None = None,
    ) -> Generator[str, None, None]:
        """Make a streaming API call, yielding tokens as they arrive.
        
        Default implementation falls back to non-streaming.
        Subclasses should override this to implement actual streaming.
        
        Args:
            prompt: The user prompt to send
            temperature: Sampling temperature (0.0-1.0)
            timeout: Request timeout in seconds
            system_prompt: Optional system prompt
            
        Yields:
            Token strings as they arrive from the API
        """
        # Default fallback: return full response as single chunk
        result = self._call_api(prompt, temperature, timeout, system_prompt)
        yield result
    
    @staticmethod
    def _strip_markdown_code_blocks(text: str) -> str:
        """Remove markdown code block wrappers from text."""
        text = text.strip()
        if not text.startswith("```"):
            return text
        
        lines = text.split("\n")
        json_lines = []
        in_block = False
        for line in lines:
            if line.startswith("```"):
                in_block = not in_block
                continue
            json_lines.append(line)
        return "\n".join(json_lines).strip()
    
    @staticmethod
    def _unwrap_json_list(parsed: dict | list, logger: logging.Logger | None = None) -> list:
        """Extract a list from a JSON response that may be wrapped in a dict.
        
        LLM JSON modes often return {"key": [...]} instead of raw arrays.
        This method handles various common wrapper structures.
        
        Args:
            parsed: The parsed JSON (dict or list)
            logger: Optional logger for debug messages
            
        Returns:
            The extracted list
            
        Raises:
            LLMProviderError: If unable to extract a list
        """
        if isinstance(parsed, list):
            return parsed
        
        if isinstance(parsed, dict):
            # Some models occasionally return a single topic block as an object
            # instead of a JSON array. Treat it as a single-element list.
            if all(k in parsed for k in ["topic", "summary", "transcript"]):
                if logger:
                    logger.warning(
                        "Topic segmentation returned single object; wrapping into list. Keys=%s",
                        list(parsed.keys()),
                    )
                return [parsed]

            # Try common key names first
            for key in ["topics", "blocks", "segments", "data", "result", "results"]:
                if key in parsed and isinstance(parsed[key], list):
                    if logger:
                        logger.debug("Extracted list from key '%s'", key)
                    return parsed[key]
            
            # If only one key and its value is a list, use that
            if len(parsed) == 1:
                value = list(parsed.values())[0]
                if isinstance(value, list):
                    if logger:
                        logger.debug("Extracted list from single-key dict")
                    return value
            
            # If dict has multiple keys but one contains a list of dicts with expected structure
            for key, value in parsed.items():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    if any(k in value[0] for k in ["topic", "summary", "transcript"]):
                        if logger:
                            logger.debug("Extracted list from key '%s' (structure match)", key)
                        return value
            
            if logger:
                logger.warning(
                    "JSON response is dict with unexpected structure. Keys: %s",
                    list(parsed.keys())
                )
            raise LLMProviderError(
                f"Unable to extract list from JSON. Got dict with keys: {list(parsed.keys())}"
            )
        
        raise LLMProviderError(f"Expected list or dict, got {type(parsed).__name__}")
    
    def summarize(self, transcript: str) -> dict:
        prompt = self.PROMPTS["summarize"].format(transcript=transcript)
        content = self._call_api(prompt, temperature=0.2, timeout=120)
        
        text = self._strip_markdown_code_blocks(content)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            self._logger.warning("Non-JSON response for summarize, using raw text")
            return {"summary": content.strip(), "action_items": []}
        
        return {
            "summary": str(parsed.get("summary", "")).strip(),
            "action_items": parsed.get("action_items", []) or [],
        }
    
    def generate_title(self, summary: str) -> str:
        prompt = self.PROMPTS["generate_title"].format(summary=summary)
        content = self._call_api(prompt, temperature=0.2, timeout=60)
        return content.strip().strip('"')
    
    def classify_subject_confidence(self, summary: str) -> bool:
        prompt = self.PROMPTS["classify_subject"].format(summary=summary)
        content = self._call_api(prompt, temperature=0.0, timeout=30)
        return content.strip().lower().startswith("yes")
    
    def cleanup_transcript(self, transcript: str) -> str:
        prompt = self.PROMPTS["cleanup_transcript"].format(transcript=transcript)
        return self._call_api(prompt, temperature=0.1, timeout=60)
    
    def segment_topics(self, transcript: str) -> list[dict]:
        prompt = self.PROMPTS["segment_topics"].format(transcript=transcript)
        system = self.PROMPTS["segment_topics_system"]
        
        content = self._call_api(
            prompt, 
            temperature=0.1, 
            timeout=90, 
            system_prompt=system,
            json_mode=True,
        )
        
        text = self._strip_markdown_code_blocks(content)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            self._logger.warning("Non-JSON topic segmentation response: %s", text[:500])
            raise LLMProviderError(f"Non-JSON for topic segmentation: {text[:200]}") from exc
        
        return self._unwrap_json_list(parsed, self._logger)
    
    def prompt(self, prompt_text: str) -> str:
        """Send a raw prompt and return the response text."""
        return self._call_api(prompt_text, temperature=0.3, timeout=60)

    def prompt_stream(self, prompt_text: str) -> Generator[str, None, None]:
        """Stream a response from the LLM, yielding tokens as they arrive."""
        yield from self._call_api_stream(prompt_text, temperature=0.3, timeout=120)
