import json
import logging
import os
import threading

import requests

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional

from app.services.llm.ollama_provider import ensure_ollama_running

_logger = logging.getLogger("notetaker.settings")


class SummarizationSettingsRequest(BaseModel):
    provider: str = Field(..., min_length=1)
    ollama_base_url: str
    ollama_model: str
    openai_api_key: str
    openai_model: str
    anthropic_api_key: str
    anthropic_model: str
    lmstudio_base_url: str
    lmstudio_model: str


class DiarizationSettingsRequest(BaseModel):
    """Legacy unified diarization settings (for backwards compatibility)."""
    enabled: bool
    provider: str
    model: str
    device: str
    hf_token: Optional[str] = None
    performance_level: float = 0.5


class RealtimeDiarizationSettingsRequest(BaseModel):
    """Real-time diarization settings (runs during live transcription)."""
    enabled: bool
    provider: str  # "diart" or "none"
    device: str = "cpu"
    hf_token: Optional[str] = None
    performance_level: float = 0.5


class BatchDiarizationSettingsRequest(BaseModel):
    """Batch diarization settings (runs after transcription completes)."""
    enabled: bool
    provider: str  # "pyannote", "whisperx", "diart", or "none"
    model: str = "pyannote/speaker-diarization-3.1"
    device: str = "cpu"
    hf_token: Optional[str] = None


class ModelTestRequest(BaseModel):
    provider: str = Field(..., min_length=1)
    api_key: str = ""
    base_url: str = ""


class ModelRegistryRequest(BaseModel):
    registry: list[dict]
    selected_model: str = ""


class ProviderSettingsRequest(BaseModel):
    openai: dict
    anthropic: dict
    gemini: dict
    grok: dict
    ollama: dict
    lmstudio: dict


class TranscriptionSettingsRequest(BaseModel):
    live_model_size: str
    final_model_size: str
    auto_transcribe: bool
    stream_transcribe: bool
    live_transcribe: bool
    consolidation_max_duration: float = 15.0
    consolidation_max_gap: float = 2.0


class TestingSettingsRequest(BaseModel):
    audio_path: str = ""
    audio_name: str = ""


class AppearanceSettingsRequest(BaseModel):
    theme: str = "system"  # "light", "dark", or "system"


