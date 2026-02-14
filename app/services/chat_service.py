"""Chat service for AI-powered meeting queries."""

import logging
import os
from typing import Generator, Optional

from app.services.llm import LLMProviderError
from app.services.meeting_store import MeetingStore
from app.services.search_service import SearchService
from app.services.summarization import SummarizationService


class ChatService:
    """Service for AI-powered chat queries about meetings.
    
    Supports two modes:
    1. Meeting Chat - Query about a specific meeting with optional cross-meeting context
    2. Overall Chat - Query across all meetings using hybrid search
    """
    
    def __init__(
        self,
        meeting_store: MeetingStore,
        summarization_service: SummarizationService,
        search_service: SearchService,
    ) -> None:
        self._meeting_store = meeting_store
        self._summarization = summarization_service
        self._search = search_service
        self._logger = logging.getLogger("notetaker.chat")
        self._prompts_dir = os.path.join(os.path.dirname(__file__), "..", "prompts")
    
    def _load_prompt_template(self, filename: str) -> str:
        """Load a prompt template from the prompts directory."""
        prompt_path = os.path.join(self._prompts_dir, filename)
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError as exc:
            raise LLMProviderError(f"Missing prompt file: {prompt_path}") from exc
    
    def _format_meeting_context(self, meeting: dict) -> str:
        """Format a meeting's data into context text."""
        title = meeting.get("title", "Untitled Meeting")
        created_at = meeting.get("created_at", "Unknown date")
        
        summary_data = meeting.get("summary")
        summary = summary_data.get("text", "") if isinstance(summary_data, dict) else ""
        
        transcript_text = ""
        transcript = meeting.get("transcript")
        if isinstance(transcript, dict):
            segments = transcript.get("segments", [])
            if segments:
                transcript_text = "\n".join(
                    f"[{seg.get('start', 0):.1f}s] {seg.get('text', '')}"
                    for seg in segments
                )
        
        return f"""Meeting: {title}
Date: {created_at}

Summary:
{summary if summary else "(No summary available)"}

Transcript:
{transcript_text if transcript_text else "(No transcript available)"}"""
    
    def _build_meeting_chat_prompt(
        self,
        question: str,
        meeting: dict,
        related_context: Optional[str] = None,
    ) -> str:
        """Build the prompt for meeting-specific chat."""
        template = self._load_prompt_template("meeting_chat_prompt.txt")
        
        title = meeting.get("title", "Untitled Meeting")
        created_at = meeting.get("created_at", "Unknown date")
        
        summary_data = meeting.get("summary")
        summary = summary_data.get("text", "") if isinstance(summary_data, dict) else ""
        
        transcript_text = ""
        transcript = meeting.get("transcript")
        if isinstance(transcript, dict):
            segments = transcript.get("segments", [])
            if segments:
                transcript_text = "\n".join(
                    f"[{seg.get('start', 0):.1f}s] {seg.get('text', '')}"
                    for seg in segments
                )
        
        # Replace template variables
        prompt = template.replace("{{meeting_title}}", title)
        prompt = prompt.replace("{{meeting_date}}", created_at)
        prompt = prompt.replace("{{summary}}", summary if summary else "(No summary available)")
        prompt = prompt.replace("{{transcript}}", transcript_text if transcript_text else "(No transcript available)")
        prompt = prompt.replace("{{question}}", question)
        
        # Handle optional related context
        if related_context:
            prompt = prompt.replace("{{related_context}}", related_context)
            prompt = prompt.replace("{{#if related_context}}", "")
            prompt = prompt.replace("{{/if}}", "")
        else:
            # Remove the related context block
            import re
            prompt = re.sub(
                r'\{\{#if related_context\}\}.*?\{\{/if\}\}',
                '',
                prompt,
                flags=re.DOTALL
            )
        
        return prompt
    
    def _build_overall_chat_prompt(
        self,
        question: str,
        meetings: list[dict],
        include_transcripts: bool = True,
    ) -> str:
        """Build the prompt for overall chat across meetings."""
        template = self._load_prompt_template("overall_chat_prompt.txt")
        
        # Build meetings context
        meetings_text = ""
        for meeting in meetings:
            title = meeting.get("title", "Untitled Meeting")
            created_at = meeting.get("created_at", "Unknown date")
            
            summary_data = meeting.get("summary")
            summary = summary_data.get("text", "") if isinstance(summary_data, dict) else ""
            
            meetings_text += f"""---
Meeting: {title}
Date: {created_at}
Summary: {summary if summary else "(No summary)"}
"""
            
            if include_transcripts:
                transcript_text = ""
                transcript = meeting.get("transcript")
                if isinstance(transcript, dict):
                    segments = transcript.get("segments", [])
                    if segments:
                        transcript_text = "\n".join(
                            f"[{seg.get('start', 0):.1f}s] {seg.get('text', '')}"
                            for seg in segments
                        )
                if transcript_text:
                    meetings_text += f"Transcript:\n{transcript_text}\n"
            
            meetings_text += "---\n"
        
        # Replace template variables
        prompt = template.replace("{{meetings}}", meetings_text)
        prompt = prompt.replace("{{question}}", question)
        
        # Handle template conditionals (simplified - remove the template syntax)
        prompt = prompt.replace("{{#each meetings}}", "")
        prompt = prompt.replace("{{/each}}", "")
        prompt = prompt.replace("{{title}}", "")
        prompt = prompt.replace("{{date}}", "")
        prompt = prompt.replace("{{#if include_transcript}}", "")
        prompt = prompt.replace("{{/if}}", "")
        
        return prompt
    
    def chat_meeting(
        self,
        meeting_id: str,
        question: str,
        include_related: bool = False,
    ) -> Generator[str, None, None]:
        """Chat about a specific meeting.
        
        Args:
            meeting_id: The ID of the meeting to query
            question: The user's question
            include_related: Whether to search for related context from other meetings
            
        Yields:
            Token strings as they arrive from the LLM
        """
        meeting = self._meeting_store.get_meeting(meeting_id)
        if not meeting:
            raise LLMProviderError(f"Meeting not found: {meeting_id}")
        
        self._logger.info(
            "Meeting chat: meeting_id=%s question='%s' include_related=%s",
            meeting_id, question[:50], include_related
        )
        
        # Optionally get related context from other meetings
        related_context = None
        if include_related:
            search_results = self._search.search_meetings(
                question, limit=3, exclude_meeting_id=meeting_id
            )
            if search_results:
                related_parts = []
                for result in search_results:
                    related_parts.append(
                        f"From '{result.title}' ({result.created_at}):\n{result.summary or '(No summary)'}"
                    )
                related_context = "\n\n".join(related_parts)
                self._logger.debug("Found %d related meetings", len(search_results))
        
        # Build prompt
        prompt = self._build_meeting_chat_prompt(question, meeting, related_context)
        
        # Stream response from LLM
        provider = self._summarization._get_provider()
        self._logger.info("Chat using provider=%s", provider.__class__.__name__)
        
        yield from provider.prompt_stream(prompt)
    
    def chat_overall(
        self,
        question: str,
        max_meetings: int = 5,
        include_transcripts: bool = True,
    ) -> Generator[str, None, None]:
        """Chat across all meetings using hybrid search.
        
        Args:
            question: The user's question
            max_meetings: Maximum number of meetings to include in context
            include_transcripts: Whether to include full transcripts for top matches
            
        Yields:
            Token strings as they arrive from the LLM
        """
        # #region agent log
        import time as _time
        import json as _json
        _log_path = "/Users/chee/zapier ai project/.cursor/debug.log"
        def _dbg(msg, data):
            with open(_log_path, "a") as _f:
                _f.write(_json.dumps({"location":"chat_service.py:chat_overall","message":msg,"data":data,"timestamp":int(_time.time()*1000),"runId":"chat-debug","hypothesisId":"H1-H4"})+"\n")
        _dbg("entry", {"question": question[:100], "max_meetings": max_meetings})
        # #endregion
        
        self._logger.info(
            "Overall chat: question='%s' max_meetings=%d include_transcripts=%s",
            question[:50], max_meetings, include_transcripts
        )
        
        # Search for relevant meetings
        search_results = self._search.search_meetings(question, limit=max_meetings)
        
        # #region agent log
        _dbg("search_results", {"count": len(search_results), "titles": [r.title for r in search_results[:3]]})
        # #endregion
        
        if not search_results:
            # No matches - get recent meetings instead
            self._logger.info("No search matches, using recent meetings")
            all_meetings = self._meeting_store.list_meetings()
            meetings = all_meetings[:max_meetings]
            # #region agent log
            _dbg("fallback_to_recent", {"recent_count": len(meetings), "titles": [m.get("title","") for m in meetings[:3]]})
            # #endregion
        else:
            # Load full meeting data for search results
            meetings = []
            for result in search_results:
                meeting = self._meeting_store.get_meeting(result.meeting_id)
                if meeting:
                    meetings.append(meeting)
            self._logger.info(
                "Found %d relevant meetings (top: %s, score: %.1f)",
                len(meetings),
                search_results[0].title if search_results else "N/A",
                search_results[0].score if search_results else 0,
            )
        
        if not meetings:
            raise LLMProviderError("No meetings available to query.")
        
        # Build prompt
        prompt = self._build_overall_chat_prompt(question, meetings, include_transcripts)
        
        # #region agent log
        _dbg("prompt_built", {"prompt_len": len(prompt), "has_question": question in prompt, "meetings_in_prompt": len(meetings)})
        # #endregion
        
        # Stream response from LLM
        provider = self._summarization._get_provider()
        self._logger.info("Chat using provider=%s", provider.__class__.__name__)
        
        # #region agent log
        _dbg("calling_provider", {"provider": provider.__class__.__name__})
        # #endregion
        
        yield from provider.prompt_stream(prompt)
    
    def chat_meeting_sync(
        self,
        meeting_id: str,
        question: str,
        include_related: bool = False,
    ) -> str:
        """Non-streaming version of chat_meeting for simple use cases."""
        tokens = list(self.chat_meeting(meeting_id, question, include_related))
        return "".join(tokens)
    
    def chat_overall_sync(
        self,
        question: str,
        max_meetings: int = 5,
        include_transcripts: bool = True,
    ) -> str:
        """Non-streaming version of chat_overall for simple use cases."""
        tokens = list(self.chat_overall(question, max_meetings, include_transcripts))
        return "".join(tokens)
