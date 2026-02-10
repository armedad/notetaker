"""Base classes for test harness."""
from __future__ import annotations

import asyncio
import logging
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, Any


class TestStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class TestResult:
    test_id: str
    name: str
    status: TestStatus
    duration_ms: float = 0.0
    message: str = ""
    details: dict = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "name": self.name,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "message": self.message,
            "details": self.details,
            "error": self.error,
        }


@dataclass
class SuiteResult:
    suite_id: str
    name: str
    started_at: str
    ended_at: str
    duration_ms: float
    passed: int
    failed: int
    skipped: int
    error: int
    results: list[TestResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "suite_id": self.suite_id,
            "name": self.name,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "error": self.error,
            "results": [r.to_dict() for r in self.results],
        }


class TestCase:
    """A single test case."""

    def __init__(
        self,
        test_id: str,
        name: str,
        fn: Callable,
        skip: bool = False,
        skip_reason: str = "",
    ):
        self.test_id = test_id
        self.name = name
        self.fn = fn
        self.skip = skip
        self.skip_reason = skip_reason

    async def run(self, context: dict) -> TestResult:
        if self.skip:
            return TestResult(
                test_id=self.test_id,
                name=self.name,
                status=TestStatus.SKIPPED,
                message=self.skip_reason or "Skipped",
            )

        start = time.perf_counter()
        try:
            if asyncio.iscoroutinefunction(self.fn):
                result = await self.fn(context)
            else:
                result = self.fn(context)

            duration_ms = (time.perf_counter() - start) * 1000

            if isinstance(result, TestResult):
                result.duration_ms = duration_ms
                return result

            # If function returns True/False
            if result is True:
                return TestResult(
                    test_id=self.test_id,
                    name=self.name,
                    status=TestStatus.PASSED,
                    duration_ms=duration_ms,
                    message="Test passed",
                )
            elif result is False:
                return TestResult(
                    test_id=self.test_id,
                    name=self.name,
                    status=TestStatus.FAILED,
                    duration_ms=duration_ms,
                    message="Test failed",
                )
            else:
                # If function returns dict with status
                if isinstance(result, dict):
                    status = TestStatus.PASSED if result.get("passed", False) else TestStatus.FAILED
                    return TestResult(
                        test_id=self.test_id,
                        name=self.name,
                        status=status,
                        duration_ms=duration_ms,
                        message=result.get("message", ""),
                        details=result.get("details", {}),
                    )
                # Assume passed if no exception
                return TestResult(
                    test_id=self.test_id,
                    name=self.name,
                    status=TestStatus.PASSED,
                    duration_ms=duration_ms,
                    message="Test completed",
                )

        except AssertionError as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return TestResult(
                test_id=self.test_id,
                name=self.name,
                status=TestStatus.FAILED,
                duration_ms=duration_ms,
                message=str(e) or "Assertion failed",
                error=traceback.format_exc(),
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            return TestResult(
                test_id=self.test_id,
                name=self.name,
                status=TestStatus.ERROR,
                duration_ms=duration_ms,
                message=f"Error: {e}",
                error=traceback.format_exc(),
            )


class TestSuite:
    """A collection of test cases."""

    suite_id: str = "base"
    name: str = "Base Test Suite"
    description: str = ""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.tests: list[TestCase] = []
        self.logger = logger or logging.getLogger(f"notetaker.test.{self.suite_id}")
        self.context: dict = {}
        self._register_tests()

    def _register_tests(self):
        """Override to register test cases."""
        pass

    def add_test(
        self,
        test_id: str,
        name: str,
        fn: Callable,
        skip: bool = False,
        skip_reason: str = "",
    ):
        self.tests.append(TestCase(test_id, name, fn, skip, skip_reason))

    async def setup(self) -> None:
        """Override for suite setup."""
        pass

    async def teardown(self) -> None:
        """Override for suite teardown."""
        pass

    async def run(self) -> SuiteResult:
        from datetime import datetime

        started_at = datetime.now().isoformat()
        start_time = time.perf_counter()

        self.logger.info("=" * 60)
        self.logger.info(f"SUITE: {self.name} ({self.suite_id})")
        self.logger.info("=" * 60)

        results: list[TestResult] = []
        passed = failed = skipped = error = 0

        try:
            await self.setup()
        except Exception as e:
            self.logger.error(f"Suite setup failed: {e}")
            return SuiteResult(
                suite_id=self.suite_id,
                name=self.name,
                started_at=started_at,
                ended_at=datetime.now().isoformat(),
                duration_ms=(time.perf_counter() - start_time) * 1000,
                passed=0,
                failed=0,
                skipped=0,
                error=1,
                results=[
                    TestResult(
                        test_id="SETUP",
                        name="Suite Setup",
                        status=TestStatus.ERROR,
                        message=f"Setup failed: {e}",
                        error=traceback.format_exc(),
                    )
                ],
            )

        for test in self.tests:
            self.logger.info(f"\n[TEST] {test.test_id}: {test.name}")
            result = await test.run(self.context)
            results.append(result)

            status_symbol = {
                TestStatus.PASSED: "✓",
                TestStatus.FAILED: "✗",
                TestStatus.SKIPPED: "○",
                TestStatus.ERROR: "!",
            }.get(result.status, "?")

            self.logger.info(
                f"  [{status_symbol}] {result.status.value.upper()} "
                f"({result.duration_ms:.1f}ms) - {result.message}"
            )
            if result.error:
                self.logger.error(f"  Error details:\n{result.error}")

            if result.status == TestStatus.PASSED:
                passed += 1
            elif result.status == TestStatus.FAILED:
                failed += 1
            elif result.status == TestStatus.SKIPPED:
                skipped += 1
            else:
                error += 1

        try:
            await self.teardown()
        except Exception as e:
            self.logger.error(f"Suite teardown failed: {e}")

        ended_at = datetime.now().isoformat()
        duration_ms = (time.perf_counter() - start_time) * 1000

        self.logger.info("\n" + "-" * 60)
        self.logger.info(
            f"SUMMARY: {passed} passed, {failed} failed, "
            f"{skipped} skipped, {error} errors ({duration_ms:.1f}ms)"
        )
        self.logger.info("-" * 60)

        return SuiteResult(
            suite_id=self.suite_id,
            name=self.name,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            passed=passed,
            failed=failed,
            skipped=skipped,
            error=error,
            results=results,
        )

    def get_info(self) -> dict:
        return {
            "suite_id": self.suite_id,
            "name": self.name,
            "description": self.description,
            "test_count": len(self.tests),
            "tests": [
                {"test_id": t.test_id, "name": t.name, "skip": t.skip}
                for t in self.tests
            ],
        }
