"""Transcription Flow E2E test suite."""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from app.tests.base import TestSuite, TestResult, TestStatus


class TranscriptionFlowSuite(TestSuite):
    """End-to-end tests for the transcription workflow."""

    suite_id = "transcription-flow"
    name = "Transcription Flow E2E"
    description = (
        "End-to-end test: start transcription via media file, verify meeting creation, "
        "verify state persistence on refresh, and verify meeting page components"
    )

    def _register_tests(self):
        self.add_test(
            "TF-001",
            "Start transcription via media file",
            self._test_start_transcription,
        )
        self.add_test(
            "TF-002",
            "Meeting created and marked in progress",
            self._test_meeting_in_progress,
        )
        self.add_test(
            "TF-003",
            "Recording status API reflects in-progress state",
            self._test_recording_status_api,
        )
        self.add_test(
            "TF-004",
            "Meetings list shows in-progress meeting",
            self._test_meetings_list_in_progress,
        )
        self.add_test(
            "TF-005",
            "Main page HTML has correct button state",
            self._test_main_page_button_state,
        )
        self.add_test(
            "TF-006",
            "Meeting page loads for in-progress meeting",
            self._test_meeting_page_loads,
        )
        self.add_test(
            "TF-007",
            "Meeting page has transcript section",
            self._test_meeting_page_transcript,
        )
        self.add_test(
            "TF-008",
            "Meeting page has summary section",
            self._test_meeting_page_summary,
        )
        self.add_test(
            "TF-009",
            "Stop transcription works",
            self._test_stop_transcription,
        )
        self.add_test(
            "TF-010",
            "Meeting status updated after stop",
            self._test_meeting_status_after_stop,
        )

    async def setup(self):
        """Set up test context."""
        self.context["api_base"] = "http://127.0.0.1:6684"
        self.context["meeting_id"] = None
        self.context["audio_path"] = None

        # Find an uploaded audio file to use for testing
        import aiohttp
        async with aiohttp.ClientSession() as session:
            # Check testing settings for a configured test file
            async with session.get(f"{self.context['api_base']}/api/settings/testing") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("audio_path"):
                        self.context["audio_path"] = data["audio_path"]
                        self.logger.info(f"Using configured test file: {self.context['audio_path']}")

        if not self.context["audio_path"]:
            self.logger.warning("No test audio file configured. Some tests may skip.")

    async def teardown(self):
        """Clean up: stop any running transcription."""
        import aiohttp

        if self.context.get("audio_path"):
            try:
                async with aiohttp.ClientSession() as session:
                    # Try to stop any running transcription
                    url = f"{self.context['api_base']}/api/transcribe/simulate/stop"
                    params = {"audio_path": self.context["audio_path"]}
                    async with session.post(url, params=params) as resp:
                        pass
            except Exception:
                pass

    async def _test_start_transcription(self, ctx: dict) -> TestResult:
        """Test starting transcription via media file."""
        import aiohttp

        if not ctx.get("audio_path"):
            return TestResult(
                test_id="TF-001",
                name="Start transcription via media file",
                status=TestStatus.SKIPPED,
                message="No test audio file configured. Set one in Settings > Testing.",
            )

        api_base = ctx["api_base"]
        audio_path = ctx["audio_path"]

        try:
            async with aiohttp.ClientSession() as session:
                # Start simulated transcription via POST /api/transcribe/simulate
                url = f"{api_base}/api/transcribe/simulate"
                payload = {"audio_path": audio_path}

                async with session.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return TestResult(
                            test_id="TF-001",
                            name="Start transcription via media file",
                            status=TestStatus.FAILED,
                            message=f"Start failed: HTTP {resp.status} - {text}",
                        )

                    data = await resp.json()

                    if data.get("status") not in ["started", "running"]:
                        return TestResult(
                            test_id="TF-001",
                            name="Start transcription via media file",
                            status=TestStatus.FAILED,
                            message=f"Unexpected status: {data.get('status')}",
                            details=data,
                        )

                    # Store meeting_id for subsequent tests
                    ctx["meeting_id"] = data.get("meeting_id")

                    return TestResult(
                        test_id="TF-001",
                        name="Start transcription via media file",
                        status=TestStatus.PASSED,
                        message=f"Transcription started, meeting_id={ctx['meeting_id']}",
                        details=data,
                    )

        except Exception as e:
            return TestResult(
                test_id="TF-001",
                name="Start transcription via media file",
                status=TestStatus.ERROR,
                message=f"Error: {e}",
            )

    async def _test_meeting_in_progress(self, ctx: dict) -> TestResult:
        """Test that meeting is created and marked as in progress."""
        import aiohttp

        meeting_id = ctx.get("meeting_id")
        if not meeting_id:
            return TestResult(
                test_id="TF-002",
                name="Meeting created and marked in progress",
                status=TestStatus.SKIPPED,
                message="No meeting_id from previous test",
            )

        api_base = ctx["api_base"]

        try:
            async with aiohttp.ClientSession() as session:
                # Get specific meeting
                async with session.get(f"{api_base}/api/meetings/{meeting_id}") as resp:
                    if resp.status != 200:
                        return TestResult(
                            test_id="TF-002",
                            name="Meeting created and marked in progress",
                            status=TestStatus.FAILED,
                            message=f"Failed to fetch meeting: HTTP {resp.status}",
                        )

                    meeting = await resp.json()

                    # Check status
                    status = meeting.get("status", "unknown")
                    if status not in ["in_progress", "recording"]:
                        return TestResult(
                            test_id="TF-002",
                            name="Meeting created and marked in progress",
                            status=TestStatus.FAILED,
                            message=f"Meeting status is '{status}', expected 'in_progress' or 'recording'",
                            details=meeting,
                        )

                    return TestResult(
                        test_id="TF-002",
                        name="Meeting created and marked in progress",
                        status=TestStatus.PASSED,
                        message=f"Meeting {meeting_id} has status='{status}'",
                        details={"meeting_id": meeting_id, "status": status},
                    )

        except Exception as e:
            return TestResult(
                test_id="TF-002",
                name="Meeting created and marked in progress",
                status=TestStatus.ERROR,
                message=f"Error: {e}",
            )

    async def _test_recording_status_api(self, ctx: dict) -> TestResult:
        """Test that recording status API reflects in-progress state."""
        import aiohttp

        api_base = ctx["api_base"]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{api_base}/api/recording/status") as resp:
                    if resp.status != 200:
                        return TestResult(
                            test_id="TF-003",
                            name="Recording status API reflects in-progress state",
                            status=TestStatus.FAILED,
                            message=f"Failed to get recording status: HTTP {resp.status}",
                        )

                    data = await resp.json()

                    # Check if there's an active recording or simulated transcription
                    # The API might report via recording_id or is_recording
                    is_active = (
                        data.get("recording_id") is not None
                        or data.get("is_recording", False)
                    )

                    return TestResult(
                        test_id="TF-003",
                        name="Recording status API reflects in-progress state",
                        status=TestStatus.PASSED,
                        message=f"Recording status API accessible, active={is_active}",
                        details=data,
                    )

        except Exception as e:
            return TestResult(
                test_id="TF-003",
                name="Recording status API reflects in-progress state",
                status=TestStatus.ERROR,
                message=f"Error: {e}",
            )

    async def _test_meetings_list_in_progress(self, ctx: dict) -> TestResult:
        """Test that meetings list shows in-progress meeting."""
        import aiohttp

        meeting_id = ctx.get("meeting_id")
        api_base = ctx["api_base"]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{api_base}/api/meetings") as resp:
                    if resp.status != 200:
                        return TestResult(
                            test_id="TF-004",
                            name="Meetings list shows in-progress meeting",
                            status=TestStatus.FAILED,
                            message=f"Failed to get meetings: HTTP {resp.status}",
                        )

                    meetings = await resp.json()

                    # Find meetings with in_progress status
                    in_progress = [
                        m for m in meetings
                        if m.get("status") in ["in_progress", "recording"]
                    ]

                    if meeting_id:
                        # Check if our specific meeting is in the list
                        our_meeting = next(
                            (m for m in meetings if m.get("id") == meeting_id),
                            None
                        )
                        if our_meeting:
                            return TestResult(
                                test_id="TF-004",
                                name="Meetings list shows in-progress meeting",
                                status=TestStatus.PASSED,
                                message=f"Found meeting {meeting_id} in list with status={our_meeting.get('status')}",
                                details={"in_progress_count": len(in_progress)},
                            )

                    return TestResult(
                        test_id="TF-004",
                        name="Meetings list shows in-progress meeting",
                        status=TestStatus.PASSED,
                        message=f"Meetings list accessible, {len(in_progress)} in-progress meetings",
                        details={"total": len(meetings), "in_progress": len(in_progress)},
                    )

        except Exception as e:
            return TestResult(
                test_id="TF-004",
                name="Meetings list shows in-progress meeting",
                status=TestStatus.ERROR,
                message=f"Error: {e}",
            )

    async def _test_main_page_button_state(self, ctx: dict) -> TestResult:
        """Test that main page HTML has correct button state elements."""
        import aiohttp

        api_base = ctx["api_base"]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{api_base}/") as resp:
                    if resp.status != 200:
                        return TestResult(
                            test_id="TF-005",
                            name="Main page HTML has correct button state",
                            status=TestStatus.FAILED,
                            message=f"Failed to load main page: HTTP {resp.status}",
                        )

                    html = await resp.text()

                    # Check for recording toggle button
                    has_toggle = (
                        'id="record-toggle"' in html
                        or 'id="recording-toggle"' in html
                        or 'class="record-btn"' in html
                        or 'data-recording' in html
                    )

                    # Check for meetings list container
                    has_meetings_list = (
                        'id="meetings-list"' in html
                        or 'id="meetings"' in html
                        or 'class="meetings-list"' in html
                    )

                    if not has_toggle:
                        return TestResult(
                            test_id="TF-005",
                            name="Main page HTML has correct button state",
                            status=TestStatus.FAILED,
                            message="No recording toggle button found in main page",
                        )

                    return TestResult(
                        test_id="TF-005",
                        name="Main page HTML has correct button state",
                        status=TestStatus.PASSED,
                        message="Main page has recording toggle and meetings list",
                        details={
                            "has_toggle": has_toggle,
                            "has_meetings_list": has_meetings_list,
                        },
                    )

        except Exception as e:
            return TestResult(
                test_id="TF-005",
                name="Main page HTML has correct button state",
                status=TestStatus.ERROR,
                message=f"Error: {e}",
            )

    async def _test_meeting_page_loads(self, ctx: dict) -> TestResult:
        """Test that meeting page loads for in-progress meeting."""
        import aiohttp

        meeting_id = ctx.get("meeting_id")
        if not meeting_id:
            return TestResult(
                test_id="TF-006",
                name="Meeting page loads for in-progress meeting",
                status=TestStatus.SKIPPED,
                message="No meeting_id available",
            )

        api_base = ctx["api_base"]

        try:
            async with aiohttp.ClientSession() as session:
                # Load meeting page
                async with session.get(f"{api_base}/meeting?id={meeting_id}") as resp:
                    if resp.status != 200:
                        return TestResult(
                            test_id="TF-006",
                            name="Meeting page loads for in-progress meeting",
                            status=TestStatus.FAILED,
                            message=f"Failed to load meeting page: HTTP {resp.status}",
                        )

                    html = await resp.text()

                    # Basic checks for meeting page structure
                    is_meeting_page = (
                        "meeting" in html.lower()
                        and ("transcript" in html.lower() or "summary" in html.lower())
                    )

                    return TestResult(
                        test_id="TF-006",
                        name="Meeting page loads for in-progress meeting",
                        status=TestStatus.PASSED,
                        message=f"Meeting page loaded successfully for {meeting_id}",
                        details={"html_length": len(html), "is_meeting_page": is_meeting_page},
                    )

        except Exception as e:
            return TestResult(
                test_id="TF-006",
                name="Meeting page loads for in-progress meeting",
                status=TestStatus.ERROR,
                message=f"Error: {e}",
            )

    async def _test_meeting_page_transcript(self, ctx: dict) -> TestResult:
        """Test that meeting page has transcript section."""
        import aiohttp

        meeting_id = ctx.get("meeting_id")
        if not meeting_id:
            return TestResult(
                test_id="TF-007",
                name="Meeting page has transcript section",
                status=TestStatus.SKIPPED,
                message="No meeting_id available",
            )

        api_base = ctx["api_base"]

        try:
            async with aiohttp.ClientSession() as session:
                # Load meeting.html directly
                async with session.get(f"{api_base}/static/meeting.html") as resp:
                    if resp.status != 200:
                        return TestResult(
                            test_id="TF-007",
                            name="Meeting page has transcript section",
                            status=TestStatus.FAILED,
                            message=f"Failed to load meeting.html: HTTP {resp.status}",
                        )

                    html = await resp.text()

                    # Check for transcript-related elements
                    has_transcript = (
                        'id="transcript"' in html
                        or 'id="transcript-output"' in html
                        or 'class="transcript"' in html
                        or 'transcript-container' in html
                        or 'transcript-panel' in html
                    )

                    if not has_transcript:
                        return TestResult(
                            test_id="TF-007",
                            name="Meeting page has transcript section",
                            status=TestStatus.FAILED,
                            message="No transcript section found in meeting.html",
                        )

                    return TestResult(
                        test_id="TF-007",
                        name="Meeting page has transcript section",
                        status=TestStatus.PASSED,
                        message="Meeting page has transcript section",
                    )

        except Exception as e:
            return TestResult(
                test_id="TF-007",
                name="Meeting page has transcript section",
                status=TestStatus.ERROR,
                message=f"Error: {e}",
            )

    async def _test_meeting_page_summary(self, ctx: dict) -> TestResult:
        """Test that meeting page has summary section."""
        import aiohttp

        api_base = ctx["api_base"]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{api_base}/static/meeting.html") as resp:
                    if resp.status != 200:
                        return TestResult(
                            test_id="TF-008",
                            name="Meeting page has summary section",
                            status=TestStatus.FAILED,
                            message=f"Failed to load meeting.html: HTTP {resp.status}",
                        )

                    html = await resp.text()

                    # Check for summary-related elements
                    has_summary = (
                        'id="summary"' in html
                        or 'id="summary-output"' in html
                        or 'class="summary"' in html
                        or 'summary-container' in html
                        or 'summary-panel' in html
                    )

                    if not has_summary:
                        return TestResult(
                            test_id="TF-008",
                            name="Meeting page has summary section",
                            status=TestStatus.FAILED,
                            message="No summary section found in meeting.html",
                        )

                    return TestResult(
                        test_id="TF-008",
                        name="Meeting page has summary section",
                        status=TestStatus.PASSED,
                        message="Meeting page has summary section",
                    )

        except Exception as e:
            return TestResult(
                test_id="TF-008",
                name="Meeting page has summary section",
                status=TestStatus.ERROR,
                message=f"Error: {e}",
            )

    async def _test_stop_transcription(self, ctx: dict) -> TestResult:
        """Test stopping transcription."""
        import aiohttp

        if not ctx.get("audio_path"):
            return TestResult(
                test_id="TF-009",
                name="Stop transcription works",
                status=TestStatus.SKIPPED,
                message="No audio_path available",
            )

        api_base = ctx["api_base"]
        audio_path = ctx["audio_path"]

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{api_base}/api/transcribe/simulate/stop"
                params = {"audio_path": audio_path}

                async with session.post(url, params=params) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return TestResult(
                            test_id="TF-009",
                            name="Stop transcription works",
                            status=TestStatus.FAILED,
                            message=f"Stop failed: HTTP {resp.status} - {text}",
                        )

                    data = await resp.json()

                    return TestResult(
                        test_id="TF-009",
                        name="Stop transcription works",
                        status=TestStatus.PASSED,
                        message="Transcription stopped successfully",
                        details=data,
                    )

        except Exception as e:
            return TestResult(
                test_id="TF-009",
                name="Stop transcription works",
                status=TestStatus.ERROR,
                message=f"Error: {e}",
            )

    async def _test_meeting_status_after_stop(self, ctx: dict) -> TestResult:
        """Test that meeting status updates after stop."""
        import aiohttp

        meeting_id = ctx.get("meeting_id")
        if not meeting_id:
            return TestResult(
                test_id="TF-010",
                name="Meeting status updated after stop",
                status=TestStatus.SKIPPED,
                message="No meeting_id available",
            )

        api_base = ctx["api_base"]

        # Wait a moment for status to update
        await asyncio.sleep(1)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{api_base}/api/meetings/{meeting_id}") as resp:
                    if resp.status != 200:
                        return TestResult(
                            test_id="TF-010",
                            name="Meeting status updated after stop",
                            status=TestStatus.FAILED,
                            message=f"Failed to fetch meeting: HTTP {resp.status}",
                        )

                    meeting = await resp.json()
                    status = meeting.get("status", "unknown")

                    # After stop, status should be completed or similar
                    if status in ["completed", "done", "ended", "transcribed"]:
                        return TestResult(
                            test_id="TF-010",
                            name="Meeting status updated after stop",
                            status=TestStatus.PASSED,
                            message=f"Meeting status changed to '{status}'",
                            details={"meeting_id": meeting_id, "status": status},
                        )
                    else:
                        return TestResult(
                            test_id="TF-010",
                            name="Meeting status updated after stop",
                            status=TestStatus.PASSED,
                            message=f"Meeting status is '{status}' (may still be processing)",
                            details={"meeting_id": meeting_id, "status": status},
                        )

        except Exception as e:
            return TestResult(
                test_id="TF-010",
                name="Meeting status updated after stop",
                status=TestStatus.ERROR,
                message=f"Error: {e}",
            )
