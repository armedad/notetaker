"""Application context — single source of truth for all runtime paths.

Every service and router receives this object instead of individual path
strings.  Properties always return the *current* value, so updating
``data_dir`` at runtime automatically propagates to every consumer without
restarting or re-constructing services.

Design note: this is deliberately a plain object (not a global/singleton)
so that a future multi-user version can give each tenant its own context.
"""

from __future__ import annotations

import os
import threading


class AppContext:
    """Holds all runtime directory paths for the application."""

    def __init__(
        self,
        *,
        cwd: str,
        data_dir: str,
        default_data_dir: str,
        config_path: str,
    ) -> None:
        self._lock = threading.Lock()
        self._cwd = cwd
        self._data_dir = data_dir
        self._default_data_dir = default_data_dir
        self._config_path = config_path
        # Static paths derived from the app package location
        self._app_dir = os.path.dirname(__file__)

    # ── data_dir (hot-swappable) ───────────────────────────────────────

    @property
    def data_dir(self) -> str:
        with self._lock:
            return self._data_dir

    @data_dir.setter
    def data_dir(self, value: str) -> None:
        with self._lock:
            self._data_dir = value

    @property
    def default_data_dir(self) -> str:
        return self._default_data_dir

    # ── Derived data paths (always follow current data_dir) ────────────

    @property
    def meetings_dir(self) -> str:
        return os.path.join(self.data_dir, "meetings")

    @property
    def recordings_dir(self) -> str:
        return os.path.join(self.data_dir, "recordings")

    @property
    def uploads_dir(self) -> str:
        return os.path.join(self.data_dir, "uploads")

    # ── Config (always in the app-level default data dir) ──────────────

    @property
    def config_path(self) -> str:
        return self._config_path

    # ── App-relative paths (never change) ──────────────────────────────

    @property
    def static_dir(self) -> str:
        return os.path.join(self._app_dir, "static")

    @property
    def prompts_dir(self) -> str:
        return os.path.join(self._app_dir, "prompts")

    # ── Logs (stay in cwd, not in data_dir) ────────────────────────────

    @property
    def logs_dir(self) -> str:
        return os.path.join(self._cwd, "logs")

    @property
    def llm_logs_dir(self) -> str:
        return os.path.join(self.logs_dir, "llm")

    @property
    def debug_log_path(self) -> str:
        return os.path.join(self.logs_dir, "debug.log")

    # ── Helpers ────────────────────────────────────────────────────────

    def ensure_dirs(self) -> None:
        """Create all required directories if they don't exist."""
        for d in (
            self.data_dir,
            self.meetings_dir,
            self.recordings_dir,
            self.uploads_dir,
            self.logs_dir,
            self.llm_logs_dir,
        ):
            os.makedirs(d, exist_ok=True)
