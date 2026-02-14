"""LLM instrumentation for observability and debugging.

This module provides two-level instrumentation for capturing LLM calls:
- Level 1: Service wrappers that set context (stem, metadata, timing)
- Level 2: BaseLLMProvider patch that captures actual prompts/responses

All functions, variables, and patches are prefixed with 'test_' to clearly
indicate this is debug/test infrastructure, not core application logic.
"""

import functools
import os
import time
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Callable, Generator, Optional

if TYPE_CHECKING:
    from app.services.chat_service import ChatService
    from app.services.llm_logger import TestLLMLogger
    from app.services.meeting_store import MeetingStore
    from app.services.rag_metrics import TestRAGMetrics
    from app.services.search_service import SearchService
    from app.services.summarization import SummarizationService


# Context variables for propagating state through async call stacks
_test_llm_call_stem: ContextVar[str] = ContextVar("_test_llm_call_stem", default="")
_test_llm_call_meta: ContextVar[dict] = ContextVar("_test_llm_call_meta", default={})
_test_log_this_request: ContextVar[bool] = ContextVar("_test_log_this_request", default=False)
_test_active_query_id: ContextVar[str] = ContextVar("_test_active_query_id", default="")


def test_install_instrumentation(
    meeting_store: "MeetingStore",
    search_service: "SearchService",
    summarization_service: "SummarizationService",
    chat_service: "ChatService",
    llm_logger: "TestLLMLogger",
    rag_metrics: "TestRAGMetrics",
) -> None:
    """Install two-level instrumentation for LLM observability.
    
    Level 1: Wraps high-level service methods to set context
    Level 2: Patches BaseLLMProvider to capture prompts/responses
    
    Args:
        meeting_store: MeetingStore instance to wrap
        search_service: SearchService instance to wrap
        summarization_service: SummarizationService instance to wrap
        chat_service: ChatService instance to wrap
        llm_logger: TestLLMLogger instance for writing logs
        rag_metrics: TestRAGMetrics instance for recording metrics
    """
    # Level 1: Wrap service methods
    _test_wrap_meeting_store(meeting_store, rag_metrics)
    _test_wrap_search_service(search_service, rag_metrics)
    _test_wrap_chat_service(chat_service, rag_metrics)
    _test_wrap_summarization_service(summarization_service)
    
    # Level 2: Patch BaseLLMProvider
    _test_patch_base_llm_provider(llm_logger, rag_metrics)


def _test_wrap_meeting_store(
    meeting_store: "MeetingStore",
    rag_metrics: "TestRAGMetrics",
) -> None:
    """Wrap MeetingStore methods to track data access."""
    original_get_meeting = meeting_store.get_meeting
    original_list_meetings = meeting_store.list_meetings
    
    @functools.wraps(original_get_meeting)
    def wrapped_get_meeting(meeting_id: str) -> Optional[dict]:
        result = original_get_meeting(meeting_id)
        
        query_id = _test_active_query_id.get()
        if query_id and result:
            # Calculate data sizes
            transcript_chars = 0
            summary_chars = 0
            
            transcript = result.get("transcript")
            if isinstance(transcript, dict):
                segments = transcript.get("segments", [])
                transcript_chars = sum(len(seg.get("text", "")) for seg in segments)
            
            summary_data = result.get("summary")
            if isinstance(summary_data, dict):
                summary_chars = len(summary_data.get("text", ""))
            
            rag_metrics.test_record_get_meeting(
                query_id,
                transcript_chars=transcript_chars,
                summary_chars=summary_chars,
            )
        
        return result
    
    @functools.wraps(original_list_meetings)
    def wrapped_list_meetings(*args: Any, **kwargs: Any) -> list:
        result = original_list_meetings(*args, **kwargs)
        
        query_id = _test_active_query_id.get()
        if query_id:
            rag_metrics.test_record_list_meetings(query_id, meetings_count=len(result))
        
        return result
    
    meeting_store.get_meeting = wrapped_get_meeting  # type: ignore
    meeting_store.list_meetings = wrapped_list_meetings  # type: ignore


def _test_wrap_search_service(
    search_service: "SearchService",
    rag_metrics: "TestRAGMetrics",
) -> None:
    """Wrap SearchService methods to track search operations."""
    original_search = search_service.search_meetings
    
    @functools.wraps(original_search)
    def wrapped_search(*args: Any, **kwargs: Any) -> list:
        result = original_search(*args, **kwargs)
        
        query_id = _test_active_query_id.get()
        if query_id:
            rag_metrics.test_record_search(query_id, results_count=len(result))
        
        return result
    
    search_service.search_meetings = wrapped_search  # type: ignore


