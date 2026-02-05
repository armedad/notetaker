import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers.recording import create_recording_router
from app.routers.logs import create_logs_router
from app.services.audio_capture import AudioCaptureService
from app.services.logging_setup import configure_logging
from app.services.crash_logging import enable_crash_logging

def create_app() -> FastAPI:
    configure_logging()
    enable_crash_logging()
    base_dir = os.path.dirname(__file__)
    version_path = os.path.join(os.path.dirname(base_dir), "VERSION.txt")
    version = "v0.0.0.0"
    if os.path.exists(version_path):
        with open(version_path, "r", encoding="utf-8") as version_file:
            version = version_file.read().strip() or version
    app = FastAPI(title="Notetaker", version="0.1.0")
    app.state.version = version
    static_dir = os.path.join(base_dir, "static")
    recordings_dir = os.path.join(os.getcwd(), "data", "recordings")
    audio_service = AudioCaptureService(recordings_dir=recordings_dir)
    app.include_router(create_recording_router(audio_service))
    app.include_router(create_logs_router())

    @app.get("/")
    def root() -> dict:
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "Notetaker API running", "version": app.state.version}

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": app.state.version}

    if os.path.exists(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    return app
