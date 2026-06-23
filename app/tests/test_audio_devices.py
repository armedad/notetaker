"""Tests for curated audio device listing."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services import audio_devices


class AudioDevicesTests(unittest.TestCase):
    def test_deduplicate_prefers_wasapi(self) -> None:
        fake_devices = [
            {
                "name": "Microphone (Realtek)",
                "max_input_channels": 2,
                "default_samplerate": 48000.0,
                "hostapi": 0,
            },
            {
                "name": "Microphone (Realtek) (WASAPI)",
                "max_input_channels": 2,
                "default_samplerate": 48000.0,
                "hostapi": 1,
            },
            {
                "name": "Microsoft Sound Mapper - Input",
                "max_input_channels": 2,
                "default_samplerate": 44100.0,
                "hostapi": 0,
            },
        ]
        fake_hostapis = [{"name": "MME"}, {"name": "Windows WASAPI"}]

        with patch.object(audio_devices, "_active_capture_names", return_value=frozenset()):
            with patch.object(audio_devices.sd, "query_devices", return_value=fake_devices):
                with patch.object(audio_devices.sd, "query_hostapis", return_value=fake_hostapis):
                    result = audio_devices.list_input_devices()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["display_name"], "Microphone (Realtek)")
        self.assertEqual(result[0]["hostapi"], "Windows WASAPI")

    def test_resolve_system_default_pair(self) -> None:
        class _Pair:
            def __getitem__(self, index: int) -> int:
                return (7, 8)[index]

        with patch.object(audio_devices.sd, "default", type("Defaults", (), {"device": _Pair()})()):
            self.assertEqual(audio_devices.resolve_system_input_device_index(), 7)

    def test_resolve_system_default_tuple(self) -> None:
        class _Defaults:
            device = (7, 8)

        with patch.object(audio_devices.sd, "default", _Defaults()):
            self.assertEqual(audio_devices.resolve_system_input_device_index(), 7)

    def test_balance_truncated_parenthesis(self) -> None:
        self.assertEqual(
            audio_devices._normalize_key("Microphone (Jabra SPEAK 510 USB"),
            audio_devices._normalize_key("Microphone (Jabra SPEAK 510 USB)"),
        )

    def test_extract_bluetooth_friendly_name(self) -> None:
        raw = "Headset (@System32\\drivers\\bthhfenum.sys,#2;%1 Hands-Free%0\r\n;(WH-1000XM3))"
        self.assertEqual(audio_devices._friendly_label(raw), "Headset (WH-1000XM3)")

    def test_skip_nameless_input(self) -> None:
        self.assertTrue(audio_devices._is_nameless_endpoint("Input ()"))

    def test_filters_inactive_bluetooth_when_active_set_known(self) -> None:
        fake_devices = [
            {
                "name": "Headset (@System32\\drivers\\bthhfenum.sys,#2;%1 Hands-Free%0\r\n;(WH-1000XM3))",
                "max_input_channels": 1,
                "default_samplerate": 8000.0,
                "hostapi": 1,
            },
            {
                "name": "Microphone (Logitech BRIO)",
                "max_input_channels": 2,
                "default_samplerate": 48000.0,
                "hostapi": 0,
            },
        ]
        fake_hostapis = [{"name": "Windows WASAPI"}, {"name": "Windows WDM-KS"}]

        with patch.object(
            audio_devices,
            "_active_capture_names",
            return_value=frozenset({"Microphone (Logitech BRIO)"}),
        ):
            with patch.object(audio_devices.sd, "query_devices", return_value=fake_devices):
                with patch.object(audio_devices.sd, "query_hostapis", return_value=fake_hostapis):
                    result = audio_devices.list_input_devices()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["display_name"], "Microphone (Logitech BRIO)")


if __name__ == "__main__":
    unittest.main()