def _test_wrap_chat_service(
    chat_service: "ChatService",
    rag_metrics: "TestRAGMetrics",
) -> None:
    """Wrap ChatService methods to track chat queries."""
    original_chat_meeting = chat_service.chat_meeting
    original_chat_overall = chat_service.chat_overall
    
    # #region agent log
    import json as _json
    _log_path = os.path.join(os.getcwd(), "logs", "debug.log")
    def _dbg(msg, data):
        import time as _time
        with open(_log_path, "a") as _f:
            _f.write(_json.dumps({"location":"llm_instrumentation.py","message":msg,"data":data,"timestamp":int(_time.time()*1000),"runId":"chat-wrap","hypothesisId":"H3"})+"\n")
    # #endregion
    
    @functools.wraps(original_chat_meeting)
    def wrapped_chat_meeting(
        meeting_id: str,
        question: str,
        include_related: bool = False,
    ) -> Generator[str, None, None]:
        # #region agent log
        _dbg("wrapped_chat_meeting_called", {"meeting_id": meeting_id, "question": question[:50]})
        # #endregion
        # Start tracking
        query_id = rag_metrics.test_start_query("meeting_chat", meeting_id=meeting_id)
        token_query_id = _test_active_query_id.set(query_id)
        
        # Set context for LLM logging
        token_stem = _test_llm_call_stem.set("meeting_chat")
        token_meta = _test_llm_call_meta.set({
            "meeting_id": meeting_id,
            "question": question,
        })
        
        try:
            response_tokens = []
            for token in original_chat_meeting(meeting_id, question, include_related):
                response_tokens.append(token)
                yield token
            
            # Record response size
            response_text = "".join(response_tokens)
            rag_metrics.test_record_prompt(
                query_id,
                output_chars=len(response_text),
            )
        finally:
            # End tracking
            rag_metrics.test_end_query(query_id)
            # ContextVar.reset() can fail when the generator's finally block
            # runs in a different async context (e.g. SSE streaming cleanup).
            try:
                _test_active_query_id.reset(token_query_id)
            except ValueError:
                pass
            try:
                _test_llm_call_stem.reset(token_stem)
            except ValueError:
                pass
            try:
                _test_llm_call_meta.reset(token_meta)
            except ValueError:
                pass
    
    @functools.wraps(original_chat_overall)
    def wrapped_chat_overall(
        question: str,
        max_meetings: int = 5,
        include_transcripts: bool = True,
    ) -> Generator[str, None, None]:
        # #region agent log
        _dbg("wrapped_chat_overall_called", {"question": question[:50], "max_meetings": max_meetings})
        # #endregion
        # Start tracking
        query_id = rag_metrics.test_start_query("overall_chat")
        token_query_id = _test_active_query_id.set(query_id)
        
        # Set context for LLM logging
        token_stem = _test_llm_call_stem.set("overall_chat")
        token_meta = _test_llm_call_meta.set({
            "question": question,
        })
        
        try:
            response_tokens = []
            for token in original_chat_overall(question, max_meetings, include_transcripts):
                response_tokens.append(token)
                yield token
            
            # Record response size
            response_text = "".join(response_tokens)
            rag_metrics.test_record_prompt(
                query_id,
                output_chars=len(response_text),
            )
        finally:
            # End tracking
            rag_metrics.test_end_query(query_id)
            try:
                _test_active_query_id.reset(token_query_id)
            except ValueError:
                pass
            try:
                _test_llm_call_stem.reset(token_stem)
            except ValueError:
                pass
            try:
                _test_llm_call_meta.reset(token_meta)
            except ValueError:
                pass
    
    chat_service.chat_meeting = wrapped_chat_meeting  # type: ignore
    chat_service.chat_overall = wrapped_chat_overall  # type: ignore


