"""Resolve shared test audio paths for the in-app E2E harness."""
from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def harness_audio_dir() -> Path:
    linked = Path(__file__).resolve().parent / "fixtures" / "audio"
    if linked.is_dir():
        return linked
    return project_root() / "tests" / "fixtures" / "audio"


def speech_wav_path() -> str | None:
    path = harness_audio_dir() / "speech_5s.wav"
    return str(path) if path.is_file() else None


def two_speaker_wav_path() -> str | None:
    path = harness_audio_dir() / "two_speaker_30s.wav"
    return str(path) if path.is_file() else None
