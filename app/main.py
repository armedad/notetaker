import os
import sys

# Workaround for tqdm threading issue in huggingface_hub downloads
# This MUST be set before importing any libraries that use huggingface_hub
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

import json
import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

# Module import trace (stderr) for boot debugging.
print(f"[boot] app.main module import cwd={os.getcwd()} pid={os.getpid()}", file=sys.stderr)

# #region agent log
_DEBUG_LOG_PATH = os.path.join(os.getcwd(), "logs", "debug.log")


def _dbg_ndjson(*, location: str, message: str, data: dict, run_id: str, hypothesis_id: str) -> None:
    """Write one NDJSON debug line for this session. Best-effort only."""
    try:
        payload = {
            "id": f"log_{int(time.time() * 1000)}_{os.getpid()}",
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data,
            "runId": run_id,
            "hypothesisId": hypothesis_id,
        }
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        return


def _boot_log(location: str, message: str, data: dict, hypothesis_id: str) -> None:
    _dbg_ndjson(
        location=location,
        message=message,
        data=data,
        run_id="boot-debug",
        hypothesis_id=hypothesis_id,
    )
# #endregion

from app.routers.recording import create_recording_router
from app.routers.logs import create_logs_router
from app.routers.transcription import create_transcription_router
from app.routers.meetings import create_meetings_router
from app.routers.settings import create_settings_router
from app.routers.summarization import create_summarization_router
from app.routers.uploads import create_uploads_router
from app.routers.testing import create_testing_router
from app.routers.chat import create_chat_router
from app.routers.debug import create_test_debug_router
from app.routers.search import create_search_router
from app.services.audio_capture import AudioCaptureService
from app.services.meeting_store import MeetingStore
from app.services.summarization import SummarizationService
from app.services.llm.ollama_provider import ensure_ollama_running
from app.services.search_service import SearchService
from app.services.chat_service import ChatService
from app.services.logging_setup import configure_logging
from app.services.crash_logging import enable_crash_logging
from app.services.llm_logger import TestLLMLogger
from app.services.rag_metrics import TestRAGMetrics
from app.services.llm_instrumentation import test_install_instrumentation

