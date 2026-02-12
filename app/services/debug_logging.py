from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional


def dbg(
    logger: Optional[logging.Logger],
    *,
    location: str,
    message: str,
    data: dict[str, Any],
    run_id: str,
    hypothesis_id: str,
) -> None:
    """
    Debug instrumentation that writes into the normal server log file (logs/server_*.log).

    Important: do NOT include secrets in `data` (tokens, passwords, API keys).
    """
    try:
        payload = {
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data,
            "runId": run_id,
            "hypothesisId": hypothesis_id,
        }
        (logger or logging.getLogger("notetaker.debug")).info(
            "DBG %s", json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        )
    except Exception:
        pass

