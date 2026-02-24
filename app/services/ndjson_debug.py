from __future__ import annotations

import json
import logging
import time
from typing import Any


_logger = logging.getLogger("notetaker.debug")


def dbg(location: str, message: str, data: dict[str, Any], *, run_id: str, hypothesis_id: str) -> None:
    """
    Log a structured debug message to the server log (logs/server_*.log).

    IMPORTANT: Do NOT log secrets (tokens, passwords, API keys, PII).
    
    All debug logs now go through Python's standard logging to the server log.
    """
    try:
        payload = {
            "id": f"dbg_{int(time.time() * 1000)}",
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data,
            "runId": run_id,
            "hypothesisId": hypothesis_id,
        }
        _logger.info("DBG_NDJSON %s", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        pass

