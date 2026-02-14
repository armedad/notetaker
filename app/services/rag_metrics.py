"""RAG metrics collection service for always-on monitoring.

This module provides runtime metrics collection for RAG query efficiency.
All classes, methods, and fields are prefixed with 'test_' to clearly
indicate this is debug/test infrastructure, not core application logic.
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class TestRAGQueryRecord:
    """Record of a single RAG query's data access patterns."""
    
    test_query_id: str
    test_start_time: float
    test_end_time: Optional[float] = None
    test_query_type: str = ""  # 'meeting_chat' or 'overall_chat'
    test_meeting_id: Optional[str] = None
    
    # Data access counts
    test_get_meeting_calls: int = 0
    test_list_meetings_calls: int = 0
    test_search_calls: int = 0
    
    # Data sizes
    test_meetings_loaded: int = 0
    test_total_transcript_chars: int = 0
    test_total_summary_chars: int = 0
    test_search_results_count: int = 0
    
    # Prompt stats
    test_input_prompt_chars: int = 0
    test_output_response_chars: int = 0
    
    def test_duration_ms(self) -> int:
        """Calculate query duration in milliseconds."""
        if self.test_end_time is None:
            return 0
        return int((self.test_end_time - self.test_start_time) * 1000)
    
    def test_estimated_input_tokens(self) -> int:
        """Estimate input tokens (rough: ~4 chars per token)."""
        return self.test_input_prompt_chars // 4
    
    def test_estimated_output_tokens(self) -> int:
        """Estimate output tokens (rough: ~4 chars per token)."""
        return self.test_output_response_chars // 4


class TestRAGMetrics:
    """Singleton service for collecting RAG query metrics.
    
    Tracks data access patterns and efficiency metrics for all RAG queries.
    Used for both always-on monitoring and on-demand testing.
    """
    
    _instance: Optional["TestRAGMetrics"] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> "TestRAGMetrics":
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._initialized = False
                cls._instance = instance
            return cls._instance
    
    def __init__(self) -> None:
        if self._initialized:
            return
        
        self._records: list[TestRAGQueryRecord] = []
        self._active_queries: dict[str, TestRAGQueryRecord] = {}
        self._records_lock = threading.Lock()
        self._query_counter = 0
        self._max_records = 100  # Keep last 100 queries
        self._initialized = True
    
    def test_start_query(
        self,
        query_type: str,
        meeting_id: Optional[str] = None,
    ) -> str:
        """Start tracking a new RAG query.
        
        Args:
            query_type: Type of query ('meeting_chat' or 'overall_chat')
            meeting_id: Optional meeting ID for context
            
        Returns:
            Unique query ID for this tracking session
        """
        with self._records_lock:
            self._query_counter += 1
            query_id = f"q{self._query_counter}_{int(time.time() * 1000)}"
        
        record = TestRAGQueryRecord(
            test_query_id=query_id,
            test_start_time=time.time(),
            test_query_type=query_type,
            test_meeting_id=meeting_id,
        )
        
        with self._records_lock:
            self._active_queries[query_id] = record
        
        return query_id
    
    def test_end_query(self, query_id: str) -> Optional[TestRAGQueryRecord]:
        """End tracking for a query and store the record.
        
        Args:
            query_id: The query ID returned by test_start_query
            
        Returns:
            The completed record, or None if query_id not found
        """
        with self._records_lock:
            record = self._active_queries.pop(query_id, None)
            if record is None:
                return None
            
            record.test_end_time = time.time()
            self._records.append(record)
            
            # Trim to max records
            if len(self._records) > self._max_records:
                self._records = self._records[-self._max_records:]
            
            return record
    
    def test_record_get_meeting(
        self,
        query_id: str,
        transcript_chars: int = 0,
        summary_chars: int = 0,
    ) -> None:
        """Record a get_meeting call during a query.
        
        Args:
            query_id: The active query ID
            transcript_chars: Size of transcript loaded
            summary_chars: Size of summary loaded
        """
        with self._records_lock:
            record = self._active_queries.get(query_id)
            if record:
                record.test_get_meeting_calls += 1
                record.test_meetings_loaded += 1
                record.test_total_transcript_chars += transcript_chars
                record.test_total_summary_chars += summary_chars
    
    def test_record_list_meetings(
        self,
        query_id: str,
        meetings_count: int = 0,
    ) -> None:
        """Record a list_meetings call during a query.
        
        Args:
            query_id: The active query ID
            meetings_count: Number of meetings in the result
        """
        with self._records_lock:
            record = self._active_queries.get(query_id)
            if record:
                record.test_list_meetings_calls += 1
                record.test_meetings_loaded += meetings_count
    
    def test_record_search(
        self,
        query_id: str,
        results_count: int = 0,
    ) -> None:
        """Record a search call during a query.
        
        Args:
            query_id: The active query ID
            results_count: Number of search results
        """
        with self._records_lock:
            record = self._active_queries.get(query_id)
            if record:
                record.test_search_calls += 1
                record.test_search_results_count += results_count
    
    def test_record_prompt(
        self,
        query_id: str,
        input_chars: int = 0,
        output_chars: int = 0,
    ) -> None:
        """Record prompt/response sizes for a query.
        
        Args:
            query_id: The active query ID
            input_chars: Size of input prompt
            output_chars: Size of output response
        """
        with self._records_lock:
            record = self._active_queries.get(query_id)
            if record:
                record.test_input_prompt_chars += input_chars
                record.test_output_response_chars += output_chars
    
    def test_to_dict(self) -> dict:
        """Export all metrics as a dictionary.
        
        Returns:
            Dict with 'aggregate' stats and 'recent' query records
        """
        with self._records_lock:
            records = list(self._records)
        
        # Calculate aggregates
        total_queries = len(records)
        if total_queries == 0:
            return {
                "aggregate": {
                    "total_queries": 0,
                    "avg_duration_ms": 0,
                    "avg_input_tokens": 0,
                    "avg_output_tokens": 0,
                    "avg_meetings_loaded": 0,
                    "avg_search_calls": 0,
                },
                "recent": [],
            }
        
        total_duration = sum(r.test_duration_ms() for r in records)
        total_input_tokens = sum(r.test_estimated_input_tokens() for r in records)
        total_output_tokens = sum(r.test_estimated_output_tokens() for r in records)
        total_meetings = sum(r.test_meetings_loaded for r in records)
        total_search_calls = sum(r.test_search_calls for r in records)
        
        # Recent records (last 20)
        recent = []
        for r in records[-20:]:
            recent.append({
                "query_id": r.test_query_id,
                "query_type": r.test_query_type,
                "meeting_id": r.test_meeting_id,
                "duration_ms": r.test_duration_ms(),
                "input_tokens": r.test_estimated_input_tokens(),
                "output_tokens": r.test_estimated_output_tokens(),
                "meetings_loaded": r.test_meetings_loaded,
                "search_calls": r.test_search_calls,
                "timestamp": datetime.fromtimestamp(r.test_start_time).isoformat(),
            })
        
        return {
            "aggregate": {
                "total_queries": total_queries,
                "avg_duration_ms": total_duration // total_queries,
                "avg_input_tokens": total_input_tokens // total_queries,
                "avg_output_tokens": total_output_tokens // total_queries,
                "avg_meetings_loaded": total_meetings // total_queries,
                "avg_search_calls": total_search_calls // total_queries,
            },
            "recent": list(reversed(recent)),  # Newest first
        }
    
    def test_reset(self) -> None:
        """Clear all collected metrics."""
        with self._records_lock:
            self._records.clear()
            self._active_queries.clear()
