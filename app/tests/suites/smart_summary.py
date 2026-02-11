"""Smart Real Time Summary test suite."""
from __future__ import annotations

from app.tests.base import TestSuite, TestResult, TestStatus


class SmartSummarySuite(TestSuite):
    """Deprecated: auto smart summary removed in manual summarization mode."""

    suite_id = "smart-summary"
    name = "Smart Real Time Summary Parsing (deprecated)"
    description = "Deprecated: manual summarization replaced the auto smart-summary pipeline"

    def _register_tests(self):
        self.add_test(
            "SS-000",
            "Suite deprecated",
            self._test_deprecated,
            skip=True,
            skip_reason="Auto smart-summary was removed; manual summarization is now used.",
        )

    async def setup(self):
        """Set up test context."""
        self.context["api_base"] = "http://127.0.0.1:6684"

    async def _test_deprecated(self, ctx: dict) -> TestResult:
        return TestResult(
            test_id="SS-000",
            name="Suite deprecated",
            status=TestStatus.SKIPPED,
            message="Auto smart-summary removed; manual summarization is now used.",
        )
