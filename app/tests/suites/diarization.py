"""Diarization test suite."""
from __future__ import annotations

from app.tests.base import TestSuite, TestResult, TestStatus


class DiarizationSuite(TestSuite):
    """Tests for speaker diarization."""

    suite_id = "diarization"
    name = "Speaker Diarization (WhisperX)"
    description = "Tests the speaker identification and diarization pipeline"

    def _register_tests(self):
        self.add_test(
            "DZ-001",
            "Diarization service loads",
            self._test_service_loads,
        )
        self.add_test(
            "DZ-002",
            "Diarization settings API works",
            self._test_settings_api,
        )
        self.add_test(
            "DZ-003",
            "Multiple speakers distinguished",
            self._test_multiple_speakers,
            skip=True,
            skip_reason="Requires multi-speaker audio fixture",
        )
        self.add_test(
            "DZ-004",
            "Speaker labels in transcript",
            self._test_speaker_labels,
            skip=True,
            skip_reason="Requires full transcription with diarization",
        )

    async def setup(self):
        """Set up test context."""
        self.context["api_base"] = "http://127.0.0.1:6684"

    async def _test_service_loads(self, ctx: dict) -> TestResult:
        """Test that diarization service initializes."""
        import aiohttp

        api_base = ctx["api_base"]

        try:
            async with aiohttp.ClientSession() as session:
                # Check health endpoint
                async with session.get(f"{api_base}/api/health") as resp:
                    if resp.status != 200:
                        return TestResult(
                            test_id="DZ-001",
                            name="Diarization service loads",
                            status=TestStatus.ERROR,
                            message=f"Health check failed: HTTP {resp.status}",
                        )
                    data = await resp.json()

                # Check diarization settings endpoint
                async with session.get(f"{api_base}/api/settings/diarization") as resp:
                    if resp.status != 200:
                        return TestResult(
                            test_id="DZ-001",
                            name="Diarization service loads",
                            status=TestStatus.FAILED,
                            message=f"Diarization settings endpoint failed: HTTP {resp.status}",
                        )
                    diarization_settings = await resp.json()

                return TestResult(
                    test_id="DZ-001",
                    name="Diarization service loads",
                    status=TestStatus.PASSED,
                    message="Diarization API endpoints accessible",
                    details={
                        "health": data,
                        "diarization_settings": diarization_settings,
                    },
                )

        except Exception as e:
            return TestResult(
                test_id="DZ-001",
                name="Diarization service loads",
                status=TestStatus.ERROR,
                message=f"Connection error: {e}",
            )

    async def _test_settings_api(self, ctx: dict) -> TestResult:
        """Test that diarization settings API works."""
        import aiohttp

        api_base = ctx["api_base"]

        try:
            async with aiohttp.ClientSession() as session:
                # Get current settings
                async with session.get(f"{api_base}/api/settings/diarization") as resp:
                    if resp.status != 200:
                        return TestResult(
                            test_id="DZ-002",
                            name="Diarization settings API works",
                            status=TestStatus.FAILED,
                            message=f"GET failed: HTTP {resp.status}",
                        )
                    settings = await resp.json()

                # Verify expected fields exist
                expected_fields = ["enabled", "provider"]
                missing = [f for f in expected_fields if f not in settings]

                if missing:
                    return TestResult(
                        test_id="DZ-002",
                        name="Diarization settings API works",
                        status=TestStatus.FAILED,
                        message=f"Missing fields: {missing}",
                        details={"settings": settings},
                    )

                return TestResult(
                    test_id="DZ-002",
                    name="Diarization settings API works",
                    status=TestStatus.PASSED,
                    message=f"Settings API works, provider={settings.get('provider')}",
                    details={"settings": settings},
                )

        except Exception as e:
            return TestResult(
                test_id="DZ-002",
                name="Diarization settings API works",
                status=TestStatus.ERROR,
                message=f"Error: {e}",
            )

    async def _test_multiple_speakers(self, ctx: dict) -> TestResult:
        """Test that multiple speakers are distinguished."""
        # TODO: Implement when multi-speaker audio fixture is available
        return TestResult(
            test_id="DZ-003",
            name="Multiple speakers distinguished",
            status=TestStatus.SKIPPED,
            message="Requires multi-speaker audio fixture",
        )

    async def _test_speaker_labels(self, ctx: dict) -> TestResult:
        """Test that speaker labels appear in transcript."""
        # TODO: Implement when full pipeline is ready
        return TestResult(
            test_id="DZ-004",
            name="Speaker labels in transcript",
            status=TestStatus.SKIPPED,
            message="Requires full transcription with diarization enabled",
        )
