"""HuggingFace model cache manager.

Scans the local HF cache for downloaded models, checks for updates,
and downloads models on demand.  All network operations temporarily
clear HF_HUB_OFFLINE so that the rest of the app stays offline by
default.
"""

import logging
import os
from typing import Optional

_logger = logging.getLogger("notetaker.hf_models")

# Every HuggingFace model that Notetaker might auto-download at runtime.
KNOWN_MODELS = [
    # -- Batch diarization (pyannote) --
    {
        "id": "pyannote/speaker-diarization-3.1",
        "label": "Speaker Diarization 3.1",
        "group": "Batch Diarization",
        "gated": True,
    },
    {
        "id": "pyannote/speaker-diarization-3.0",
        "label": "Speaker Diarization 3.0",
        "group": "Batch Diarization",
        "gated": True,
    },
    {
        "id": "pyannote/segmentation-3.0",
        "label": "Segmentation 3.0",
        "group": "Batch Diarization",
        "gated": True,
    },
    {
        "id": "pyannote/wespeaker-voxceleb-resnet34-LM",
        "label": "Speaker Embedding (WeSpeaker)",
        "group": "Batch Diarization",
        "gated": False,
    },
    # -- Real-time diarization (diart) --
    {
        "id": "pyannote/segmentation",
        "label": "Segmentation (v1)",
        "group": "Real-time Diarization",
        "gated": True,
    },
    {
        "id": "pyannote/embedding",
        "label": "Speaker Embedding",
        "group": "Real-time Diarization",
        "gated": True,
    },
    # -- Transcription (faster-whisper via CTranslate2) --
    {
        "id": "Systran/faster-whisper-tiny",
        "label": "Whisper Tiny",
        "group": "Transcription",
        "gated": False,
    },
    {
        "id": "Systran/faster-whisper-base",
        "label": "Whisper Base",
        "group": "Transcription",
        "gated": False,
    },
    {
        "id": "Systran/faster-whisper-small",
        "label": "Whisper Small",
        "group": "Transcription",
        "gated": False,
    },
    {
        "id": "Systran/faster-whisper-medium",
        "label": "Whisper Medium",
        "group": "Transcription",
        "gated": False,
    },
    {
        "id": "Systran/faster-whisper-large-v3",
        "label": "Whisper Large V3",
        "group": "Transcription",
        "gated": False,
    },
]


def _get_cache_info(model_id: str) -> dict:
    """Return cache status for a single model."""
    try:
        from huggingface_hub import scan_cache_dir
        cache = scan_cache_dir()
        for repo in cache.repos:
            if repo.repo_id == model_id:
                total_size = repo.size_on_disk
                local_hash = None
                for rev in repo.revisions:
                    if "main" in rev.refs:
                        local_hash = rev.commit_hash
                        break
                if local_hash is None and repo.revisions:
                    local_hash = next(iter(repo.revisions)).commit_hash
                return {
                    "cached": True,
                    "size_bytes": total_size,
                    "size_mb": round(total_size / (1024 * 1024), 1),
                    "local_hash": local_hash,
                }
        return {"cached": False}
    except Exception as exc:
        _logger.warning("Cache scan failed for %s: %s", model_id, exc)
        return {"cached": False, "error": str(exc)}


def list_models() -> list[dict]:
    """All known models with their local cache status."""
    out = []
    for m in KNOWN_MODELS:
        info = _get_cache_info(m["id"])
        out.append({**m, **info})
    return out


def _with_network(fn, *args, **kwargs):
    """Run *fn* with HF_HUB_OFFLINE temporarily cleared."""
    prev = os.environ.pop("HF_HUB_OFFLINE", None)
    try:
        return fn(*args, **kwargs)
    finally:
        # Always restore offline mode (boot default is "1").
        os.environ["HF_HUB_OFFLINE"] = prev if prev is not None else "1"


def check_for_update(model_id: str, hf_token: Optional[str] = None) -> dict:
    """Go online briefly to see if a newer revision exists."""
    local = _get_cache_info(model_id)
    local_hash = local.get("local_hash")

    try:
        from huggingface_hub import model_info as _model_info
        info = _with_network(_model_info, model_id, token=hf_token)
        remote_hash = info.sha

        if not local.get("cached"):
            return {
                "model_id": model_id,
                "cached": False,
                "update_available": True,
                "remote_hash": remote_hash,
                "message": "Model not cached — download required.",
            }

        update = bool(local_hash and remote_hash and local_hash != remote_hash)
        return {
            "model_id": model_id,
            "cached": True,
            "update_available": update,
            "local_hash": local_hash,
            "remote_hash": remote_hash,
            "message": "Newer version available." if update else "Up to date.",
        }
    except Exception as exc:
        return {
            "model_id": model_id,
            "error": str(exc),
            "message": f"Check failed: {str(exc)[:200]}",
        }


def download_model(model_id: str, hf_token: Optional[str] = None) -> dict:
    """Download (or update) a model from HuggingFace Hub."""
    try:
        from huggingface_hub import snapshot_download
        _logger.info("Downloading model: %s", model_id)
        path = _with_network(snapshot_download, model_id, token=hf_token)
        cache = _get_cache_info(model_id)
        return {
            "model_id": model_id,
            "status": "ok",
            "path": str(path),
            "message": "Download complete.",
            **cache,
        }
    except Exception as exc:
        _logger.error("Download failed for %s: %s", model_id, exc)
        return {
            "model_id": model_id,
            "status": "error",
            "message": f"Download failed: {str(exc)[:200]}",
        }
