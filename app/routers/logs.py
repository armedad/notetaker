import os

from fastapi import APIRouter


def create_logs_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/logs/errors")
    def error_log() -> dict:
        logs_dir = os.path.join(os.getcwd(), "logs")
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

    return router
