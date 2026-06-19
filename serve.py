#!/usr/bin/env python3
"""Notetaker server launcher (uvicorn). Use notetaker.bat / notetaker.ps1 on Windows."""

from __future__ import annotations

import os
import sys

from app.paths import ensure_install_cwd

ensure_install_cwd()

from app.cli import parse_launch_argv  # noqa: E402


def main() -> int:
    opts = parse_launch_argv()
    # Enables POST /api/local/shutdown from settings UI and capps (loopback-only).
    os.environ.setdefault("NOTETAKER_LOCAL_SHUTDOWN", "1")
    if opts.debug:
        os.environ["NOTETAKER_DEBUG"] = "1"

    import uvicorn

    mode = "debug" if opts.debug else "normal"
    print(
        f"Starting Notetaker ({mode}) at http://{opts.host}:{opts.port}/ "
        f"(install={os.getcwd()})",
        file=sys.stderr,
    )
    if opts.debug:
        print(
            "Debug mode: verbose logging and all debug flags enabled.",
            file=sys.stderr,
        )

    uvicorn.run(
        "run:app",
        host=opts.host,
        port=opts.port,
        log_level="debug" if opts.debug else "info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
