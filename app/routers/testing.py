"""Test harness API router."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, FileResponse

from app.tests.harness import TestHarness


def create_testing_router(ctx) -> APIRouter:
    """Create the testing router with configured harness."""
    router = APIRouter(tags=["testing"])
    logger = logging.getLogger("notetaker.api.testing")
    harness = TestHarness(ctx.logs_dir)

    @router.get("/test", response_class=HTMLResponse)
    async def test_page():
        """Serve the test harness page."""
        return FileResponse(f"{ctx.static_dir}/test.html")

    @router.get("/api/test/suites")
    async def list_suites():
        """List all available test suites."""
        return {
            "status": "ok",
            "suites": harness.get_available_suites(),
        }

    @router.post("/api/test/run")
    async def run_tests(
        suite: Optional[str] = Query(None, description="Suite ID to run"),
        all_suites: bool = Query(False, alias="all", description="Run all suites"),
    ):
        """Run test suite(s)."""
        logger.info(f"Test run requested: suite={suite}, all={all_suites}")

        if all_suites:
            result = await harness.run_all()
            return result
        elif suite:
            result = await harness.run_suite(suite)
            return result
        else:
            return {
                "status": "error",
                "message": "Specify ?suite=<suite_id> or ?all=true",
                "available_suites": [s["suite_id"] for s in harness.get_available_suites()],
            }

    @router.get("/api/test/run")
    async def run_tests_get(
        suite: Optional[str] = Query(None, description="Suite ID to run"),
        all_suites: bool = Query(False, alias="all", description="Run all suites"),
    ):
        """Run test suite(s) via GET (for browser URL triggering)."""
        logger.info(f"Test run requested (GET): suite={suite}, all={all_suites}")

        if all_suites:
            result = await harness.run_all()
            return result
        elif suite:
            result = await harness.run_suite(suite)
            return result
        else:
            return {
                "status": "error",
                "message": "Specify ?suite=<suite_id> or ?all=true",
                "available_suites": [s["suite_id"] for s in harness.get_available_suites()],
            }

    return router
