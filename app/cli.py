"""Notetaker command-line options for serve.py and start scripts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from app.paths import read_port_file

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 6684
DEBUG_PORT = 6685

HELP_EPILOG = """examples:
  notetaker.bat
  notetaker.bat -debug
  python serve.py --debug
  python serve.py --help
"""


@dataclass(frozen=True)
class LaunchOptions:
    debug: bool
    host: str
    port: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notetaker",
        description="Local meeting record, transcribe, and search (FastAPI + web UI).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_EPILOG,
        add_help=False,
    )
    parser.add_argument(
        "-debug",
        "--debug",
        action="store_true",
        help=f"Run in debug mode (port {DEBUG_PORT}, verbose logging, all debug flags on).",
    )
    parser.add_argument(
        "-help",
        "--help",
        "-h",
        action="help",
        help="Show this help message and exit.",
    )
    return parser


def resolve_port(*, debug: bool = False) -> int:
    """Resolve listen port: ``.port`` file overrides defaults."""
    port = read_port_file()
    if port is not None:
        return port
    return DEBUG_PORT if debug else DEFAULT_PORT


def parse_launch_argv(argv: list[str] | None = None) -> LaunchOptions:
    args = build_parser().parse_args(argv)
    return LaunchOptions(
        debug=args.debug,
        host=DEFAULT_HOST,
        port=resolve_port(debug=args.debug),
    )
