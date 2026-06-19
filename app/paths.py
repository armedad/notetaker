"""Install-relative paths — all runtime files resolve from the app install root."""

from __future__ import annotations

import os

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_INSTALL_ROOT = os.path.dirname(_APP_DIR)
_install_root: str | None = None


def resolve_install_root() -> str:
    """Return the notetaker install directory (parent of ``app/``)."""
    global _install_root
    if _install_root is not None:
        return _install_root
    override = os.environ.get("NOTETAKER_INSTALL_DIR", "").strip()
    if override:
        _install_root = os.path.abspath(override)
    else:
        _install_root = _DEFAULT_INSTALL_ROOT
    return _install_root


def set_install_root(path: str) -> None:
    global _install_root
    _install_root = os.path.abspath(path)


def ensure_install_cwd() -> str:
    """Pin process cwd to the install root (isolates prod vs other checkouts)."""
    root = resolve_install_root()
    os.chdir(root)
    return root


def default_data_dir() -> str:
    return os.path.join(resolve_install_root(), "data")


def default_config_path() -> str:
    return os.path.join(default_data_dir(), "config.json")


def logs_dir() -> str:
    return os.path.join(resolve_install_root(), "logs")


def llm_logs_dir() -> str:
    return os.path.join(logs_dir(), "llm")


def debug_log_path() -> str:
    return os.path.join(logs_dir(), "debug.log")


def port_file_path(install_root: str | None = None) -> str:
    """Path to optional ``.port`` file in the install root."""
    return os.path.join(install_root or resolve_install_root(), ".port")


def read_port_file(install_root: str | None = None) -> int | None:
    """Return port from ``.port`` if present and valid, else ``None``."""
    path = port_file_path(install_root)
    try:
        with open(path, encoding="utf-8") as port_file:
            text = port_file.read().strip()
        if not text:
            return None
        port = int(text.split()[0])
        if 1 <= port <= 65535:
            return port
    except (OSError, ValueError):
        return None
    return None
