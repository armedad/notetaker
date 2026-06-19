"""Health smoke E2E suite — Phase 0."""
from __future__ import annotations

import aiohttp

from app.tests.base import TestResult, TestStatus, TestSuite


class HealthSmokeSuite(TestSuite):
    suite_id = "health-smoke"
    name = "Health Smoke"
    description = "Basic server health and static asset checks"

    def _register_tests(self):
        self.add_test("HS-001", "Health endpoint", self._test_health)
        self.add_test("HS-002", "Root page", self._test_root)
        self.add_test("HS-003", "Meeting page", self._test_meeting)
        self.add_test("HS-004", "Settings page", self._test_settings)
        self.add_test("HS-005", "Test harness page", self._test_harness)

    async def setup(self):
        self.context["api_base"] = "http://127.0.0.1:6684"

    async def _test_health(self, ctx: dict) -> TestResult:
        base = ctx["api_base"]
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base}/api/health") as resp:
                if resp.status != 200:
                    return TestResult("HS-001", "Health endpoint", TestStatus.FAILED, message=f"HTTP {resp.status}")
                data = await resp.json()
                if data.get("status") != "ok":
                    return TestResult("HS-001", "Health endpoint", TestStatus.FAILED, message=str(data))
                return TestResult("HS-001", "Health endpoint", TestStatus.PASSED, message="ok")

    async def _test_root(self, ctx: dict) -> TestResult:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ctx['api_base']}/") as resp:
                ok = resp.status == 200
                return TestResult("HS-002", "Root page", TestStatus.PASSED if ok else TestStatus.FAILED)

    async def _test_meeting(self, ctx: dict) -> TestResult:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ctx['api_base']}/meeting") as resp:
                ok = resp.status == 200
                return TestResult("HS-003", "Meeting page", TestStatus.PASSED if ok else TestStatus.FAILED)

    async def _test_settings(self, ctx: dict) -> TestResult:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ctx['api_base']}/settings") as resp:
                ok = resp.status == 200
                return TestResult("HS-004", "Settings page", TestStatus.PASSED if ok else TestStatus.FAILED)

    async def _test_harness(self, ctx: dict) -> TestResult:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ctx['api_base']}/test") as resp:
                ok = resp.status == 200
                return TestResult("HS-005", "Test harness page", TestStatus.PASSED if ok else TestStatus.FAILED)
