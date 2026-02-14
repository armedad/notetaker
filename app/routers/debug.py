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
    llm_logger: TestLLMLogger,
    rag_metrics: TestRAGMetrics,
) -> APIRouter:
    """Create the debug API router with endpoints for observability.
    
    Args:
        llm_logger: TestLLMLogger instance for log operations
        rag_metrics: TestRAGMetrics instance for metrics operations
        
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
        _log_path = os.path.join(os.getcwd(), "logs", "debug.log")
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
    
    return router
