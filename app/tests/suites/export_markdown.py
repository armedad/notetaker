"""Export markdown E2E suite — Phase 9."""
from __future__ import annotations

import aiohttp

from app.tests.base import TestResult, TestStatus, TestSuite


class ExportMarkdownSuite(TestSuite):
    suite_id = "export-markdown"
    name = "Markdown Export"
    description = "Meeting export via API"

    def _register_tests(self):
        self.add_test("EX-001", "Create meeting and export", self._test_export)

    async def setup(self):
        self.context["api_base"] = "http://127.0.0.1:6684"
        self.context["meeting_id"] = None

    async def teardown(self):
        mid = self.context.get("meeting_id")
        if not mid:
            return
        async with aiohttp.ClientSession() as session:
            await session.delete(f"{self.context['api_base']}/api/meetings/{mid}")

    async def _test_export(self, ctx: dict) -> TestResult:
        base = ctx["api_base"]
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base}/api/recording/start",
                json={"device_index": 0, "samplerate": 48000, "channels": 1},
            ) as start:
                if start.status != 200:
                    return TestResult("EX-001", "Create meeting and export", TestStatus.FAILED, message="start failed")
                data = await start.json()
                mid = data.get("recording_id")
            await session.post(f"{base}/api/recording/stop")
            if not mid:
                return TestResult("EX-001", "Create meeting and export", TestStatus.FAILED, message="no meeting id")
            ctx["meeting_id"] = mid
            async with session.get(f"{base}/api/meetings/{mid}/export") as exp:
                if exp.status != 200:
                    return TestResult("EX-001", "Create meeting and export", TestStatus.FAILED, message=f"export HTTP {exp.status}")
                body = await exp.text()
                if len(body) < 10:
                    return TestResult("EX-001", "Create meeting and export", TestStatus.FAILED, message="empty export")
                return TestResult("EX-001", "Create meeting and export", TestStatus.PASSED, message=f"{len(body)} chars")
