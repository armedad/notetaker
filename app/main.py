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

from app.context import AppContext
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
from app.services.background_finalizer import BackgroundFinalizer
from app.services.diarization import DiarizationService, parse_diarization_config

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

    default_data_dir = os.path.join(cwd, "data")
    os.makedirs(default_data_dir, exist_ok=True)
    # Config always lives in the app-level data dir regardless of custom data_dir
    config_path = os.path.join(default_data_dir, "config.json")
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

    # Resolve data directory: use custom path from config if valid, else default
    custom_data_dir = config.get("data_dir", "")
    if custom_data_dir and os.path.isdir(custom_data_dir) and os.access(custom_data_dir, os.W_OK):
        data_dir = custom_data_dir
        logger.info("Boot: using custom data_dir=%s", data_dir)
    else:
        data_dir = default_data_dir
        if custom_data_dir:
            logger.warning(
                "Boot: custom data_dir=%s is invalid or not writable, falling back to %s",
                custom_data_dir, data_dir,
            )
        else:
            logger.info("Boot: using default data_dir=%s", data_dir)

    ctx = AppContext(
        cwd=cwd,
        data_dir=data_dir,
        default_data_dir=default_data_dir,
        config_path=config_path,
    )
    ctx.ensure_dirs()
    logger.info("Boot: AppContext ready data_dir=%s", ctx.data_dir)

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
    app.state.ctx = ctx
    logger.info(
        "Boot: static_dir=%s recordings_dir=%s meetings_dir=%s",
        ctx.static_dir,
        ctx.recordings_dir,
        ctx.meetings_dir,
    )
    try:
        audio_service = AudioCaptureService(ctx)
        logger.info("Boot: audio_service ready")
    except Exception as exc:
        _boot_log(
            "app/main.py:create_app",
            "audio_service failed",
            {"exc_type": type(exc).__name__, "exc": str(exc)[:300]},
            "H2",
        )
        raise
    try:
        meeting_store = MeetingStore(ctx)
        logger.info("Boot: meeting_store ready")
        meeting_store.regenerate_folder_docs()
        logger.info("Boot: folder docs regenerated")
    except Exception as exc:
        _boot_log(
            "app/main.py:create_app",
            "meeting_store failed",
            {"exc_type": type(exc).__name__, "exc": str(exc)[:300]},
            "H3",
        )
        raise
    try:
        summarization_service = SummarizationService(ctx)
        logger.info("Boot: summarization_service ready")
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
            pass
    except Exception as exc:
        _boot_log(
            "app/main.py:create_app",
            "summarization_service failed",
            {"exc_type": type(exc).__name__, "exc": str(exc)[:300]},
            "H4",
        )
        raise
    try:
        app.include_router(
            create_recording_router(audio_service, meeting_store, summarization_service, ctx)
        )
        logger.info("Boot: recording router mounted")
        app.include_router(create_logs_router(ctx))
        logger.info("Boot: logs router mounted")
        app.include_router(
            create_transcription_router(config, audio_service, meeting_store, summarization_service, ctx)
        )
        logger.info("Boot: transcription router mounted")
        app.include_router(create_meetings_router(meeting_store, summarization_service, ctx))
        logger.info("Boot: meetings router mounted")
        app.include_router(create_summarization_router(meeting_store, summarization_service))
        logger.info("Boot: summarization router mounted")
        search_service = SearchService(meeting_store)
        chat_service = ChatService(ctx, meeting_store, summarization_service, search_service)
        app.include_router(create_chat_router(chat_service, meeting_store))
        logger.info("Boot: chat router mounted")
        app.include_router(create_search_router(search_service))
        logger.info("Boot: search router mounted")

        test_llm_logger = TestLLMLogger(ctx)
        test_rag_metrics = TestRAGMetrics()
        try:
            test_install_instrumentation(
                meeting_store=meeting_store,
                search_service=search_service,
                summarization_service=summarization_service,
                chat_service=chat_service,
                llm_logger=test_llm_logger,
                rag_metrics=test_rag_metrics,
            )
        except Exception as inst_exc:
            _boot_log("app/main.py:create_app", "instrumentation_failed", {"error": str(inst_exc)[:300]}, "H2")
            raise
        # Start background finalizer for meetings with incomplete finalization
        background_finalizer = None
        try:
            diarization_config = config.get("diarization", {})
            _, batch_diar_cfg = parse_diarization_config(diarization_config)
            diarization_service = DiarizationService(batch_diar_cfg)
            
            background_finalizer = BackgroundFinalizer(
                meeting_store=meeting_store,
                summarization_service=summarization_service,
                diarization_service=diarization_service,
            )
            background_finalizer.start()
            app.state.background_finalizer = background_finalizer
            logger.info("Boot: BackgroundFinalizer started")
        except Exception as exc:
            logger.warning("Boot: BackgroundFinalizer failed to start: %s", exc)
            _boot_log(
                "app/main.py:create_app",
                "background_finalizer_failed",
                {"exc_type": type(exc).__name__, "exc": str(exc)[:300]},
                "H6",
            )
        
        debug_router = create_test_debug_router(ctx, test_llm_logger, test_rag_metrics, background_finalizer)
        app.include_router(debug_router)
        logger.info("Boot: test debug router mounted (LLM observability)")
        app.include_router(create_settings_router(ctx))
        logger.info("Boot: settings router mounted")
        app.include_router(create_uploads_router(ctx))
        logger.info("Boot: uploads router mounted")
    except Exception as exc:
        _boot_log(
            "app/main.py:create_app",
            "router mount failed",
            {"exc_type": type(exc).__name__, "exc": str(exc)[:300]},
            "H5",
        )
        raise

    app.include_router(create_testing_router(ctx))
    logger.info("Boot: testing router mounted")

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
        index_path = os.path.join(ctx.static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "Notetaker API running", "version": app.state.version}

    @app.get("/meeting")
    def meeting_view() -> dict:
        page_path = os.path.join(ctx.static_dir, "meeting.html")
        if os.path.exists(page_path):
            return FileResponse(page_path)
        return {"message": "Meeting view not found", "version": app.state.version}

    @app.get("/settings")
    def settings_view() -> dict:
        page_path = os.path.join(ctx.static_dir, "settings.html")
        if os.path.exists(page_path):
            return FileResponse(page_path)
        return {"message": "Settings view not found", "version": app.state.version}

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": app.state.version}

    if os.path.exists(ctx.static_dir):
        app.mount("/static", StaticFiles(directory=ctx.static_dir), name="static")
        logger.info("Boot: static mounted at /static")
    else:
        logger.warning("Boot: static directory missing=%s", ctx.static_dir)

    logger.info("Boot: create_app complete")
    return app