def _test_wrap_summarization_service(
    summarization_service: "SummarizationService",
) -> None:
    """Wrap SummarizationService methods to set LLM call stems."""
    # Map method names to their stems
    stem_map = {
        "summarize": "summarize",
        "summarize_stream": "summarize_stream",
        "generate_title": "generate_title",
        "is_meaningful_summary": "classify_subject",
        "cleanup_transcript": "cleanup_transcript",
        "segment_topics": "segment_topics",
        "prompt_raw": "prompt_raw",
        "identify_speaker_name": "identify_speaker",
    }
    
    for method_name, stem in stem_map.items():
        original = getattr(summarization_service, method_name)
        
        @functools.wraps(original)
        def make_wrapper(orig: Callable, s: str) -> Callable:
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                token = _test_llm_call_stem.set(s)
                try:
                    return orig(*args, **kwargs)
                finally:
                    _test_llm_call_stem.reset(token)
            return wrapper
        
        setattr(summarization_service, method_name, make_wrapper(original, stem))


def _test_patch_base_llm_provider(
    llm_logger: "TestLLMLogger",
    rag_metrics: "TestRAGMetrics",
) -> None:
    """Patch BaseLLMProvider to capture all LLM calls."""
    from app.services.llm.base import BaseLLMProvider
    
    original_call_api = BaseLLMProvider._call_api
    original_call_api_stream = BaseLLMProvider._call_api_stream
    
    def wrapped_call_api(
        self: BaseLLMProvider,
        prompt: str,
        temperature: float = 0.2,
        timeout: int = 120,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
    ) -> str:
        start_time = time.time()
        result = original_call_api(self, prompt, temperature, timeout, system_prompt, json_mode)
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Record prompt size for RAG metrics
        query_id = _test_active_query_id.get()
        if query_id:
            rag_metrics.test_record_prompt(query_id, input_chars=len(prompt))
        
        # Log if enabled or explicitly requested
        should_log = llm_logger.test_get_log_all() or _test_log_this_request.get()
        stem = _test_llm_call_stem.get()
        
        if should_log and stem:
            meta = _test_llm_call_meta.get()
            
            # Get provider and model info
            provider_name = self.__class__.__name__
            model = getattr(self, "_model", getattr(self, "model", "unknown"))
            
            llm_logger.test_log_call(
                stem=stem,
                provider=provider_name,
                model=model,
                temperature=temperature,
                input_prompt=prompt,
                output_response=result,
                duration_ms=duration_ms,
                meeting_id=meta.get("meeting_id"),
                question=meta.get("question"),
                system_prompt=system_prompt,
            )
        
        return result
    
    def wrapped_call_api_stream(
        self: BaseLLMProvider,
        prompt: str,
        temperature: float = 0.2,
        timeout: int = 120,
        system_prompt: Optional[str] = None,
    ) -> Generator[str, None, None]:
        start_time = time.time()
        
        # Capture tokens for logging
        tokens: list[str] = []
        
        # Record prompt size for RAG metrics
        query_id = _test_active_query_id.get()
        if query_id:
            rag_metrics.test_record_prompt(query_id, input_chars=len(prompt))
        
        for token in original_call_api_stream(self, prompt, temperature, timeout, system_prompt):
            tokens.append(token)
            yield token
        
        duration_ms = int((time.time() - start_time) * 1000)
        result = "".join(tokens)
        
        # Log if enabled or explicitly requested
        should_log = llm_logger.test_get_log_all() or _test_log_this_request.get()
        stem = _test_llm_call_stem.get()
        
        if should_log and stem:
            meta = _test_llm_call_meta.get()
            
            # Get provider and model info
            provider_name = self.__class__.__name__
            model = getattr(self, "_model", getattr(self, "model", "unknown"))
            
            llm_logger.test_log_call(
                stem=stem,
                provider=provider_name,
                model=model,
                temperature=temperature,
                input_prompt=prompt,
                output_response=result,
                duration_ms=duration_ms,
                meeting_id=meta.get("meeting_id"),
                question=meta.get("question"),
                system_prompt=system_prompt,
            )
    
    BaseLLMProvider._call_api = wrapped_call_api  # type: ignore
    BaseLLMProvider._call_api_stream = wrapped_call_api_stream  # type: ignore


# Export context variable for use in chat router
def test_set_log_this_request(value: bool) -> Any:
    """Set the log_this flag for the current request context.
    
    Returns:
        Token to pass to test_reset_log_this_request
    """
    return _test_log_this_request.set(value)


def test_reset_log_this_request(token: Any) -> None:
    """Reset the log_this flag using the token from test_set_log_this_request."""
    _test_log_this_request.reset(token)
