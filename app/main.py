import os
import sys

# Workaround for tqdm threading issue in huggingface_hub downloads
# This MUST be set before importing any libraries that use huggingface_hub
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

import json
import logging

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

# Module import trace (stderr) for boot debugging.
print(f"[boot] app.main module import cwd={os.getcwd()} pid={os.getpid()}", file=sys.stderr)

from app.routers.recording import create_recording_router
from app.routers.logs import create_logs_router
from app.routers.transcription import create_transcription_router
from app.routers.meetings import create_meetings_router
from app.routers.settings import create_settings_router
from app.routers.summarization import create_summarization_router
from app.routers.uploads import create_uploads_router
from app.routers.testing import create_testing_router
from app.services.audio_capture import AudioCaptureService
from app.services.meeting_store import MeetingStore
from app.services.summarization import SummarizationConfig, SummarizationService
from app.services.logging_setup import configure_logging
from app.services.crash_logging import enable_crash_logging

def create_app() -> FastAPI:
    configure_logging()
    logger = logging.getLogger("notetaker.boot")
    logger.info("Boot: starting create_app")
    enable_crash_logging()
    base_dir = os.path.dirname(__file__)
    cwd = os.getcwd()
    logger.info("Boot: base_dir=%s cwd=%s", base_dir, cwd)
    data_dir = os.path.join(cwd, "data")
    os.makedirs(data_dir, exist_ok=True)
    logger.info("Boot: data_dir=%s exists=%s", data_dir, os.path.exists(data_dir))
    config_path = os.path.join(data_dir, "config.json")
    config: dict = {}
    if os.path.exists(config_path):
        logger.info("Boot: loading config_path=%s", config_path)
        with open(config_path, "r", encoding="utf-8") as config_file:
            config = json.load(config_file)
        logger.info("Boot: config keys=%s", sorted(config.keys()))
    else:
        logger.info("Boot: config_path missing=%s", config_path)
    version_path = os.path.join(os.path.dirname(base_dir), "VERSION.txt")
    version = "v0.0.0.0"
    if os.path.exists(version_path):
        with open(version_path, "r", encoding="utf-8") as version_file:
            version = version_file.read().strip() or version
    logger.info("Boot: version_path=%s version=%s", version_path, version)
    app = FastAPI(title="Notetaker", version="0.1.0")
    app.state.version = version
    static_dir = os.path.join(base_dir, "static")
    recordings_dir = os.path.join(cwd, "data", "recordings")
    meetings_path = os.path.join(cwd, "data", "meetings.json")
    logger.info(
        "Boot: static_dir=%s recordings_dir=%s meetings_path=%s",
        static_dir,
        recordings_dir,
        meetings_path,
    )
    audio_service = AudioCaptureService(recordings_dir=recordings_dir)
    logger.info("Boot: audio_service ready")
    meeting_store = MeetingStore(path=meetings_path)
    logger.info("Boot: meeting_store ready")
    summarization_config = config.get("summarization", {})
    logger.info("Boot: summarization_config keys=%s", sorted(summarization_config.keys()))
    summarization_service = SummarizationService(
        SummarizationConfig(
            provider=summarization_config.get("provider", "ollama"),
            ollama_base_url=summarization_config.get(
                "ollama_base_url", "http://127.0.0.1:11434"
            ),
            ollama_model=summarization_config.get("ollama_model", "llama3.1"),
            openai_api_key=summarization_config.get("openai_api_key", ""),
            openai_model=summarization_config.get("openai_model", "gpt-4o-mini"),
            anthropic_api_key=summarization_config.get("anthropic_api_key", ""),
            anthropic_model=summarization_config.get(
                "anthropic_model", "claude-3-5-sonnet-20241022"
            ),
            lmstudio_base_url=summarization_config.get(
                "lmstudio_base_url", "http://127.0.0.1:1234"
            ),
            lmstudio_model=summarization_config.get("lmstudio_model", ""),
        )
    )
    logger.info("Boot: summarization_service ready")
    app.include_router(
        create_recording_router(
            audio_service, meeting_store, summarization_service, config_path
        )
    )
    logger.info("Boot: recording router mounted")
    app.include_router(create_logs_router())
    logger.info("Boot: logs router mounted")
    app.include_router(
        create_transcription_router(
            config,
            audio_service,
            meeting_store,
            summarization_service,
        )
    )
    logger.info("Boot: transcription router mounted")
    app.include_router(create_meetings_router(meeting_store, summarization_service))
    logger.info("Boot: meetings router mounted")
    app.include_router(create_summarization_router(meeting_store, summarization_service))
    logger.info("Boot: summarization router mounted")
    app.include_router(create_settings_router(config_path))
    logger.info("Boot: settings router mounted")
    app.include_router(
        create_uploads_router(
            config_path, os.path.join(cwd, "data", "uploads")
        )
    )
    logger.info("Boot: uploads router mounted")

    logs_dir = os.path.join(cwd, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    app.include_router(create_testing_router(logs_dir, static_dir))
    logger.info("Boot: testing router mounted")

    # Middleware to prevent caching of HTML and JS files
    class NoCacheMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            path = request.url.path
            if path.endswith(('.html', '.js', '.css')) or path in ('/', '/meeting', '/settings', '/test-harness'):
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
            return response
    
    app.add_middleware(NoCacheMiddleware)
    logger.info("Boot: no-cache middleware added")

    @app.get("/")
    def root() -> dict:
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "Notetaker API running", "version": app.state.version}

    @app.get("/meeting")
    def meeting_view() -> dict:
        page_path = os.path.join(static_dir, "meeting.html")
        if os.path.exists(page_path):
            return FileResponse(page_path)
        return {"message": "Meeting view not found", "version": app.state.version}

    @app.get("/settings")
    def settings_view() -> dict:
        page_path = os.path.join(static_dir, "settings.html")
        if os.path.exists(page_path):
            return FileResponse(page_path)
        return {"message": "Settings view not found", "version": app.state.version}

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": app.state.version}

    if os.path.exists(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
        logger.info("Boot: static mounted at /static")
    else:
        logger.warning("Boot: static directory missing=%s", static_dir)

    logger.info("Boot: create_app complete")
    return app
