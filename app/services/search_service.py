"""Search service for finding relevant meetings by keyword matching."""

import logging
import re
from dataclasses import dataclass
from typing import Optional

from app.services.meeting_store import MeetingStore


@dataclass
class SearchResult:
    """A search result with meeting data and relevance score."""
    meeting_id: str
    title: str
    created_at: str
    summary: Optional[str]
    transcript_text: Optional[str]
    score: float
    match_reason: str


@dataclass
class SearchMatch:
    """A single search match with field-level detail and snippet."""
    meeting_id: str
    meeting_title: str
    created_at: str
    field_type: str  # "title", "summary", "transcript", "attendee", "user_note", "manual_notes", "chat"
    snippet: str  # Text around the match (~100 chars)
    score: float
    
    def to_dict(self) -> dict:
        return {
            "meeting_id": self.meeting_id,
            "meeting_title": self.meeting_title,
            "created_at": self.created_at,
            "field_type": self.field_type,
            "snippet": self.snippet,
            "score": self.score,
        }


class SearchService:
    """Service for searching meetings by keyword matching on titles and summaries."""
    
    def __init__(self, meeting_store: MeetingStore) -> None:
        self._meeting_store = meeting_store
        self._logger = logging.getLogger("notetaker.search")
    
    def _tokenize(self, text: str) -> set[str]:
        """Tokenize text into lowercase words."""
        if not text:
            return set()
        # Split on non-alphanumeric, convert to lowercase, filter short words
        words = re.findall(r'\b[a-zA-Z0-9]+\b', text.lower())
        return {w for w in words if len(w) > 2}
    
    def _score_match(
        self,
        query_tokens: set[str],
        title: str,
        summary: str,
    ) -> tuple[float, str]:
        """Calculate relevance score and match reason.
        
        Returns:
            Tuple of (score, match_reason)
            - Title matches score higher than summary matches
            - More matching tokens = higher score
        """
        title_tokens = self._tokenize(title)
        summary_tokens = self._tokenize(summary)
        
        title_matches = query_tokens & title_tokens
        summary_matches = query_tokens & summary_tokens
        
        # Title matches are worth 2x summary matches
        score = len(title_matches) * 2.0 + len(summary_matches) * 1.0
        
        # Build match reason
        reasons = []
        if title_matches:
            reasons.append(f"title: {', '.join(sorted(title_matches))}")
        if summary_matches:
            # Only show summary matches not already in title
            unique_summary = summary_matches - title_matches
            if unique_summary:
                reasons.append(f"summary: {', '.join(sorted(unique_summary))}")
        
        match_reason = "; ".join(reasons) if reasons else "no direct match"
        
        return score, match_reason
    
    def search_meetings(
        self,
        query: str,
        limit: int = 5,
        exclude_meeting_id: Optional[str] = None,
    ) -> list[SearchResult]:
        """Search meetings by keyword matching on titles and summaries.
        
        Args:
            query: The search query string
            limit: Maximum number of results to return
            exclude_meeting_id: Optional meeting ID to exclude from results
            
        Returns:
            List of SearchResult objects sorted by relevance score (descending)
        """
        query_tokens = self._tokenize(query)
        if not query_tokens:
            self._logger.debug("Empty query tokens, returning empty results")
            return []
        
        self._logger.debug("Searching for tokens: %s", query_tokens)
        
        meetings = self._meeting_store.list_meetings()
        results: list[SearchResult] = []
        
        for meeting in meetings:
            meeting_id = meeting.get("id", "")
            
            # Skip excluded meeting
            if exclude_meeting_id and meeting_id == exclude_meeting_id:
                continue
            
            title = meeting.get("title", "")
            summary_data = meeting.get("summary")
            summary = summary_data.get("text", "") if isinstance(summary_data, dict) else ""
            
            score, match_reason = self._score_match(query_tokens, title, summary)
            
            # Only include if there's some match
            if score > 0:
                # Get full transcript text if needed
                transcript_text = None
                transcript = meeting.get("transcript")
                if isinstance(transcript, dict):
                    segments = transcript.get("segments", [])
                    if segments:
                        transcript_text = " ".join(
                            seg.get("text", "") for seg in segments
                        )
                
                results.append(SearchResult(
                    meeting_id=meeting_id,
                    title=title,
                    created_at=meeting.get("created_at", ""),
                    summary=summary,
                    transcript_text=transcript_text,
                    score=score,
                    match_reason=match_reason,
                ))
        
        # Sort by score descending
        results.sort(key=lambda r: r.score, reverse=True)
        
        # Limit results
        results = results[:limit]
        
        self._logger.info(
            "Search for '%s' found %d results (top score: %.1f)",
            query,
            len(results),
            results[0].score if results else 0,
        )
        
        return results
    
    def get_meeting_context(self, meeting_id: str) -> Optional[dict]:
        """Get full context for a specific meeting.
        
        Returns:
            Dict with title, summary, transcript_text, created_at, or None if not found
        """
        meeting = self._meeting_store.get_meeting(meeting_id)
        if not meeting:
            return None
        
        title = meeting.get("title", "Untitled Meeting")
        
        summary_data = meeting.get("summary")
        summary = summary_data.get("text", "") if isinstance(summary_data, dict) else ""
        
        transcript_text = ""
        transcript = meeting.get("transcript")
        if isinstance(transcript, dict):
            segments = transcript.get("segments", [])
            if segments:
                transcript_text = " ".join(
                    seg.get("text", "") for seg in segments
                )
        
        return {
            "meeting_id": meeting_id,
            "title": title,
            "summary": summary,
            "transcript_text": transcript_text,
            "created_at": meeting.get("created_at", ""),
        }
    
    def _extract_snippet(self, text: str, query: str, context_chars: int = 50) -> str:
        """Extract a snippet around the first match of query in text.
        
        Args:
            text: The text to search in
            query: The search query (case-insensitive)
            context_chars: Number of characters to include before/after match
            
        Returns:
            Snippet with ellipsis if truncated
        """
        if not text or not query:
            return ""
        
        text_lower = text.lower()
        query_lower = query.lower()
        
        # Find first occurrence
        idx = text_lower.find(query_lower)
        if idx == -1:
            # No exact match, return start of text
            return text[:context_chars * 2] + ("..." if len(text) > context_chars * 2 else "")
        
        # Calculate snippet boundaries
        start = max(0, idx - context_chars)
        end = min(len(text), idx + len(query) + context_chars)
        
        snippet = text[start:end]
        
        # Add ellipsis
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        
        return snippet
    
    def _find_match_in_text(self, text: str, query_lower: str) -> bool:
        """Check if query appears in text (case-insensitive)."""
        if not text:
            return False
        return query_lower in text.lower()
    
    def search_all_fields(
        self,
        query: str,
        limit: int = 50,
    ) -> list[SearchMatch]:
        """Search all meeting fields and return matches with snippets.
        
        Searches across:
        - title (weight: 3x)
        - summary (weight: 2x)
        - transcript (weight: 1x)
        - attendee names (weight: 2x)
        - user_notes (weight: 1.5x)
        - manual_notes (weight: 1x)
        - chat_history (weight: 1x)
        
        Args:
            query: The search query string
            limit: Maximum number of matches to return
            
        Returns:
            List of SearchMatch objects sorted by score descending
        """
        if not query or len(query.strip()) < 2:
            return []
        
        query = query.strip()
        query_lower = query.lower()
        
        meetings = self._meeting_store.list_meetings()
        matches: list[SearchMatch] = []
        
        # Field weights
        WEIGHTS = {
            "title": 3.0,
            "summary": 2.0,
            "attendee": 2.0,
            "user_note": 1.5,
            "transcript": 1.0,
            "manual_notes": 1.0,
            "chat": 1.0,
        }
        
        for meeting in meetings:
            meeting_id = meeting.get("id", "")
            title = meeting.get("title", "Untitled Meeting")
            created_at = meeting.get("created_at", "")
            
            # Search title
            if self._find_match_in_text(title, query_lower):
                matches.append(SearchMatch(
                    meeting_id=meeting_id,
                    meeting_title=title,
                    created_at=created_at,
                    field_type="title",
                    snippet=self._extract_snippet(title, query),
                    score=WEIGHTS["title"],
                ))
            
            # Search summary
            summary_data = meeting.get("summary")
            summary_text = summary_data.get("text", "") if isinstance(summary_data, dict) else ""
            if self._find_match_in_text(summary_text, query_lower):
                matches.append(SearchMatch(
                    meeting_id=meeting_id,
                    meeting_title=title,
                    created_at=created_at,
                    field_type="summary",
                    snippet=self._extract_snippet(summary_text, query),
                    score=WEIGHTS["summary"],
                ))
            
            # Search attendees
            attendees = meeting.get("attendees", [])
            for attendee in attendees:
                name = attendee.get("name", "")
                if self._find_match_in_text(name, query_lower):
                    matches.append(SearchMatch(
                        meeting_id=meeting_id,
                        meeting_title=title,
                        created_at=created_at,
                        field_type="attendee",
                        snippet=f"Attendee: {name}",
                        score=WEIGHTS["attendee"],
                    ))
                    break  # Only one match per meeting for attendees
            
            # Search user_notes
            user_notes = meeting.get("user_notes", [])
            for note in user_notes:
                note_text = note.get("text", "")
                if self._find_match_in_text(note_text, query_lower):
                    matches.append(SearchMatch(
                        meeting_id=meeting_id,
                        meeting_title=title,
                        created_at=created_at,
                        field_type="user_note",
                        snippet=self._extract_snippet(note_text, query),
                        score=WEIGHTS["user_note"],
                    ))
                    break  # Only one match per meeting for user notes
            
            # Search manual_notes
            manual_notes = meeting.get("manual_notes", "")
            if self._find_match_in_text(manual_notes, query_lower):
                matches.append(SearchMatch(
                    meeting_id=meeting_id,
                    meeting_title=title,
                    created_at=created_at,
                    field_type="manual_notes",
                    snippet=self._extract_snippet(manual_notes, query),
                    score=WEIGHTS["manual_notes"],
                ))
            
            # Search transcript
            transcript = meeting.get("transcript")
            if isinstance(transcript, dict):
                segments = transcript.get("segments", [])
                for segment in segments:
                    seg_text = segment.get("text", "")
                    if self._find_match_in_text(seg_text, query_lower):
                        matches.append(SearchMatch(
                            meeting_id=meeting_id,
                            meeting_title=title,
                            created_at=created_at,
                            field_type="transcript",
                            snippet=self._extract_snippet(seg_text, query),
                            score=WEIGHTS["transcript"],
                        ))
                        break  # Only one match per meeting for transcript
            
            # Search chat_history
            chat_history = meeting.get("chat_history", [])
            for chat_msg in chat_history:
                content = chat_msg.get("content", "")
                if self._find_match_in_text(content, query_lower):
                    matches.append(SearchMatch(
                        meeting_id=meeting_id,
                        meeting_title=title,
                        created_at=created_at,
                        field_type="chat",
                        snippet=self._extract_snippet(content, query),
                        score=WEIGHTS["chat"],
                    ))
                    break  # Only one match per meeting for chat
        
        # Sort by score descending, then by created_at descending
        matches.sort(key=lambda m: (m.score, m.created_at), reverse=True)
        
        # Limit results
        matches = matches[:limit]
        
        self._logger.info(
            "Full search for '%s' found %d matches",
            query,
            len(matches),
        )
        
        return matches
