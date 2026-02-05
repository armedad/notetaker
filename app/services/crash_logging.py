import faulthandler
import os
from typing import Optional


_crash_file_handle: Optional[object] = None


def enable_crash_logging() -> None:
    global _crash_file_handle
    logs_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    crash_log_path = os.path.join(logs_dir, "crash.log")

    _crash_file_handle = open(crash_log_path, "a", encoding="utf-8")
    faulthandler.enable(file=_crash_file_handle, all_threads=True)