def create_settings_router(config_path: str) -> APIRouter:
    router = APIRouter()

    @router.get("/api/settings/summarization")
    def get_summarization_settings() -> dict:
        if not os.path.exists(config_path):
            return {}
        with open(config_path, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)
        return data.get("summarization", {})

    @router.post("/api/settings/summarization")
    def update_summarization_settings(payload: SummarizationSettingsRequest) -> dict:
        data = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        data["summarization"] = payload.model_dump()
        with open(config_path, "w", encoding="utf-8") as config_file:
            json.dump(data, config_file, indent=2)
        return {"status": "ok"}

    def _gpu_available() -> bool:
        try:
            import torch
        except Exception:
            return False
        return bool(torch.cuda.is_available())

    @router.get("/api/settings/diarization")
    def get_diarization_settings() -> dict:
        diarization = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as config_file:
                data = json.load(config_file)
            diarization = data.get("diarization", {})
        diarization["gpu_available"] = _gpu_available()
        return diarization

    @router.post("/api/settings/diarization")
    def update_diarization_settings(payload: DiarizationSettingsRequest) -> dict:
        """Legacy endpoint - updates unified diarization settings."""
        data = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        data["diarization"] = payload.model_dump()
        with open(config_path, "w", encoding="utf-8") as config_file:
            json.dump(data, config_file, indent=2)
        return {"status": "ok"}

    @router.get("/api/settings/diarization/realtime")
    def get_realtime_diarization_settings() -> dict:
        """Get real-time diarization settings."""
        if not os.path.exists(config_path):
            return {
                "enabled": False,
                "provider": "none",
                "device": "cpu",
                "hf_token": "",
                "performance_level": 0.5,
                "gpu_available": _gpu_available(),
            }
        with open(config_path, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)
        
        diarization = data.get("diarization", {})
        
        # Check for new split format
        if "realtime" in diarization:
            result = diarization["realtime"].copy()
        else:
            # Legacy format - extract realtime-relevant settings
            # Real-time is only enabled if provider is diart
            legacy_enabled = diarization.get("enabled", False)
            legacy_provider = diarization.get("provider", "none")
            result = {
                "enabled": legacy_enabled and legacy_provider.lower() == "diart",
                "provider": "diart" if legacy_provider.lower() == "diart" else "none",
                "device": diarization.get("device", "cpu"),
                "hf_token": diarization.get("hf_token", ""),
                "performance_level": diarization.get("performance_level", 0.5),
            }
        
        result["gpu_available"] = _gpu_available()
        return result

    @router.post("/api/settings/diarization/realtime")
    def update_realtime_diarization_settings(payload: RealtimeDiarizationSettingsRequest) -> dict:
        """Update real-time diarization settings."""
        data = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        
        diarization = data.get("diarization", {})
        
        # Convert to new split format if needed
        if "realtime" not in diarization:
            # Migrate from legacy to split format
            batch_settings = {
                "enabled": diarization.get("enabled", False) and diarization.get("provider", "").lower() != "diart",
                "provider": diarization.get("provider", "none") if diarization.get("provider", "").lower() != "diart" else "none",
                "model": diarization.get("model", "pyannote/speaker-diarization-3.1"),
                "device": diarization.get("device", "cpu"),
                "hf_token": diarization.get("hf_token", ""),
            }
            diarization = {"batch": batch_settings}
        
        diarization["realtime"] = payload.model_dump()
        data["diarization"] = diarization
        
        with open(config_path, "w", encoding="utf-8") as config_file:
            json.dump(data, config_file, indent=2)
        return {"status": "ok"}

    @router.get("/api/settings/diarization/batch")
    def get_batch_diarization_settings() -> dict:
        """Get batch diarization settings."""
        if not os.path.exists(config_path):
            return {
                "enabled": False,
                "provider": "none",
                "model": "pyannote/speaker-diarization-3.1",
                "device": "cpu",
                "hf_token": "",
                "gpu_available": _gpu_available(),
            }
        with open(config_path, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)
        
        diarization = data.get("diarization", {})
        
        # Check for new split format
        if "batch" in diarization:
            result = diarization["batch"].copy()
        else:
            # Legacy format - extract batch-relevant settings
            # Batch is enabled for non-diart providers
            legacy_enabled = diarization.get("enabled", False)
            legacy_provider = diarization.get("provider", "none")
            is_batch = legacy_provider.lower() not in ("diart", "none")
            result = {
                "enabled": legacy_enabled and is_batch,
                "provider": legacy_provider if is_batch else "none",
                "model": diarization.get("model", "pyannote/speaker-diarization-3.1"),
                "device": diarization.get("device", "cpu"),
                "hf_token": diarization.get("hf_token", ""),
            }
        
        result["gpu_available"] = _gpu_available()
        return result

    @router.post("/api/settings/diarization/batch")
    def update_batch_diarization_settings(payload: BatchDiarizationSettingsRequest) -> dict:
        """Update batch diarization settings."""
        data = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        
        diarization = data.get("diarization", {})
        
        # Convert to new split format if needed
        if "batch" not in diarization:
            # Migrate from legacy to split format
            realtime_settings = {
                "enabled": diarization.get("enabled", False) and diarization.get("provider", "").lower() == "diart",
                "provider": "diart" if diarization.get("provider", "").lower() == "diart" else "none",
                "device": diarization.get("device", "cpu"),
                "hf_token": diarization.get("hf_token", ""),
                "performance_level": diarization.get("performance_level", 0.5),
            }
            diarization = {"realtime": realtime_settings}
        
        diarization["batch"] = payload.model_dump()
        data["diarization"] = diarization
        
        with open(config_path, "w", encoding="utf-8") as config_file:
            json.dump(data, config_file, indent=2)
        return {"status": "ok"}

    @router.post("/api/settings/diarization/test")
    def test_diarization_access() -> dict:
        """Test if HuggingFace token has access to pyannote models."""
        if not os.path.exists(config_path):
            return {"status": "error", "message": "No configuration found"}
        
        with open(config_path, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)
        
        diarization = data.get("diarization", {})
        
        # Find HF token from new split format or legacy format
        hf_token = ""
        if "batch" in diarization:
            hf_token = diarization["batch"].get("hf_token", "")
        if not hf_token and "realtime" in diarization:
            hf_token = diarization["realtime"].get("hf_token", "")
        if not hf_token:
            hf_token = diarization.get("hf_token", "")
        
        if not hf_token:
            return {
                "status": "error",
                "message": "HuggingFace token not configured. Get one at https://huggingface.co/settings/tokens"
            }
        
        # Test access to the required models
        models_to_check = [
            "pyannote/speaker-diarization-3.1",
            "pyannote/segmentation-3.0",
        ]
        
        results = []
        for model in models_to_check:
            try:
                response = requests.get(
                    f"https://huggingface.co/api/models/{model}",
                    headers={"Authorization": f"Bearer {hf_token}"},
                    timeout=10,
                )
                if response.status_code == 200:
                    results.append({"model": model, "status": "ok"})
                elif response.status_code == 403:
                    results.append({
                        "model": model,
                        "status": "error",
                        "message": f"License not accepted. Visit https://huggingface.co/{model} to accept."
                    })
                elif response.status_code == 401:
                    results.append({
                        "model": model,
                        "status": "error", 
                        "message": "Invalid HuggingFace token"
                    })
                else:
                    results.append({
                        "model": model,
                        "status": "error",
                        "message": f"HTTP {response.status_code}"
                    })
            except Exception as exc:
                results.append({
                    "model": model,
                    "status": "error",
                    "message": str(exc)
                })
        
        all_ok = all(r["status"] == "ok" for r in results)
        return {
            "status": "ok" if all_ok else "error",
            "models": results,
            "message": "All models accessible" if all_ok else "Some models require license acceptance"
        }

    @router.post("/api/settings/models/test")
    def test_model_access(payload: ModelTestRequest) -> dict:
        provider = payload.provider.lower()
        if provider in {"openai", "lmstudio"}:
            base_url = (
                payload.base_url.strip()
                if payload.base_url
                else "https://api.openai.com"
            )
            headers = {
                "Authorization": f"Bearer {payload.api_key or 'lmstudio'}",
                "Content-Type": "application/json",
            }
            response = requests.get(
                f"{base_url.rstrip('/')}/v1/models", headers=headers, timeout=15
            )
            if response.status_code != 200:
                return {"status": "error", "message": f"{provider} error: {response.status_code}"}
            data = response.json()
            models = [item.get("id") for item in data.get("data", []) if item.get("id")]
            return {"status": "ok", "models": sorted(models)}

        if provider == "anthropic":
            headers = {
                "x-api-key": payload.api_key,
                "anthropic-version": "2023-06-01",
            }
            response = requests.get(
                f"{payload.base_url.rstrip('/')}/v1/models", headers=headers, timeout=15
            )
            if response.status_code != 200:
                return {"status": "error", "message": f"anthropic error: {response.status_code}"}
            data = response.json()
            models = [item.get("id") for item in data.get("data", []) if item.get("id")]
            return {"status": "ok", "models": sorted(models)}

        if provider == "gemini":
            base_url = payload.base_url.strip() or "https://generativelanguage.googleapis.com"
            response = requests.get(
                f"{base_url.rstrip('/')}/v1/models?key={payload.api_key}", timeout=15
            )
            if response.status_code != 200:
                return {"status": "error", "message": f"gemini error: {response.status_code}"}
            data = response.json()
            models = [
                item.get("name") for item in data.get("models", []) if item.get("name")
            ]
            return {"status": "ok", "models": sorted(models)}

        if provider == "grok":
            base_url = payload.base_url.strip() or "https://api.x.ai"
            headers = {
                "Authorization": f"Bearer {payload.api_key}",
                "Content-Type": "application/json",
            }
            response = requests.get(
                f"{base_url.rstrip('/')}/v1/models", headers=headers, timeout=15
            )
            if response.status_code != 200:
                return {"status": "error", "message": f"grok error: {response.status_code}"}
            data = response.json()
            models = [item.get("id") for item in data.get("data", []) if item.get("id")]
            return {"status": "ok", "models": sorted(models)}

        if provider == "ollama":
            base_url = payload.base_url.strip()
            if not base_url:
                return {"status": "error", "message": "Missing Ollama base URL"}
            response = requests.get(
                f"{base_url.rstrip('/')}/api/tags", timeout=15
            )
            if response.status_code != 200:
                return {"status": "error", "message": f"ollama error: {response.status_code}"}
            data = response.json()
            models = [item.get("name") for item in data.get("models", []) if item.get("name")]
            return {"status": "ok", "models": sorted(models)}

        return {"status": "error", "message": f"Unknown provider: {provider}"}

    @router.get("/api/settings/models")
    def get_model_settings() -> dict:
        if not os.path.exists(config_path):
            return {"registry": [], "selected_model": ""}
        with open(config_path, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)
        return data.get("models", {"registry": [], "selected_model": ""})

    @router.post("/api/settings/models")
    def update_model_settings(payload: ModelRegistryRequest) -> dict:
        data = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        data["models"] = payload.model_dump()
        with open(config_path, "w", encoding="utf-8") as config_file:
            json.dump(data, config_file, indent=2)
        
        # If the newly selected model is Ollama, launch it in the background
        selected = payload.selected_model or ""
        if selected.startswith("ollama:"):
            providers = data.get("providers", {})
            ollama_cfg = providers.get("ollama", {})
            ollama_url = ollama_cfg.get("base_url") or "http://127.0.0.1:11434"
            threading.Thread(
                target=ensure_ollama_running,
                args=(ollama_url,),
                daemon=True,
                name="ollama-launcher-settings",
            ).start()
            _logger.info("Model changed to Ollama — auto-launch initiated")
        
        return {"status": "ok"}

    @router.get("/api/settings/providers")
    def get_provider_settings() -> dict:
        if not os.path.exists(config_path):
            return {}
        with open(config_path, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)
        return data.get("providers", {})

    @router.post("/api/settings/providers")
    def update_provider_settings(payload: ProviderSettingsRequest) -> dict:
        data = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        data["providers"] = payload.model_dump()
        with open(config_path, "w", encoding="utf-8") as config_file:
            json.dump(data, config_file, indent=2)
        return {"status": "ok"}

    @router.get("/api/settings/transcription")
    def get_transcription_settings() -> dict:
        if not os.path.exists(config_path):
            return {}
        with open(config_path, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)
        return data.get("transcription", {})

    @router.post("/api/settings/transcription")
    def update_transcription_settings(payload: TranscriptionSettingsRequest) -> dict:
        data = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        transcription = data.get("transcription", {})
        transcription["live_model_size"] = payload.live_model_size
        transcription["final_model_size"] = payload.final_model_size
        transcription["auto_transcribe"] = payload.auto_transcribe
        transcription["stream_transcribe"] = payload.stream_transcribe
        transcription["live_transcribe"] = payload.live_transcribe
        transcription["consolidation_max_duration"] = payload.consolidation_max_duration
        transcription["consolidation_max_gap"] = payload.consolidation_max_gap
        data["transcription"] = transcription
        with open(config_path, "w", encoding="utf-8") as config_file:
            json.dump(data, config_file, indent=2)
        return {"status": "ok"}

    @router.get("/api/settings/testing")
    def get_testing_settings() -> dict:
        if not os.path.exists(config_path):
            return {"audio_path": "", "audio_name": ""}
        with open(config_path, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)
        return data.get("testing", {"audio_path": "", "audio_name": ""})

    @router.post("/api/settings/testing")
    def update_testing_settings(payload: TestingSettingsRequest) -> dict:
        data = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        testing = data.get("testing", {})
        testing["audio_path"] = payload.audio_path
        testing["audio_name"] = payload.audio_name
        data["testing"] = testing
        with open(config_path, "w", encoding="utf-8") as config_file:
            json.dump(data, config_file, indent=2)
        return {"status": "ok"}

    @router.get("/api/settings/appearance")
    def get_appearance_settings() -> dict:
        if not os.path.exists(config_path):
            return {"theme": "system"}
        with open(config_path, "r", encoding="utf-8") as config_file:
            data = json.load(config_file)
        return data.get("appearance", {"theme": "system"})

    @router.post("/api/settings/appearance")
    def update_appearance_settings(payload: AppearanceSettingsRequest) -> dict:
        # Validate theme value
        valid_themes = ["light", "dark", "system"]
        theme = payload.theme if payload.theme in valid_themes else "system"
        
        data = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        appearance = data.get("appearance", {})
        appearance["theme"] = theme
        data["appearance"] = appearance
        with open(config_path, "w", encoding="utf-8") as config_file:
            json.dump(data, config_file, indent=2)
        return {"status": "ok", "theme": theme}

    return router