def create_app() -> FastAPI:
    # #region agent log
    _boot_log(
        "app/main.py:create_app",
        "create_app enter",
        {"cwd": os.getcwd(), "pid": os.getpid()},
        "H0",
    )
    # #endregion
    configure_logging()
    logger = logging.getLogger("notetaker.boot")
    logger.info("Boot: starting create_app")
    enable_crash_logging()

    # Default to offline mode for HuggingFace — no auto-downloads.
    # The global setting in config.json can override this at boot.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    logger.info("Boot: HF_HUB_OFFLINE=%s (initial)", os.environ.get("HF_HUB_OFFLINE"))

    base_dir = os.path.dirname(__file__)
    cwd = os.getcwd()
    logger.info("Boot: base_dir=%s cwd=%s", base_dir, cwd)
    data_dir = os.path.join(cwd, "data")
    os.makedirs(data_dir, exist_ok=True)
    logger.info("Boot: data_dir=%s exists=%s", data_dir, os.path.exists(data_dir))
    config_path = os.path.join(data_dir, "config.json")
    config: dict = {}
    try:
        if os.path.exists(config_path):
            logger.info("Boot: loading config_path=%s", config_path)
            with open(config_path, "r", encoding="utf-8") as config_file:
                config = json.load(config_file)
            logger.info("Boot: config keys=%s", sorted(config.keys()))
            # #region agent log
            _boot_log(
                "app/main.py:create_app",
                "config loaded",
                {"config_path": config_path, "keys": sorted(config.keys())},
                "H1",
            )
            # #endregion
        else:
            logger.info("Boot: config_path missing=%s", config_path)
            # #region agent log
            _boot_log(
                "app/main.py:create_app",
                "config missing",
                {"config_path": config_path},
                "H1",
            )
            # #endregion
    except Exception as exc:
        # #region agent log
        _boot_log(
            "app/main.py:create_app",
            "config load failed",
            {"config_path": config_path, "exc_type": type(exc).__name__, "exc": str(exc)[:300]},
            "H1",
        )
        # #endregion
        raise

    # Honour the persisted auto-download preference
    if config.get("hf_models", {}).get("auto_download", False):
        os.environ.pop("HF_HUB_OFFLINE", None)
        logger.info("Boot: HF auto-download ON — HF_HUB_OFFLINE cleared")
    else:
        logger.info("Boot: HF auto-download OFF — HF_HUB_OFFLINE=1")

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
    meetings_dir = os.path.join(cwd, "data", "meetings")
    logger.info(
        "Boot: static_dir=%s recordings_dir=%s meetings_dir=%s",
        static_dir,
        recordings_dir,
        meetings_dir,
    )
    try:
        audio_service = AudioCaptureService(recordings_dir=recordings_dir)
        logger.info("Boot: audio_service ready")
        # #region agent log
        _boot_log(
            "app/main.py:create_app",
            "audio_service ready",
            {"recordings_dir": recordings_dir},
            "H2",
        )
        # #endregion
    except Exception as exc:
        # #region agent log
        _boot_log(
            "app/main.py:create_app",
            "audio_service failed",
            {"recordings_dir": recordings_dir, "exc_type": type(exc).__name__, "exc": str(exc)[:300]},
            "H2",
        )
        # #endregion
        raise
    try:
        meeting_store = MeetingStore(meetings_dir=meetings_dir)
        logger.info("Boot: meeting_store ready")
        # #region agent log
        _boot_log(
            "app/main.py:create_app",
            "meeting_store ready",
            {"meetings_dir": meetings_dir},
            "H3",
        )
        # #endregion
    except Exception as exc:
        # #region agent log
        _boot_log(
            "app/main.py:create_app",
            "meeting_store failed",
            {"meetings_dir": meetings_dir, "exc_type": type(exc).__name__, "exc": str(exc)[:300]},
            "H3",
        )
        # #endregion
        raise
    try:
        # SummarizationService reads config dynamically to use the user's selected model
        summarization_service = SummarizationService(config_path)
        logger.info("Boot: summarization_service ready")
        # #region agent log
        _boot_log(
            "app/main.py:create_app",
            "summarization_service ready",
            {"config_path": config_path},
            "H4",
        )
        # #endregion
        # If selected model is Ollama, launch it in the background
        try:
            provider_name, _ = summarization_service._get_selected_model()
            if provider_name == "ollama":
                provider_cfg = summarization_service._get_provider_config("ollama")
                ollama_url = provider_cfg.get("base_url") or "http://127.0.0.1:11434"
                import threading
                threading.Thread(
                    target=ensure_ollama_running,
                    args=(ollama_url,),
                    daemon=True,
                    name="ollama-launcher",
                ).start()
                logger.info("Boot: Ollama auto-launch initiated in background")
        except Exception:
            pass  # No model selected yet or config incomplete — skip
    except Exception as exc:
        # #region agent log
        _boot_log(
            "app/main.py:create_app",
            "summarization_service failed",
            {"config_path": config_path, "exc_type": type(exc).__name__, "exc": str(exc)[:300]},
            "H4",
        )
        # #endregion
        raise
    try:
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
                recordings_dir,
            )
        )
        logger.info("Boot: transcription router mounted")
        app.include_router(create_meetings_router(meeting_store, summarization_service, config_path))
        logger.info("Boot: meetings router mounted")
        app.include_router(create_summarization_router(meeting_store, summarization_service))
        logger.info("Boot: summarization router mounted")
        # Chat service and router
        search_service = SearchService(meeting_store)
        chat_service = ChatService(meeting_store, summarization_service, search_service)
        app.include_router(create_chat_router(chat_service, meeting_store))
        logger.info("Boot: chat router mounted")
        
        # Search router
        app.include_router(create_search_router(search_service))
        logger.info("Boot: search router mounted")
        
        # LLM observability instrumentation (test/debug infrastructure)
        llm_logs_dir = os.path.join(cwd, "logs", "llm")
        os.makedirs(llm_logs_dir, exist_ok=True)
        test_llm_logger = TestLLMLogger(llm_logs_dir)
        test_rag_metrics = TestRAGMetrics()
        # #region agent log
        _boot_log("app/main.py:create_app", "instrumentation_start", {"llm_logs_dir": llm_logs_dir}, "H1-H2")
        # #endregion
        try:
            test_install_instrumentation(
                meeting_store=meeting_store,
                search_service=search_service,
                summarization_service=summarization_service,
                chat_service=chat_service,
                llm_logger=test_llm_logger,
                rag_metrics=test_rag_metrics,
            )
            # #region agent log
            _boot_log("app/main.py:create_app", "instrumentation_ok", {}, "H2")
            # #endregion
        except Exception as inst_exc:
            # #region agent log
            _boot_log("app/main.py:create_app", "instrumentation_failed", {"error": str(inst_exc)[:300]}, "H2")
            # #endregion
            raise
        debug_router = create_test_debug_router(test_llm_logger, test_rag_metrics)
        app.include_router(debug_router)
        # #region agent log
        _boot_log("app/main.py:create_app", "debug_router_mounted", {"router_routes": [r.path for r in debug_router.routes]}, "H1")
        # #endregion
        logger.info("Boot: test debug router mounted (LLM observability)")
        app.include_router(create_settings_router(config_path))
        logger.info("Boot: settings router mounted")
        app.include_router(
            create_uploads_router(
                config_path, os.path.join(cwd, "data", "uploads")
            )
        )
        logger.info("Boot: uploads router mounted")
        # #region agent log
        _boot_log(
            "app/main.py:create_app",
            "routers mounted",
            {"uploads_dir": os.path.join(cwd, "data", "uploads")},
            "H5",
        )
        # #endregion
    except Exception as exc:
        # #region agent log
        _boot_log(
            "app/main.py:create_app",
            "router mount failed",
            {"exc_type": type(exc).__name__, "exc": str(exc)[:300]},
            "H5",
        )
        # #endregion
        raise

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
