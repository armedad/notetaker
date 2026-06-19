"""Manual summarization UI checks."""
from __future__ import annotations

import aiohttp

from app.tests.base import TestResult, TestStatus, TestSuite


class SmartSummarySuite(TestSuite):
    suite_id = "smart-summary"
    name = "Manual Summarization"
    description = "Manual summarization controls (replaces deprecated auto smart-summary)"

    def _register_tests(self):
        self.add_test("SS-001", "Manual summarize button exists", self._test_button)
        self.add_test("SS-002", "Manual summary status element", self._test_status)
        self.add_test("SS-003", "Summary output area", self._test_output)

    async def setup(self):
        self.context["api_base"] = "http://127.0.0.1:6684"

    async def _html(self, ctx: dict) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ctx['api_base']}/static/meeting.html") as resp:
                return await resp.text()

    async def _test_button(self, ctx: dict) -> TestResult:
        html = await self._html(ctx)
        ok = 'id="manual-summarize"' in html
        return TestResult("SS-001", "Manual summarize button", TestStatus.PASSED if ok else TestStatus.FAILED)

    async def _test_status(self, ctx: dict) -> TestResult:
        html = await self._html(ctx)
        ok = 'id="manual-summary-status"' in html
        return TestResult("SS-002", "Manual summary status", TestStatus.PASSED if ok else TestStatus.FAILED)

    async def _test_output(self, ctx: dict) -> TestResult:
        html = await self._html(ctx)
        ok = 'id="summary-output"' in html or 'id="manual-summary"' in html
        return TestResult("SS-003", "Summary output area", TestStatus.PASSED if ok else TestStatus.FAILED)
