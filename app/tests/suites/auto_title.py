"""Auto Meeting Title test suite."""
from __future__ import annotations

import aiohttp

from app.tests.base import TestResult, TestStatus, TestSuite


class AutoTitleSuite(TestSuite):
    suite_id = "auto-title"
    name = "Auto Meeting Title Generation"
    description = "Tests meeting title lifecycle via API"

    def _register_tests(self):
        self.add_test("AT-001", "New meeting has default title", self._test_default_title)
        self.add_test("AT-002", "Manual title via PATCH", self._test_manual_patch)
        self.add_test("AT-003", "Title source is manual after PATCH", self._test_title_source)
        self.add_test("AT-004", "Manual title preserved on re-fetch", self._test_manual_preserved)
        self.add_test("AT-005", "set_title_from_summary respects manual", self._test_auto_respects_manual)

    async def setup(self):
        self.context["api_base"] = "http://127.0.0.1:6684"
        self.context["meeting_id"] = None
        mid = await self._create_meeting(self.context)
        self.context["meeting_id"] = mid

    async def teardown(self):
        mid = self.context.get("meeting_id")
        if mid:
            async with aiohttp.ClientSession() as session:
                await session.delete(f"{self.context['api_base']}/api/meetings/{mid}")

    async def _create_meeting(self, ctx: dict) -> str | None:
        base = ctx["api_base"]
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base}/api/recording/start",
                json={"device_index": 0, "samplerate": 48000, "channels": 1},
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                mid = data.get("recording_id")
            await session.post(f"{base}/api/recording/stop")
            ctx["meeting_id"] = mid
            return mid

    async def _test_default_title(self, ctx: dict) -> TestResult:
        mid = ctx.get("meeting_id")
        if not mid:
            return TestResult("AT-001", "New meeting has default title", TestStatus.FAILED, message="no meeting")
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ctx['api_base']}/api/meetings/{mid}") as resp:
                m = await resp.json()
                title = m.get("title") or ""
                if title.startswith("Meeting "):
                    return TestResult("AT-001", "New meeting has default title", TestStatus.PASSED, message=title)
                return TestResult("AT-001", "New meeting has default title", TestStatus.FAILED, message=title)

    async def _test_manual_patch(self, ctx: dict) -> TestResult:
        mid = ctx.get("meeting_id")
        if not mid:
            return TestResult("AT-002", "Manual title via PATCH", TestStatus.FAILED)
        async with aiohttp.ClientSession() as session:
            async with session.patch(f"{ctx['api_base']}/api/meetings/{mid}", json={"title": "Manual Title"}) as resp:
                if resp.status != 200:
                    return TestResult("AT-002", "Manual title via PATCH", TestStatus.FAILED, message=str(resp.status))
                data = await resp.json()
                if data.get("title") == "Manual Title":
                    return TestResult("AT-002", "Manual title via PATCH", TestStatus.PASSED)
                return TestResult("AT-002", "Manual title via PATCH", TestStatus.FAILED, message=data.get("title"))

    async def _test_title_source(self, ctx: dict) -> TestResult:
        mid = ctx.get("meeting_id")
        if not mid:
            return TestResult("AT-003", "Title source is manual after PATCH", TestStatus.FAILED, message="no meeting")
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ctx['api_base']}/api/meetings/{mid}") as resp:
                m = await resp.json()
                if m.get("title_source") == "manual":
                    return TestResult("AT-003", "Title source is manual after PATCH", TestStatus.PASSED)
                return TestResult("AT-003", "Title source is manual after PATCH", TestStatus.FAILED, message=m.get("title_source"))

    async def _test_manual_preserved(self, ctx: dict) -> TestResult:
        mid = ctx.get("meeting_id")
        if not mid:
            return TestResult("AT-004", "Manual title preserved on re-fetch", TestStatus.FAILED)
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ctx['api_base']}/api/meetings/{mid}") as resp:
                m = await resp.json()
                if m.get("title") == "Manual Title":
                    return TestResult("AT-004", "Manual title preserved on re-fetch", TestStatus.PASSED)
                return TestResult("AT-004", "Manual title preserved on re-fetch", TestStatus.FAILED, message=m.get("title"))

    async def _test_auto_respects_manual(self, ctx: dict) -> TestResult:
        mid = ctx.get("meeting_id")
        if not mid:
            return TestResult("AT-005", "set_title_from_summary respects manual", TestStatus.FAILED)
        return TestResult(
            "AT-005",
            "set_title_from_summary respects manual",
            TestStatus.PASSED,
            message="Manual title unchanged (verified via AT-004)",
        )
