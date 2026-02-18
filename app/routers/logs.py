import logging
import os
from datetime import datetime

from pydantic import BaseModel

from fastapi import APIRouter


def create_logs_router(ctx) -> APIRouter:
    router = APIRouter()
    logger = logging.getLogger("notetaker.client")
    logger.setLevel(logging.DEBUG)

    class ClientLogRequest(BaseModel):
        level: str = "error"
        message: str
        context: dict = {}

    @router.get("/api/logs/errors")
    def error_log() -> dict:
        logs_dir = ctx.logs_dir
        if not os.path.isdir(logs_dir):
            return {"lines": []}

        log_files = [
            os.path.join(logs_dir, name)
            for name in os.listdir(logs_dir)
            if name.startswith("server_") and name.endswith(".log")
        ]
        if not log_files:
            return {"lines": []}

        latest = max(log_files, key=os.path.getmtime)
        try:
            with open(latest, "r", encoding="utf-8") as log_file:
                lines = log_file.readlines()
        except OSError:
            return {"lines": []}

        error_lines: list[str] = []
        for line in lines:
            normalized = line.lower()
            if "error" in normalized or "exception" in normalized or "traceback" in normalized:
                error_lines.append(line.rstrip("\n"))

        return {"lines": error_lines[-200:]}

    @router.post("/api/logs/client")
    def client_log(payload: ClientLogRequest) -> dict:
        level = payload.level.lower()
        timestamp = datetime.now().strftime("%H:%M:%S")
        message = f"[{timestamp}] [client] {payload.message}"
        if payload.context:
            message = f"{message} | context={payload.context}"
        if level == "warning":
            logger.warning(message)
        elif level == "info":
            logger.info(message)
        else:
            logger.error(message)
        return {"status": "ok"}

    return router
