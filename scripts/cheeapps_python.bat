@echo off
REM Resolve Python 3.12 for CHEEAPPS venv creation. Call from install.bat after setlocal.
REM Sets CHEEAPPS_VENV_PY to "py -3.12" or "python" (when already 3.12). Exits 1 if unavailable.

set "CHEEAPPS_VENV_PY="
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "CHEEAPPS_VENV_PY=py -3.12"
  goto :cheeapps_python_ok
)
python -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) else 1)" >nul 2>&1
if not errorlevel 1 (
  set "CHEEAPPS_VENV_PY=python"
  goto :cheeapps_python_ok
)
echo error: Python 3.12 is required for CHEEAPPS venvs.
echo   Install from https://www.python.org/downloads/ or: winget install Python.Python.3.12
exit /b 1
:cheeapps_python_ok
exit /b 0
