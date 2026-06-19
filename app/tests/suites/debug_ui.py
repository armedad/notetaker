"""Debug UI / manual summarization HTML checks."""
from __future__ import annotations

import aiohttp

from app.tests.base import TestResult, TestStatus, TestSuite


class DebugUISuite(TestSuite):
    suite_id = "debug-ui"
    name = "Manual Summarization UI"
    description = "HTML presence checks for meeting page controls"

    def _register_tests(self):
        self.add_test("DU-001", "Manual summarize button in meeting page", self._test_manual_button)
        self.add_test("DU-002", "Meeting grid layout present", self._test_grid)
        self.add_test("DU-003", "Transcript output region present", self._test_transcript)
        self.add_test("DU-004", "Manual summary textarea present", self._test_manual_summary)
        self.add_test("DU-005", "Export and delete controls present", self._test_actions)

    async def setup(self):
        self.context["api_base"] = "http://127.0.0.1:6684"

    async def _fetch_meeting_html(self, ctx: dict) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ctx['api_base']}/static/meeting.html") as resp:
                return await resp.text()

    async def _test_manual_button(self, ctx: dict) -> TestResult:
        html = await self._fetch_meeting_html(ctx)
        ok = 'id="manual-summarize"' in html
        return TestResult("DU-001", "Manual summarize button", TestStatus.PASSED if ok else TestStatus.FAILED)

    async def _test_grid(self, ctx: dict) -> TestResult:
        html = await self._fetch_meeting_html(ctx)
        ok = 'id="meeting-grid"' in html
        return TestResult("DU-002", "Meeting grid layout", TestStatus.PASSED if ok else TestStatus.FAILED)

    async def _test_transcript(self, ctx: dict) -> TestResult:
        html = await self._fetch_meeting_html(ctx)
        ok = 'id="transcript-output"' in html
        return TestResult("DU-003", "Transcript output region", TestStatus.PASSED if ok else TestStatus.FAILED)

    async def _test_manual_summary(self, ctx: dict) -> TestResult:
        html = await self._fetch_meeting_html(ctx)
        ok = 'id="manual-summary"' in html
        return TestResult("DU-004", "Manual summary textarea", TestStatus.PASSED if ok else TestStatus.FAILED)

    async def _test_actions(self, ctx: dict) -> TestResult:
        html = await self._fetch_meeting_html(ctx)
        ok = 'id="export-meeting"' in html and 'id="delete-meeting"' in html
        return TestResult("DU-005", "Export and delete controls", TestStatus.PASSED if ok else TestStatus.FAILED)
