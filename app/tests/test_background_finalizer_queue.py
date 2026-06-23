"""Tests for event-driven BackgroundFinalizer queue (no polling)."""
from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from app.services.active_meeting_tracker import get_tracker
from app.services.background_finalizer import BackgroundFinalizer, _BOOT_DELAY_SECONDS


class BackgroundFinalizerQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        get_tracker().clear()

    def _make_finalizer(self) -> BackgroundFinalizer:
        store = MagicMock()
        store.needs_finalization.return_value = True
        store.get_meeting.return_value = {
            "id": "m1",
            "status": "completed",
            "audio_path": "/tmp/a.wav",
            "transcript": {"segments": [{"text": "hi", "start": 0, "end": 1}]},
            "finalization": {
                "transcription": "completed",
                "diarization": "pending",
                "speaker_names": "pending",
            },
        }
        store.get_pending_finalization_stages.return_value = ["Diarization"]
        store.get_failed_finalization_stages.return_value = []
        store.list_meetings_needing_finalization.return_value = [store.get_meeting.return_value]

        diarization = MagicMock()
        diarization.is_enabled.return_value = False

        return BackgroundFinalizer(
            store,
            MagicMock(),
            diarization,
            delay_between_meetings=0,
        )

    def test_enqueue_dedupes_same_meeting(self) -> None:
        finalizer = self._make_finalizer()
        self.assertTrue(finalizer.enqueue("m1", reason="test"))
        self.assertTrue(finalizer.enqueue("m1", reason="test"))
        self.assertEqual(finalizer.get_status()["pending_count"], 1)

    def test_enqueue_skips_when_not_needed(self) -> None:
        finalizer = self._make_finalizer()
        finalizer._meeting_store.needs_finalization.return_value = False
        self.assertFalse(finalizer.enqueue("m1"))
        self.assertEqual(finalizer.get_status()["pending_count"], 0)

    def test_worker_processes_enqueued_meeting_without_idle_poll(self) -> None:
        finalizer = self._make_finalizer()
        processed = threading.Event()

        def _finalize_meeting(meeting: dict) -> None:
            processed.set()

        finalizer._finalize_meeting = _finalize_meeting  # type: ignore[method-assign]

        with patch.object(finalizer, "_enqueue_all_pending_at_boot"):
            with patch("app.services.background_finalizer._BOOT_DELAY_SECONDS", 0):
                finalizer.start()
                finalizer.enqueue("m1", reason="unit_test")
                self.assertTrue(
                    processed.wait(timeout=2.0),
                    "expected worker to process enqueued meeting without polling",
                )
                finalizer.stop()

    def test_boot_sweep_enqueues_pending_meetings(self) -> None:
        finalizer = self._make_finalizer()
        count = finalizer.enqueue_all_pending()
        self.assertEqual(count, 1)
        self.assertEqual(finalizer.get_status()["pending_count"], 1)


if __name__ == "__main__":
    unittest.main()
