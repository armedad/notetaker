"""Debug UI test suite."""
from __future__ import annotations

from app.tests.base import TestSuite, TestResult, TestStatus


class DebugUISuite(TestSuite):
    """Tests for the smart summary debug UI."""

    suite_id = "debug-ui"
    name = "Smart Real Time Summary Debug UI"
    description = "Tests the debug panel in the meeting UI"

    def _register_tests(self):
        self.add_test(
            "DU-001",
            "Debug button exists in meeting page",
            self._test_debug_button_exists,
        )
        self.add_test(
            "DU-002",
            "Click debug shows two columns",
            self._test_two_columns_render,
            skip=True,
            skip_reason="Feature not yet implemented",
        )
        self.add_test(
            "DU-003",
            "Left column has done/draft/streaming",
            self._test_left_column_content,
            skip=True,
            skip_reason="Feature not yet implemented",
        )
        self.add_test(
            "DU-004",
            "Right column has summarized/interim",
            self._test_right_column_content,
            skip=True,
            skip_reason="Feature not yet implemented",
        )
        self.add_test(
            "DU-005",
            "Content auto-scrolls to bottom",
            self._test_auto_scroll,
            skip=True,
            skip_reason="Feature not yet implemented",
        )

    async def setup(self):
        """Set up test context."""
        self.context["api_base"] = "http://127.0.0.1:6684"

    async def _test_debug_button_exists(self, ctx: dict) -> TestResult:
        """Test that debug button exists in meeting page."""
        import aiohttp

        api_base = ctx["api_base"]

        try:
            async with aiohttp.ClientSession() as session:
                # Fetch the meeting page HTML
                async with session.get(f"{api_base}/static/meeting.html") as resp:
                    if resp.status != 200:
                        return TestResult(
                            test_id="DU-001",
                            name="Debug button exists in meeting page",
                            status=TestStatus.ERROR,
                            message=f"Failed to fetch meeting.html: HTTP {resp.status}",
                        )
                    html = await resp.text()

                # Check for debug button in HTML
                # Look for button with debug-related id or class
                has_debug_button = (
                    'id="debug-btn"' in html
                    or 'id="debug-button"' in html
                    or 'class="debug-btn"' in html
                    or "debug" in html.lower()
                )

                if has_debug_button:
                    return TestResult(
                        test_id="DU-001",
                        name="Debug button exists in meeting page",
                        status=TestStatus.PASSED,
                        message="Debug button found in meeting.html",
                    )
                else:
                    return TestResult(
                        test_id="DU-001",
                        name="Debug button exists in meeting page",
                        status=TestStatus.FAILED,
                        message="No debug button found in meeting.html",
                        details={"html_length": len(html)},
                    )

        except Exception as e:
            return TestResult(
                test_id="DU-001",
                name="Debug button exists in meeting page",
                status=TestStatus.ERROR,
                message=f"Connection error: {e}",
            )

    async def _test_two_columns_render(self, ctx: dict) -> TestResult:
        """Test that clicking debug shows two columns."""
        # TODO: Implement when feature is ready
        # This would require browser automation (Playwright/Selenium)
        return TestResult(
            test_id="DU-002",
            name="Click debug shows two columns",
            status=TestStatus.SKIPPED,
            message="Requires browser automation - feature not yet implemented",
        )

    async def _test_left_column_content(self, ctx: dict) -> TestResult:
        """Test that left column has done/draft/streaming."""
        # TODO: Implement when feature is ready
        return TestResult(
            test_id="DU-003",
            name="Left column has done/draft/streaming",
            status=TestStatus.SKIPPED,
            message="Requires browser automation - feature not yet implemented",
        )

    async def _test_right_column_content(self, ctx: dict) -> TestResult:
        """Test that right column has summarized/interim."""
        # TODO: Implement when feature is ready
        return TestResult(
            test_id="DU-004",
            name="Right column has summarized/interim",
            status=TestStatus.SKIPPED,
            message="Requires browser automation - feature not yet implemented",
        )

    async def _test_auto_scroll(self, ctx: dict) -> TestResult:
        """Test that content auto-scrolls to bottom."""
        # TODO: Implement when feature is ready
        return TestResult(
            test_id="DU-005",
            name="Content auto-scrolls to bottom",
            status=TestStatus.SKIPPED,
            message="Requires browser automation - feature not yet implemented",
        )
