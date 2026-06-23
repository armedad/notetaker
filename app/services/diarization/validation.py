"""Preflight checks and user-facing error messages for diarization."""

from __future__ import annotations

import os
from typing import Optional


def resolve_hf_token(config_token: Optional[str]) -> Optional[str]:
    """Resolve HF token from config value or HF_TOKEN environment variable."""
    token = (config_token or "").strip()
    if not token:
        token = (os.environ.get("HF_TOKEN") or "").strip()
    return token or None


def is_valid_hf_token(token: Optional[str]) -> bool:
    """Return True when token looks like a real HuggingFace API token."""
    if not token or not isinstance(token, str):
        return False
    token = token.strip()
    if not token.startswith("hf_"):
        return False
    if len(token) < 20:
        return False
    return True


def hf_token_error_message() -> str:
    return (
        "HuggingFace token is missing or invalid. Add a valid token (starts with hf_) "
        "in Settings → Diarization and accept the pyannote model licenses at huggingface.co."
    )


def validate_device(device: str) -> Optional[str]:
    """Return an error message when the requested device is unavailable."""
    dev = (device or "cpu").lower().strip()
    if dev == "cuda":
        try:
            import torch
        except ImportError:
            return (
                "CUDA device requested but PyTorch is not installed with CUDA support. "
                "Change diarization device to CPU in Settings."
            )
        if not torch.cuda.is_available():
            return (
                "CUDA device requested but no NVIDIA GPU is available. "
                "Change diarization device to CPU in Settings."
            )
    elif dev == "mps":
        try:
            import torch
        except ImportError:
            return (
                "MPS device requested but PyTorch is not installed. "
                "Change diarization device to CPU in Settings."
            )
        if not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
            return (
                "MPS device requested but Apple Silicon GPU is not available. "
                "Change diarization device to CPU in Settings."
            )
    return None


def check_diarization_prerequisites(
    hf_token: Optional[str],
    device: str,
    *,
    require_hf_token: bool = True,
) -> Optional[str]:
    """Return an error message when diarization cannot start, else None."""
    token = resolve_hf_token(hf_token)
    if require_hf_token and not is_valid_hf_token(token):
        return hf_token_error_message()
    return validate_device(device)


def format_diarization_start_error(exc: Exception) -> str:
    """Map common diarization exceptions to actionable user messages."""
    msg = str(exc)
    lower = msg.lower()
    if any(
        needle in lower
        for needle in (
            "401",
            "unauthorized",
            "invalid token",
            "authentication",
            "gated repo",
            "cannot access gated",
            "access to model",
        )
    ):
        return hf_token_error_message()
    if "cuda" in lower and any(
        needle in lower
        for needle in ("not available", "no cuda", "cuda error", "no kernel image", "invalid device")
    ):
        return (
            "CUDA error: GPU is not available or failed to initialize. "
            "Change diarization device to CPU in Settings."
        )
    return f"Diarization failed: {type(exc).__name__}: {msg}"
