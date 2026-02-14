from __future__ import annotations

import json
import logging
import os
import time
from typing import Any


_DEBUG_LOG_PATH = os.path.join(os.getcwd(), "logs", "debug.log")


def dbg(location: str, message: str, data: dict[str, Any], *, run_id: str, hypothesis_id: str) -> None:
    """
    Append a single NDJSON debug line for Cursor debug-mode analysis.

    IMPORTANT: Do NOT log secrets (tokens, passwords, API keys, PII).
    """
    # #region agent log
    try:
        payload = {
            "id": f"dbg_{int(time.time() * 1000)}_{os.getpid()}",
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data,
            "runId": run_id,
            "hypothesisId": hypothesis_id,
        }
        # Mirror into the normal server log stream so logs live under ./logs/server_*.log too.
        try:
            logging.getLogger("notetaker.debug").info(
                "DBG_NDJSON %s", json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            )
        except Exception:
            pass
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion

