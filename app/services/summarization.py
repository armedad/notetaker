import json
import logging
import os

from typing import Generator, Optional

from app.services.llm import (
    AnthropicProvider,
    GeminiProvider,
    GrokProvider,
    LLMProvider,
    LLMProviderError,
    OllamaProvider,
    OpenAIProvider,
)


class SummarizationService:
    """Service for LLM-based summarization using the user's selected model.
    
    Reads model selection from config.json dynamically:
    - models.selected_model: format "provider:model_id" (e.g., "openai:gpt-4o")
    - providers.<provider>: contains api_key and base_url for each provider
    """
    
    def __init__(self, config_path: str) -> None:
        self._config_path = config_path
        self._logger = logging.getLogger("notetaker.summarization")
        self._title_logger = logging.getLogger("notetaker.summarization.title")
        self._prompts_dir = os.path.join(os.path.dirname(__file__), "..", "prompts")

    def _read_config(self) -> dict:
        """Read config from file, returning empty dict if not found."""
        if not os.path.exists(self._config_path):
            return {}
        with open(self._config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _get_selected_model(self) -> tuple[str, str]:
        """Get the user's selected model from config.
        
        Returns:
            Tuple of (provider_name, model_id)
            
        Raises:
            LLMProviderError if no model is selected
        """
        config = self._read_config()
        models_config = config.get("models", {})
        selected = models_config.get("selected_model", "")
        
        if not selected:
            raise LLMProviderError(
                "No AI model selected. Please go to Settings > AI Models and select a model."
            )
        
        # Format is "provider:model_id" (e.g., "openai:gpt-4o")
        if ":" not in selected:
            raise LLMProviderError(
                f"Invalid model format '{selected}'. Expected 'provider:model_id'."
            )
        
        provider, model_id = selected.split(":", 1)
        return provider.lower(), model_id

    def _get_provider_config(self, provider_name: str) -> dict:
        """Get provider configuration (api_key, base_url) from config."""
        config = self._read_config()
        providers = config.get("providers", {})
        return providers.get(provider_name, {})

    def _get_provider(self, override: Optional[str] = None) -> LLMProvider:
        """Get an LLM provider instance based on user's selected model.
        
        Args:
            override: Optional override in format "provider:model" or just "provider"
        """
        if override:
            # Support both "provider:model" and "provider" formats for override
            if ":" in override:
                provider_name, model_id = override.split(":", 1)
            else:
                provider_name = override
                _, model_id = self._get_selected_model()
            provider_name = provider_name.lower()
        else:
            provider_name, model_id = self._get_selected_model()
        
        provider_config = self._get_provider_config(provider_name)
        api_key = provider_config.get("api_key", "")
        base_url = provider_config.get("base_url", "")
        
        if provider_name == "ollama":
            if not base_url:
                base_url = "http://127.0.0.1:11434"
            return OllamaProvider(base_url=base_url, model=model_id)
        
        if provider_name == "openai":
            if not api_key:
                raise LLMProviderError(
                    "Missing OpenAI API key. Please configure it in Settings > AI Models."
                )
            return OpenAIProvider(
                api_key=api_key,
                model=model_id,
                base_url=base_url if base_url else None,
            )
        
        if provider_name == "anthropic":
            if not api_key:
                raise LLMProviderError(
                    "Missing Anthropic API key. Please configure it in Settings > AI Models."
                )
            return AnthropicProvider(api_key=api_key, model=model_id)
        
        if provider_name == "gemini":
            if not api_key:
                raise LLMProviderError(
                    "Missing Gemini API key. Please configure it in Settings > AI Models."
                )
            return GeminiProvider(api_key=api_key, model=model_id)
        
        if provider_name == "grok":
            if not api_key:
                raise LLMProviderError(
                    "Missing Grok API key. Please configure it in Settings > AI Models."
                )
            return GrokProvider(api_key=api_key, model=model_id)
        
        if provider_name == "lmstudio":
            if not base_url:
                base_url = "http://127.0.0.1:1234"
            return OpenAIProvider(
                api_key="lmstudio",
                model=model_id,
                base_url=base_url,
            )
        
        raise LLMProviderError(f"Unknown provider: {provider_name}")

    def summarize(
        self, transcript: str, provider_override: Optional[str] = None
    ) -> dict:
        if not transcript.strip():
            raise LLMProviderError("Transcript is empty")
        provider = self._get_provider(provider_override)
        self._logger.info("Summarization using provider=%s", provider.__class__.__name__)

        prompt_path = os.path.join(self._prompts_dir, "summary_prompt.txt")
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                template = f.read()
        except OSError as exc:
            raise LLMProviderError(f"Missing summary prompt file: {prompt_path}") from exc

        prompt = template.replace("{{transcript}}", transcript)
        # Use raw prompt and parse JSON here so both manual + final share the same prompt file.
        content = provider.prompt(prompt)
        # Providers based on BaseLLMProvider may wrap JSON in markdown fences; strip if present.
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            stripped = []
            for line in lines:
                if line.startswith("```"):
                    continue
                stripped.append(line)
            text = "\n".join(stripped).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            self._logger.warning("Non-JSON response for summarize prompt file, using raw text")
            return {"summary": content.strip(), "action_items": []}
        return {
            "summary": str(parsed.get("summary", "")).strip(),
            "action_items": parsed.get("action_items", []) or [],
        }

    def generate_title(
        self, summary: str, provider_override: Optional[str] = None
    ) -> str:
        if not summary.strip():
            raise LLMProviderError("Summary is empty")
        provider = self._get_provider(provider_override)
        self._title_logger.info(
            "Title generation using provider=%s", provider.__class__.__name__
        )
        return provider.generate_title(summary)

    def is_meaningful_summary(
        self, summary: str, provider_override: Optional[str] = None
    ) -> bool:
        if not summary.strip():
            return False
        provider = self._get_provider(provider_override)
        try:
            return provider.classify_subject_confidence(summary)
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(str(exc)) from exc

    def cleanup_transcript(
        self, transcript: str, provider_override: Optional[str] = None
    ) -> str:
        if not transcript.strip():
            raise LLMProviderError("Transcript is empty")
        provider = self._get_provider(provider_override)
        return provider.cleanup_transcript(transcript)

    def segment_topics(
        self, transcript: str, provider_override: Optional[str] = None
    ) -> list[dict]:
        if not transcript.strip():
            raise LLMProviderError("Transcript is empty")
        provider = self._get_provider(provider_override)
        return provider.segment_topics(transcript)

    def prompt_raw(
        self, prompt: str, provider_override: Optional[str] = None
    ) -> str:
        """Send a raw prompt to the LLM and return the response text."""
        if not prompt.strip():
            raise LLMProviderError("Prompt is empty")
        provider = self._get_provider(provider_override)
        self._logger.info("Raw prompt using provider=%s", provider.__class__.__name__)
        return provider.prompt(prompt)

    def summarize_stream(
        self, transcript: str, provider_override: Optional[str] = None
    ) -> Generator[str, None, None]:
        """Stream summary tokens as they are generated.
        
        Uses the summary prompt template and streams the LLM response token by token.
        
        Args:
            transcript: The transcript to summarize
            provider_override: Optional override for the LLM provider
            
        Yields:
            Token strings as they arrive from the LLM
        """
        if not transcript.strip():
            raise LLMProviderError("Transcript is empty")
        
        provider = self._get_provider(provider_override)
        self._logger.info("Streaming summarization using provider=%s", provider.__class__.__name__)

        prompt_path = os.path.join(self._prompts_dir, "summary_prompt.txt")
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                template = f.read()
        except OSError as exc:
            raise LLMProviderError(f"Missing summary prompt file: {prompt_path}") from exc

        prompt = template.replace("{{transcript}}", transcript)
        yield from provider.prompt_stream(prompt)

    def identify_speaker_name(
        self,
        speaker_id: str,
        speaker_segments: list[dict],
        provider_override: Optional[str] = None,
    ) -> Optional[dict]:
        """Identify a speaker's name from their dialogue.
        
        Uses LLM to analyze what a speaker said and try to identify their name.
        
        Args:
            speaker_id: The speaker identifier (e.g., "SPEAKER_00")
            speaker_segments: List of transcript segments for this speaker
            provider_override: Optional override for the LLM provider
            
        Returns:
            Dict with keys:
                - name: The identified name (str) or None
                - confidence: "high", "medium", or "low"
                - reasoning: Explanation of how the name was identified
            Or None if identification failed.
        """
        if not speaker_segments:
            return None
        
        # Build speaker's dialogue text
        speaker_text = "\n".join(
            f"[{seg.get('start', 0):.1f}s] {seg.get('text', '')}"
            for seg in speaker_segments[:20]  # Limit to first 20 segments
        )
        
        if not speaker_text.strip():
            return None
        
        # Load prompt template
        prompt_path = os.path.join(self._prompts_dir, "identify_speaker_prompt.txt")
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                template = f.read()
        except OSError as exc:
            self._logger.warning("Missing speaker prompt file: %s", exc)
            return None
        
        # Build prompt
        prompt = template.replace("{{speaker_id}}", speaker_id)
        prompt = prompt.replace("{{speaker_text}}", speaker_text)
        
        # Get response from LLM
        try:
            provider = self._get_provider(provider_override)
            self._logger.info(
                "Identifying speaker %s using provider=%s",
                speaker_id, provider.__class__.__name__
            )
            content = provider.prompt(prompt)
        except Exception as exc:
            self._logger.warning("LLM call failed for speaker identification: %s", exc)
            return None
        
        # Parse JSON response
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            stripped = []
            for line in lines:
                if line.startswith("```"):
                    continue
                stripped.append(line)
            text = "\n".join(stripped).strip()
        
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            self._logger.warning(
                "Non-JSON response for speaker identification: %s",
                text[:200]
            )
            return None
        
        name = parsed.get("name")
        confidence = parsed.get("confidence", "low")
        reasoning = parsed.get("reasoning", "")
        
        # Only return a name if confidence is not low or name is explicitly provided
        if not name:
            self._logger.debug(
                "Could not identify speaker %s: %s",
                speaker_id, reasoning
            )
            return None
        
        return {
            "name": str(name).strip(),
            "confidence": confidence,
            "reasoning": reasoning,
        }

    def identify_all_speakers(
        self,
        segments: list,
        speaker_ids: list,
        provider_override: Optional[str] = None,
    ) -> list:
        """Identify names for multiple speakers in a single LLM call.

        Builds a representative transcript excerpt with speaker labels and asks
        the LLM to identify all speakers at once.  This is more token-efficient
        and more accurate than per-speaker calls because the model can see
        cross-speaker context (e.g., "Thanks, Sarah").

        Args:
            segments: All transcript segments (each has 'speaker', 'text', 'start').
            speaker_ids: Speaker IDs to identify (manual names already filtered out).
            provider_override: Optional LLM provider override.

        Returns:
            List of dicts, each with keys: speaker_id, name (str|None),
            confidence ("high"|"medium"|"low"), reasoning (str).
            Returns an empty list on failure.
        """
        if not segments or not speaker_ids:
            return []

        # Build a representative transcript with speaker labels.
        # Include up to the first 10 and last 10 segments per speaker to
        # keep token count manageable while capturing introductions (early)
        # and later cross-references.
        speaker_segments: dict = {}
        for seg in segments:
            spk = seg.get("speaker")
            if spk and spk in speaker_ids:
                speaker_segments.setdefault(spk, []).append(seg)

        # Also include segments from OTHER speakers — they may address
        # our target speakers by name.
        other_segments = [
            seg for seg in segments
            if seg.get("speaker") and seg["speaker"] not in speaker_ids
        ]

        # Build the excerpt: interleave in chronological order
        selected = []
        for spk, segs in speaker_segments.items():
            if len(segs) <= 20:
                selected.extend(segs)
            else:
                selected.extend(segs[:10])
                selected.extend(segs[-10:])

        # Add a sample of other-speaker segments for cross-references
        if other_segments:
            if len(other_segments) <= 20:
                selected.extend(other_segments)
            else:
                selected.extend(other_segments[:10])
                selected.extend(other_segments[-10:])

        # Sort chronologically
        selected.sort(key=lambda s: s.get("start", 0))

        transcript_lines = []
        for seg in selected:
            spk = seg.get("speaker", "UNKNOWN")
            text = seg.get("text", "").strip()
            start = seg.get("start", 0)
            if text:
                transcript_lines.append(f"[{start:.1f}s] [{spk}]: {text}")

        transcript_text = "\n".join(transcript_lines)
        if not transcript_text.strip():
            return []

        ids_text = "\n".join(f"- {sid}" for sid in speaker_ids)

        # Load prompt template
        prompt_path = os.path.join(self._prompts_dir, "identify_all_speakers_prompt.txt")
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                template = f.read()
        except OSError as exc:
            self._logger.warning("Missing batch speaker prompt file: %s", exc)
            return []

        prompt = template.replace("{{speaker_ids}}", ids_text)
        prompt = prompt.replace("{{transcript}}", transcript_text)

        # Single LLM call
        try:
            provider = self._get_provider(provider_override)
            self._logger.info(
                "Batch identifying %d speakers using provider=%s",
                len(speaker_ids),
                provider.__class__.__name__,
            )
            content = provider.prompt(prompt)
        except Exception as exc:
            self._logger.warning("LLM call failed for batch speaker identification: %s", exc)
            return []

        # Parse JSON array response
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(line for line in lines if not line.startswith("```")).strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            self._logger.warning(
                "Non-JSON response for batch speaker identification: %s",
                text[:300],
            )
            return []

        if not isinstance(parsed, list):
            self._logger.warning("Expected JSON array for batch speaker identification, got %s", type(parsed).__name__)
            return []

        # Normalise and filter
        results = []
        for entry in parsed:
            if not isinstance(entry, dict):
                continue
            sid = entry.get("speaker_id")
            name = entry.get("name")
            confidence = entry.get("confidence", "low")
            reasoning = entry.get("reasoning", "")

            if not sid or sid not in speaker_ids:
                continue

            # Treat low-confidence as unidentified
            if name and confidence == "low":
                name = None

            results.append({
                "speaker_id": str(sid),
                "name": str(name).strip() if name else None,
                "confidence": confidence,
                "reasoning": reasoning,
            })

        return results
