import json
import os

import requests

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional


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
    enabled: bool
    provider: str
    model: str
    device: str
    hf_token: Optional[str] = None
    performance_level: float = 0.5


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


class TestingSettingsRequest(BaseModel):
    audio_path: str = ""
    audio_name: str = ""


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
        data = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        data["diarization"] = payload.model_dump()
        with open(config_path, "w", encoding="utf-8") as config_file:
            json.dump(data, config_file, indent=2)
        return {"status": "ok"}

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

    return router
