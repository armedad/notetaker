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
        self.add_test("DZ-003", "Diarization fixture audio available", self._test_fixture_audio)
        self.add_test("DZ-004", "Realtime and batch settings endpoints", self._test_realtime_batch)

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

    async def _test_fixture_audio(self, ctx: dict) -> TestResult:
        from app.tests.fixture_paths import two_speaker_wav_path

        wav = two_speaker_wav_path()
        if wav:
            return TestResult("DZ-003", "Diarization fixture audio available", TestStatus.PASSED, message=wav)
        return TestResult("DZ-003", "Diarization fixture audio available", TestStatus.FAILED, message="missing fixture")

    async def _test_realtime_batch(self, ctx: dict) -> TestResult:
        import aiohttp

        api_base = ctx["api_base"]
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{api_base}/api/settings/diarization/realtime") as r1:
                async with session.get(f"{api_base}/api/settings/diarization/batch") as r2:
                    if r1.status == 200 and r2.status == 200:
                        return TestResult("DZ-004", "Realtime and batch settings endpoints", TestStatus.PASSED)
                    return TestResult("DZ-004", "Realtime and batch settings endpoints", TestStatus.FAILED)
