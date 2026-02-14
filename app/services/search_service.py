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
