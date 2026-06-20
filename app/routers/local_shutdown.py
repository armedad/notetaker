"""Loopback-only process exit for local dev / capps dashboard."""
from __future__ import annotations

import os
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

router = APIRouter(tags=["local"])

# Must match $RestartExitCode in notetaker.ps1 — launcher re-runs from the top on this code.
RESTART_EXIT_CODE = 42


def _require_loopback(request: Request) -> None:
    client = request.client
    host = (client.host if client else "") or ""
    if host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Local shutdown accepts loopback only.")


def _exit_process(code: int = 0) -> None:
    time.sleep(0.2)
    os._exit(code)


@router.post("/local/shutdown")
async def post_local_shutdown(request: Request, background_tasks: BackgroundTasks) -> dict[str, bool]:
    """End the notetaker server process. Loopback only; response is sent before exit."""
    _require_loopback(request)
    background_tasks.add_task(_exit_process, 0)
    return {"ok": True, "shutting_down": True}


@router.post("/local/restart")
async def post_local_restart(request: Request, background_tasks: BackgroundTasks) -> dict[str, bool]:
    """Exit with RESTART_EXIT_CODE so notetaker.ps1 re-launches from the top. Loopback only."""
    _require_loopback(request)
    background_tasks.add_task(_exit_process, RESTART_EXIT_CODE)
    return {"ok": True, "restarting": True}
