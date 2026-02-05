import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler


def _build_file_handler(log_path: str) -> RotatingFileHandler:
    formatter = logging.Formatter("[%(asctime)s] [%(name)s] %(message)s", "%H:%M:%S")
    file_handler = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=3)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    file_handler.name = "notetaker_file"
    return file_handler


def _build_stream_handler() -> logging.StreamHandler:
    formatter = logging.Formatter("[%(asctime)s] [%(name)s] %(message)s", "%H:%M:%S")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO)
    stream_handler.name = "notetaker_stream"
    return stream_handler


def _replace_handlers(logger: logging.Logger, handlers: list[logging.Handler]) -> None:
    logger.handlers = []
    for handler in handlers:
        logger.addHandler(handler)
    logger.propagate = False


def configure_logging() -> str:
    logs_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(logs_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = os.path.join(logs_dir, f"server_{timestamp}.log")

    file_handler = _build_file_handler(log_path)
    stream_handler = _build_stream_handler()

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    _replace_handlers(root_logger, [file_handler, stream_handler])

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.setLevel(logging.INFO)
        _replace_handlers(uv_logger, [file_handler, stream_handler])

    root_logger.info("Logging initialized: %s", log_path)
    return log_path
