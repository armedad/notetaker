"""Debug API router for LLM observability endpoints.

This module provides API endpoints for accessing RAG metrics and LLM logs.
All endpoints are under /api/test/ to clearly indicate they are for
debugging/testing purposes, not production API.
"""

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.llm_logger import TestLLMLogger
from app.services.rag_metrics import TestRAGMetrics


class TestLogAllRequest(BaseModel):
    """Request body for toggling log-all setting."""
    enabled: bool


def create_test_debug_router(
    ctx,
    llm_logger: TestLLMLogger,
    rag_metrics: TestRAGMetrics,
    background_finalizer=None,
) -> APIRouter:
    """Create the debug API router with endpoints for observability.
    
    Args:
        llm_logger: TestLLMLogger instance for log operations
        rag_metrics: TestRAGMetrics instance for metrics operations
        background_finalizer: Optional BackgroundFinalizer instance for finalization controls
        
    Returns:
        FastAPI router with debug endpoints mounted
    """
    router = APIRouter(prefix="/api/test", tags=["debug"])
    
    # -------------------------------------------------------------------------
    # RAG Metrics Endpoints
    # -------------------------------------------------------------------------
    
    @router.get("/rag-metrics")
    def get_rag_metrics() -> dict:
        """Get RAG query metrics including aggregates and recent queries.
        
        Returns:
            Dict with 'aggregate' stats and 'recent' query records
        """
        # #region agent log
        import time as _time
        import json as _json
        _log_path = ctx.debug_log_path
        result = rag_metrics.test_to_dict()
        with open(_log_path, "a") as _f:
            _f.write(_json.dumps({"location":"debug.py:get_rag_metrics","message":"rag_metrics_called","data":{"total_queries": result.get("aggregate", {}).get("total_queries", 0), "recent_count": len(result.get("recent", []))},"timestamp":int(_time.time()*1000),"runId":"debug-api","hypothesisId":"H3-H4"})+"\n")
        # #endregion
        return result
    
    @router.post("/rag-metrics/reset")
    def reset_rag_metrics() -> dict:
        """Reset all RAG metrics.
        
        Returns:
            Confirmation message
        """
        rag_metrics.test_reset()
        return {"status": "ok", "message": "RAG metrics reset"}
    
    # -------------------------------------------------------------------------
    # LLM Logging Endpoints
    # -------------------------------------------------------------------------
    
    @router.get("/llm-logs")
    def list_llm_logs() -> dict:
        """List all LLM log files.
        
        Returns:
            Dict with 'logs' array containing file info
        """
        logs = llm_logger.test_list_logs()
        return {"logs": logs}
    
    @router.get("/llm-logs/{filename}")
    def get_llm_log(filename: str) -> dict:
        """Get the content of a specific LLM log file.
        
        Args:
            filename: Name of the log file (without path)
            
        Returns:
            Dict with 'filename' and 'content'
            
        Raises:
            HTTPException 404 if file not found
        """
        content = llm_logger.test_get_log(filename)
        if content is None:
            raise HTTPException(status_code=404, detail="Log file not found")
        return {"filename": filename, "content": content}
    
    @router.delete("/llm-logs")
    def clear_llm_logs() -> dict:
        """Delete all LLM log files.
        
        Returns:
            Dict with count of deleted files
        """
        count = llm_logger.test_clear_logs()
        return {"status": "ok", "deleted": count}
    
    @router.get("/llm-logging")
    def get_llm_logging_status() -> dict:
        """Get the current state of the log-all setting.
        
        Returns:
            Dict with 'enabled' boolean
        """
        return {"enabled": llm_logger.test_get_log_all()}
    
    @router.post("/llm-logging")
    def set_llm_logging(request: TestLogAllRequest) -> dict:
        """Enable or disable global LLM logging.
        
        Args:
            request: Body with 'enabled' boolean
            
        Returns:
            Confirmation with new state
        """
        llm_logger.test_set_log_all(request.enabled)
        return {"status": "ok", "enabled": request.enabled}
    
    # -------------------------------------------------------------------------
    # Submit-and-Log Prompt Endpoints
    # -------------------------------------------------------------------------
    
    @router.get("/latest-submit-log")
    def get_latest_submit_log() -> dict:
        """Return the most recent submit_*.log file path and content."""
        logs_dir = ctx.logs_dir
        if not os.path.isdir(logs_dir):
            raise HTTPException(status_code=404, detail="No submit logs found")
        
        submit_files = [
            f for f in os.listdir(logs_dir)
            if f.startswith("submit_") and f.endswith(".log")
        ]
        if not submit_files:
            raise HTTPException(status_code=404, detail="No submit logs found")
        
        latest = max(
            submit_files,
            key=lambda f: os.path.getmtime(os.path.join(logs_dir, f)),
        )
        full_path = os.path.join(logs_dir, latest)
        
        with open(full_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        
        return {"path": full_path, "filename": latest, "content": content}
    
    # -------------------------------------------------------------------------
    # Background Finalization Endpoints
    # -------------------------------------------------------------------------
    
    @router.get("/finalization-status")
    def get_finalization_status() -> dict:
        """Get the current status of the background finalization service.
        
        Returns:
            Dict with:
                - running: bool - whether the service is running
                - active: bool - whether currently processing a meeting
                - current_meeting_id: str or None
                - current_stage: str or None
                - pending_count: int - number of meetings waiting
        """
        if background_finalizer is None:
            return {
                "running": False,
                "active": False,
                "current_meeting_id": None,
                "current_stage": None,
                "pending_count": 0,
                "error": "Background finalizer not available",
            }
        return background_finalizer.get_status()
    
    @router.post("/restart-finalization")
    def restart_finalization() -> dict:
        """Wake up the background finalizer to process pending meetings.
        
        Returns:
            Dict with status and current pending count
        """
        if background_finalizer is None:
            raise HTTPException(
                status_code=503,
                detail="Background finalizer not available",
            )
        
        status = background_finalizer.get_status()
        if status.get("active"):
            return {
                "status": "already_active",
                "message": "Finalization is already in progress",
                "current_meeting_id": status.get("current_meeting_id"),
                "current_stage": status.get("current_stage"),
            }
        
        background_finalizer.wake()
        return {
            "status": "ok",
            "message": "Finalization restarted",
            "pending_count": status.get("pending_count", 0),
        }
    
    return router
