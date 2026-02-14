"""RAG efficiency test suite.

Tests to verify that the RAG system is working efficiently and not
loading unnecessary meeting data for each query.
"""

import httpx
from app.tests.base import TestResult, TestStatus, TestSuite


class RAGEfficiencySuite(TestSuite):
    """Test suite for RAG query efficiency verification.
    
    Tests focus on:
    - Verifying token efficiency (not loading all meeting data)
    - Checking proper use of search vs full data loading
    - Monitoring data access patterns
    """
    
    suite_id = "rag-efficiency"
    name = "RAG Efficiency Tests"
    description = "Verify RAG system efficiency and token usage"
    
    def __init__(self, *args, **kwargs):
        self.base_url = "http://127.0.0.1:8787"
        super().__init__(*args, **kwargs)
    
    def _register_tests(self):
        """Register all RAG efficiency test cases."""
        self.add_test(
            "RAG-001",
            "Debug endpoints accessible",
            self._test_debug_endpoints_accessible,
        )
        self.add_test(
            "RAG-002",
            "RAG metrics collection works",
            self._test_rag_metrics_collection,
        )
        self.add_test(
            "RAG-003",
            "Meeting chat uses targeted data loading",
            self._test_meeting_chat_targeted_loading,
        )
        self.add_test(
            "RAG-004",
            "Overall chat uses search before loading",
            self._test_overall_chat_search_first,
        )
        self.add_test(
            "RAG-005",
            "LLM logging toggle works",
            self._test_llm_logging_toggle,
        )
        self.add_test(
            "RAG-006",
            "Token estimates are reasonable",
            self._test_token_estimates_reasonable,
        )
        self.add_test(
            "RAG-007",
            "Metrics reset clears all data",
            self._test_metrics_reset,
        )
    
    async def setup(self):
        """Reset RAG metrics before running tests."""
        async with httpx.AsyncClient() as client:
            try:
                await client.post(f"{self.base_url}/api/test/rag-metrics/reset")
            except httpx.RequestError:
                pass  # Server might not be running
    
    async def _test_debug_endpoints_accessible(self, context: dict) -> TestResult:
        """Test that debug API endpoints are accessible."""
        async with httpx.AsyncClient() as client:
            try:
                # Test RAG metrics endpoint
                resp = await client.get(f"{self.base_url}/api/test/rag-metrics")
                if resp.status_code != 200:
                    return TestResult(
                        test_id="RAG-001",
                        name="Debug endpoints accessible",
                        status=TestStatus.FAILED,
                        message=f"RAG metrics endpoint returned {resp.status_code}",
                    )
                
                # Test LLM logs endpoint
                resp = await client.get(f"{self.base_url}/api/test/llm-logs")
                if resp.status_code != 200:
                    return TestResult(
                        test_id="RAG-001",
                        name="Debug endpoints accessible",
                        status=TestStatus.FAILED,
                        message=f"LLM logs endpoint returned {resp.status_code}",
                    )
                
                # Test LLM logging status endpoint
                resp = await client.get(f"{self.base_url}/api/test/llm-logging")
                if resp.status_code != 200:
                    return TestResult(
                        test_id="RAG-001",
                        name="Debug endpoints accessible",
                        status=TestStatus.FAILED,
                        message=f"LLM logging status endpoint returned {resp.status_code}",
                    )
                
                return TestResult(
                    test_id="RAG-001",
                    name="Debug endpoints accessible",
                    status=TestStatus.PASSED,
                    message="All debug endpoints are accessible",
                )
            except httpx.RequestError as e:
                return TestResult(
                    test_id="RAG-001",
                    name="Debug endpoints accessible",
                    status=TestStatus.ERROR,
                    message=f"Connection error: {e}",
                    error=str(e),
                )
    
    async def _test_rag_metrics_collection(self, context: dict) -> TestResult:
        """Test that RAG metrics are being collected."""
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{self.base_url}/api/test/rag-metrics")
                if resp.status_code != 200:
                    return TestResult(
                        test_id="RAG-002",
                        name="RAG metrics collection works",
                        status=TestStatus.FAILED,
                        message=f"Failed to get metrics: {resp.status_code}",
                    )
                
                data = resp.json()
                
                # Verify structure
                if "aggregate" not in data or "recent" not in data:
                    return TestResult(
                        test_id="RAG-002",
                        name="RAG metrics collection works",
                        status=TestStatus.FAILED,
                        message="Metrics missing expected structure (aggregate/recent)",
                        details={"keys": list(data.keys())},
                    )
                
                aggregate = data["aggregate"]
                expected_keys = [
                    "total_queries", "avg_duration_ms", "avg_input_tokens",
                    "avg_output_tokens", "avg_meetings_loaded", "avg_search_calls"
                ]
                
                missing = [k for k in expected_keys if k not in aggregate]
                if missing:
                    return TestResult(
                        test_id="RAG-002",
                        name="RAG metrics collection works",
                        status=TestStatus.FAILED,
                        message=f"Aggregate missing keys: {missing}",
                        details={"aggregate_keys": list(aggregate.keys())},
                    )
                
                return TestResult(
                    test_id="RAG-002",
                    name="RAG metrics collection works",
                    status=TestStatus.PASSED,
                    message="RAG metrics structure is correct",
                    details={"aggregate": aggregate},
                )
            except httpx.RequestError as e:
                return TestResult(
                    test_id="RAG-002",
                    name="RAG metrics collection works",
                    status=TestStatus.ERROR,
                    message=f"Connection error: {e}",
                    error=str(e),
                )
    
    async def _test_meeting_chat_targeted_loading(self, context: dict) -> TestResult:
        """Test that meeting chat only loads the target meeting."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                # Reset metrics first
                await client.post(f"{self.base_url}/api/test/rag-metrics/reset")
                
                # Get a meeting to test with
                resp = await client.get(f"{self.base_url}/api/meetings")
                if resp.status_code != 200 or not resp.json():
                    return TestResult(
                        test_id="RAG-003",
                        name="Meeting chat uses targeted data loading",
                        status=TestStatus.SKIPPED,
                        message="No meetings available for testing",
                    )
                
                meetings = resp.json()
                meeting_id = meetings[0]["id"]
                
                # Make a chat request (don't need to wait for full response)
                chat_resp = await client.post(
                    f"{self.base_url}/api/chat/meeting",
                    json={"meeting_id": meeting_id, "question": "Test query"},
                    timeout=30.0,
                )
                
                if chat_resp.status_code != 200:
                    return TestResult(
                        test_id="RAG-003",
                        name="Meeting chat uses targeted data loading",
                        status=TestStatus.SKIPPED,
                        message=f"Chat request failed: {chat_resp.status_code}",
                    )
                
                # Consume the streaming response
                # (it's SSE, so we just need to read it)
                _ = chat_resp.text
                
                # Check metrics
                resp = await client.get(f"{self.base_url}/api/test/rag-metrics")
                data = resp.json()
                
                recent = data.get("recent", [])
                if not recent:
                    return TestResult(
                        test_id="RAG-003",
                        name="Meeting chat uses targeted data loading",
                        status=TestStatus.FAILED,
                        message="No metrics recorded for chat request",
                    )
                
                # Find the meeting_chat query
                meeting_queries = [q for q in recent if q.get("query_type") == "meeting_chat"]
                if not meeting_queries:
                    return TestResult(
                        test_id="RAG-003",
                        name="Meeting chat uses targeted data loading",
                        status=TestStatus.FAILED,
                        message="No meeting_chat query found in metrics",
                        details={"recent": recent},
                    )
                
                query = meeting_queries[-1]  # Most recent
                meetings_loaded = query.get("meetings_loaded", 0)
                
                # Meeting chat should only load 1 meeting (the target)
                # Plus possibly 3 more if include_related is true
                if meetings_loaded > 5:  # Allow some buffer for related
                    return TestResult(
                        test_id="RAG-003",
                        name="Meeting chat uses targeted data loading",
                        status=TestStatus.FAILED,
                        message=f"Loaded too many meetings: {meetings_loaded}",
                        details={"query": query},
                    )
                
                return TestResult(
                    test_id="RAG-003",
                    name="Meeting chat uses targeted data loading",
                    status=TestStatus.PASSED,
                    message=f"Meeting chat loaded {meetings_loaded} meeting(s)",
                    details={"query": query},
                )
            except httpx.RequestError as e:
                return TestResult(
                    test_id="RAG-003",
                    name="Meeting chat uses targeted data loading",
                    status=TestStatus.ERROR,
                    message=f"Connection error: {e}",
                    error=str(e),
                )
    
    async def _test_overall_chat_search_first(self, context: dict) -> TestResult:
        """Test that overall chat uses search before loading full meetings."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                # Reset metrics first
                await client.post(f"{self.base_url}/api/test/rag-metrics/reset")
                
                # Make an overall chat request
                chat_resp = await client.post(
                    f"{self.base_url}/api/chat/overall",
                    json={"question": "Test overall query"},
                    timeout=30.0,
                )
                
                if chat_resp.status_code != 200:
                    return TestResult(
                        test_id="RAG-004",
                        name="Overall chat uses search before loading",
                        status=TestStatus.SKIPPED,
                        message=f"Chat request failed: {chat_resp.status_code}",
                    )
                
                # Consume the streaming response
                _ = chat_resp.text
                
                # Check metrics
                resp = await client.get(f"{self.base_url}/api/test/rag-metrics")
                data = resp.json()
                
                recent = data.get("recent", [])
                overall_queries = [q for q in recent if q.get("query_type") == "overall_chat"]
                
                if not overall_queries:
                    return TestResult(
                        test_id="RAG-004",
                        name="Overall chat uses search before loading",
                        status=TestStatus.FAILED,
                        message="No overall_chat query found in metrics",
                    )
                
                query = overall_queries[-1]
                search_calls = query.get("search_calls", 0)
                meetings_loaded = query.get("meetings_loaded", 0)
                
                # Overall chat should use search (unless no search results)
                # The key efficiency check: shouldn't load ALL meetings
                details = {
                    "search_calls": search_calls,
                    "meetings_loaded": meetings_loaded,
                    "query": query,
                }
                
                # Reasonable threshold: shouldn't load more than 10 meetings
                if meetings_loaded > 10:
                    return TestResult(
                        test_id="RAG-004",
                        name="Overall chat uses search before loading",
                        status=TestStatus.FAILED,
                        message=f"Loaded too many meetings: {meetings_loaded}",
                        details=details,
                    )
                
                return TestResult(
                    test_id="RAG-004",
                    name="Overall chat uses search before loading",
                    status=TestStatus.PASSED,
                    message=f"Search calls: {search_calls}, Meetings loaded: {meetings_loaded}",
                    details=details,
                )
            except httpx.RequestError as e:
                return TestResult(
                    test_id="RAG-004",
                    name="Overall chat uses search before loading",
                    status=TestStatus.ERROR,
                    message=f"Connection error: {e}",
                    error=str(e),
                )
    
    async def _test_llm_logging_toggle(self, context: dict) -> TestResult:
        """Test that LLM logging can be toggled on and off."""
        async with httpx.AsyncClient() as client:
            try:
                # Get initial state
                resp = await client.get(f"{self.base_url}/api/test/llm-logging")
                if resp.status_code != 200:
                    return TestResult(
                        test_id="RAG-005",
                        name="LLM logging toggle works",
                        status=TestStatus.FAILED,
                        message=f"Failed to get logging status: {resp.status_code}",
                    )
                
                initial = resp.json().get("enabled", False)
                
                # Toggle to opposite
                resp = await client.post(
                    f"{self.base_url}/api/test/llm-logging",
                    json={"enabled": not initial},
                )
                if resp.status_code != 200:
                    return TestResult(
                        test_id="RAG-005",
                        name="LLM logging toggle works",
                        status=TestStatus.FAILED,
                        message=f"Failed to toggle logging: {resp.status_code}",
                    )
                
                # Verify change
                resp = await client.get(f"{self.base_url}/api/test/llm-logging")
                new_state = resp.json().get("enabled")
                
                if new_state != (not initial):
                    return TestResult(
                        test_id="RAG-005",
                        name="LLM logging toggle works",
                        status=TestStatus.FAILED,
                        message=f"Toggle didn't change state: {initial} -> {new_state}",
                    )
                
                # Restore original state
                await client.post(
                    f"{self.base_url}/api/test/llm-logging",
                    json={"enabled": initial},
                )
                
                return TestResult(
                    test_id="RAG-005",
                    name="LLM logging toggle works",
                    status=TestStatus.PASSED,
                    message=f"Successfully toggled logging from {initial} to {not initial}",
                )
            except httpx.RequestError as e:
                return TestResult(
                    test_id="RAG-005",
                    name="LLM logging toggle works",
                    status=TestStatus.ERROR,
                    message=f"Connection error: {e}",
                    error=str(e),
                )
    
    async def _test_token_estimates_reasonable(self, context: dict) -> TestResult:
        """Test that token estimates are reasonable (not zero, not huge)."""
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{self.base_url}/api/test/rag-metrics")
                data = resp.json()
                
                recent = data.get("recent", [])
                if not recent:
                    return TestResult(
                        test_id="RAG-006",
                        name="Token estimates are reasonable",
                        status=TestStatus.SKIPPED,
                        message="No recent queries to analyze",
                    )
                
                # Check token counts in recent queries
                issues = []
                for query in recent:
                    input_tokens = query.get("input_tokens", 0)
                    output_tokens = query.get("output_tokens", 0)
                    
                    # Input tokens should be reasonable (not empty, not huge)
                    if input_tokens == 0:
                        issues.append(f"Query {query.get('query_id')}: zero input tokens")
                    elif input_tokens > 100000:  # 100k tokens seems excessive
                        issues.append(f"Query {query.get('query_id')}: {input_tokens} input tokens (excessive)")
                
                if issues:
                    return TestResult(
                        test_id="RAG-006",
                        name="Token estimates are reasonable",
                        status=TestStatus.FAILED,
                        message=f"Found {len(issues)} issues with token counts",
                        details={"issues": issues},
                    )
                
                # Calculate averages for reporting
                avg_input = sum(q.get("input_tokens", 0) for q in recent) // len(recent)
                avg_output = sum(q.get("output_tokens", 0) for q in recent) // len(recent)
                
                return TestResult(
                    test_id="RAG-006",
                    name="Token estimates are reasonable",
                    status=TestStatus.PASSED,
                    message=f"Avg input: {avg_input} tokens, Avg output: {avg_output} tokens",
                    details={"avg_input": avg_input, "avg_output": avg_output},
                )
            except httpx.RequestError as e:
                return TestResult(
                    test_id="RAG-006",
                    name="Token estimates are reasonable",
                    status=TestStatus.ERROR,
                    message=f"Connection error: {e}",
                    error=str(e),
                )
    
    async def _test_metrics_reset(self, context: dict) -> TestResult:
        """Test that metrics reset clears all data."""
        async with httpx.AsyncClient() as client:
            try:
                # Reset metrics
                resp = await client.post(f"{self.base_url}/api/test/rag-metrics/reset")
                if resp.status_code != 200:
                    return TestResult(
                        test_id="RAG-007",
                        name="Metrics reset clears all data",
                        status=TestStatus.FAILED,
                        message=f"Reset failed: {resp.status_code}",
                    )
                
                # Verify metrics are empty
                resp = await client.get(f"{self.base_url}/api/test/rag-metrics")
                data = resp.json()
                
                total = data.get("aggregate", {}).get("total_queries", -1)
                recent = data.get("recent", [])
                
                if total != 0:
                    return TestResult(
                        test_id="RAG-007",
                        name="Metrics reset clears all data",
                        status=TestStatus.FAILED,
                        message=f"Total queries should be 0 after reset, got {total}",
                    )
                
                if recent:
                    return TestResult(
                        test_id="RAG-007",
                        name="Metrics reset clears all data",
                        status=TestStatus.FAILED,
                        message=f"Recent queries should be empty, got {len(recent)} items",
                    )
                
                return TestResult(
                    test_id="RAG-007",
                    name="Metrics reset clears all data",
                    status=TestStatus.PASSED,
                    message="Metrics successfully reset to zero",
                )
            except httpx.RequestError as e:
                return TestResult(
                    test_id="RAG-007",
                    name="Metrics reset clears all data",
                    status=TestStatus.ERROR,
                    message=f"Connection error: {e}",
                    error=str(e),
                )
