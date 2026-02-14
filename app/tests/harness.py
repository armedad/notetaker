"""Test harness orchestration."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

from app.tests.base import SuiteResult, TestSuite


class TestHarness:
    """Orchestrates test suite execution."""

    def __init__(self, logs_dir: str):
        self.logs_dir = logs_dir
        self.suites: dict[str, type[TestSuite]] = {}
        self.logger = logging.getLogger("notetaker.test.harness")
        self._register_suites()

    def _register_suites(self):
        """Register all available test suites."""
        from app.tests.suites.auto_title import AutoTitleSuite
        from app.tests.suites.smart_summary import SmartSummarySuite
        from app.tests.suites.debug_ui import DebugUISuite
        from app.tests.suites.diarization import DiarizationSuite
        from app.tests.suites.transcription_flow import TranscriptionFlowSuite
        from app.tests.suites.rag_efficiency import RAGEfficiencySuite

        self.suites["auto-title"] = AutoTitleSuite
        self.suites["smart-summary"] = SmartSummarySuite
        self.suites["debug-ui"] = DebugUISuite
        self.suites["diarization"] = DiarizationSuite
        self.suites["transcription-flow"] = TranscriptionFlowSuite
        self.suites["rag-efficiency"] = RAGEfficiencySuite

    def get_available_suites(self) -> list[dict]:
        """Return info about all available suites."""
        result = []
        for suite_id, suite_class in self.suites.items():
            suite = suite_class()
            result.append(suite.get_info())
        return result

    def _create_test_logger(self, suite_id: str) -> tuple[logging.Logger, str]:
        """Create a logger that writes to a test-specific log file."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_file = os.path.join(self.logs_dir, f"test_{suite_id}_{timestamp}.log")

        logger = logging.getLogger(f"notetaker.test.{suite_id}")
        logger.setLevel(logging.DEBUG)

        # Remove existing handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        # File handler
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("[%(asctime)s] [%(name)s] %(message)s", datefmt="%H:%M:%S")
        )
        logger.addHandler(file_handler)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(
            logging.Formatter("[%(asctime)s] [TEST] %(message)s", datefmt="%H:%M:%S")
        )
        logger.addHandler(console_handler)

        return logger, log_file

    async def run_suite(self, suite_id: str) -> dict:
        """Run a specific test suite."""
        if suite_id not in self.suites:
            return {
                "status": "error",
                "message": f"Unknown suite: {suite_id}",
                "available": list(self.suites.keys()),
            }

        logger, log_file = self._create_test_logger(suite_id)
        logger.info(f"Starting test suite: {suite_id}")
        logger.info(f"Log file: {log_file}")

        suite_class = self.suites[suite_id]
        suite = suite_class(logger=logger)

        result = await suite.run()

        # Write JSON summary to log
        logger.info("\n" + "=" * 60)
        logger.info("JSON RESULT:")
        logger.info(json.dumps(result.to_dict(), indent=2))
        logger.info("=" * 60)

        return {
            "status": "ok",
            "log_file": log_file,
            "result": result.to_dict(),
        }

    async def run_all(self) -> dict:
        """Run all test suites."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_file = os.path.join(self.logs_dir, f"test_all_{timestamp}.log")

        logger = logging.getLogger("notetaker.test.all")
        logger.setLevel(logging.DEBUG)

        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("[%(asctime)s] [%(name)s] %(message)s", datefmt="%H:%M:%S")
        )
        logger.addHandler(file_handler)

        logger.info("=" * 60)
        logger.info("RUNNING ALL TEST SUITES")
        logger.info("=" * 60)

        all_results = []
        total_passed = total_failed = total_skipped = total_error = 0

        for suite_id, suite_class in self.suites.items():
            logger.info(f"\n>>> Starting suite: {suite_id}")
            suite = suite_class(logger=logger)
            result = await suite.run()
            all_results.append(result.to_dict())

            total_passed += result.passed
            total_failed += result.failed
            total_skipped += result.skipped
            total_error += result.error

        logger.info("\n" + "=" * 60)
        logger.info("OVERALL SUMMARY")
        logger.info("=" * 60)
        logger.info(
            f"Total: {total_passed} passed, {total_failed} failed, "
            f"{total_skipped} skipped, {total_error} errors"
        )
        logger.info(f"Suites run: {len(all_results)}")

        # Write JSON summary
        logger.info("\n" + "=" * 60)
        logger.info("JSON RESULT:")
        summary = {
            "total_passed": total_passed,
            "total_failed": total_failed,
            "total_skipped": total_skipped,
            "total_error": total_error,
            "suites": all_results,
        }
        logger.info(json.dumps(summary, indent=2))
        logger.info("=" * 60)

        return {
            "status": "ok",
            "log_file": log_file,
            "total_passed": total_passed,
            "total_failed": total_failed,
            "total_skipped": total_skipped,
            "total_error": total_error,
            "suites": all_results,
        }
