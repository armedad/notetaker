#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${PROJECT_DIR}/.notetaker.pid"
VERSION_FILE="${PROJECT_DIR}/VERSION.txt"
LAST_VERSION_FILE="${PROJECT_DIR}/.last_version"
LOGS_DIR="${PROJECT_DIR}/logs"
FORCE_RESTART=false
AUTO_RESTART=true

mkdir -p "${LOGS_DIR}"
LAUNCHER_LOG="${LOGS_DIR}/launcher_$(date +"%Y-%m-%d_%H-%M-%S").log"
exec > >(tee -a "${LAUNCHER_LOG}") 2>&1

log() {
  echo "[$(date +"%H:%M:%S")] [launcher] $*"
}

trap 'log "ERROR at line ${LINENO}. Exit code=$?"; exit 1' ERR

if [[ "${1:-}" == "--restart" ]]; then
  FORCE_RESTART=true
fi
if [[ "${1:-}" == "--no-restart" ]]; then
  AUTO_RESTART=false
fi

cd "${PROJECT_DIR}"

if [[ ! -f "${VERSION_FILE}" ]]; then
  log "Missing VERSION.txt in ${PROJECT_DIR}"
  exit 1
fi

CURRENT_VERSION="$(cat "${VERSION_FILE}")"
LAST_VERSION=""
if [[ -f "${LAST_VERSION_FILE}" ]]; then
  LAST_VERSION="$(cat "${LAST_VERSION_FILE}")"
fi

if [[ "${CURRENT_VERSION}" != "${LAST_VERSION}" || "${FORCE_RESTART}" == "true" ]]; then
  if [[ -f "${PID_FILE}" ]]; then
    OLD_PID="$(cat "${PID_FILE}")"
    if ps -p "${OLD_PID}" >/dev/null 2>&1; then
      log "Stopping previous server (pid ${OLD_PID}) due to deploy change"
      kill "${OLD_PID}"
      sleep 1
    fi
  fi
  echo "${CURRENT_VERSION}" > "${LAST_VERSION_FILE}"
fi

log "Ensuring no stray notetaker processes are running"
# Kill only notetaker's uvicorn process (specific port) - avoid killing other projects' run.py
pkill -f "uvicorn run:app.*--port 6684" >/dev/null 2>&1 || true

if [[ ! -f "requirements.txt" ]]; then
  log "Missing requirements.txt in ${PROJECT_DIR}"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  log "python3 not found. Please install Python 3.10+."
  exit 1
fi

log "Python version: $(python3 --version 2>&1)"

if [[ ! -d ".venv" ]]; then
  log "Creating virtualenv"
  python3 -m venv .venv
fi

source ".venv/bin/activate"

log "Installing dependencies"
pip install -r requirements.txt
log "Checking installed dependencies"
pip check || true

log "Preflight: scan for Python 3.9 union syntax"
if command -v rg >/dev/null 2>&1; then
  if rg -n "\\| None" app >/dev/null 2>&1; then
    rg -n "\\| None" app || true
    log "Detected '| None' usage; may fail under Python < 3.10"
  else
    log "No '| None' usage detected in app/"
  fi
else
  log "rg not available; skipping union syntax scan"
fi

log "Preflight: import run.py"
python - <<'PY'
import sys
try:
    import run  # noqa: F401
    print("[preflight] run import: OK")
except Exception as exc:
    print(f"[preflight] run import: FAIL: {exc}")
    sys.exit(1)
PY

log "Preflight: whisperx/torch availability"
python - <<'PY'
import sys
try:
    import torch
    print(f"[preflight] torch: {torch.__version__} cuda={torch.cuda.is_available()}")
except Exception as exc:
    print(f"[preflight] torch: FAIL: {exc}")
    sys.exit(1)
try:
    import whisperx  # noqa: F401
    print("[preflight] whisperx: OK")
except Exception as exc:
    print(f"[preflight] whisperx: FAIL: {exc}")
    sys.exit(1)
PY

cleanup_sentinels() {
  rm -f "${PROJECT_DIR}/.restart" "${PROJECT_DIR}/.exit" 2>/dev/null
}

terminate_server() {
  if [[ -f "${PID_FILE}" ]]; then
    local pid
    pid="$(cat "${PID_FILE}")"
    if [[ -n "${pid}" ]]; then
      kill "${pid}" 2>/dev/null || true
    fi
  fi
  pkill -f "uvicorn run:app" >/dev/null 2>&1 || true
}

handle_interrupt() {
  log "Interrupt received, stopping server"
  touch "${PROJECT_DIR}/.exit" 2>/dev/null || true
  terminate_server
}

start_pid_writer() {
  (
    for _ in {1..50}; do
      local pid
      pid="$(pgrep -n -f "uvicorn run:app" || true)"
      if [[ -n "${pid}" ]]; then
        echo "${pid}" > "${PID_FILE}"
        break
      fi
      sleep 0.2
    done
  ) </dev/null >/dev/null 2>&1 &
  echo $!
}

start_watcher() {
  (
    while true; do
      if [[ -f "${PROJECT_DIR}/.exit" ]]; then
        terminate_server
        break
      fi
      if [[ -f "${PROJECT_DIR}/.restart" ]]; then
        terminate_server
        break
      fi
      sleep 1
    done
  ) </dev/null >/dev/null 2>&1 &
  echo $!
}

trap cleanup_sentinels EXIT
trap handle_interrupt INT TERM

while true; do
  SERVER_LOG="${LOGS_DIR}/server_$(date +"%Y-%m-%d_%H-%M-%S").log"
  log "Starting server for ${CURRENT_VERSION}"
  log "Server log path: ${SERVER_LOG}"
  log "Launching uvicorn (foreground)"
  cleanup_sentinels
  touch "${SERVER_LOG}"
  ls -l "${SERVER_LOG}"
  pwd
  log "Python path: $(command -v python)"
  log "Python version: $(python -V 2>&1)"
  log "Uvicorn version: $(python -m uvicorn --version 2>&1)"

  WATCHER_PID="$(start_watcher)"
  PID_WRITER_PID="$(start_pid_writer)"

  set +e
  log "Uvicorn command: python -u -m uvicorn run:app --host 127.0.0.1 --port 6684 --log-level debug"
  PYTHONUNBUFFERED=1 python -u -m uvicorn run:app \
    --host 127.0.0.1 \
    --port 6684 \
    --log-level debug 2>&1 | tee -a "${SERVER_LOG}"
  EXIT_CODE=${PIPESTATUS[0]}
  set -e
  log "Uvicorn exit code: ${EXIT_CODE}"
  kill "${WATCHER_PID}" 2>/dev/null || true
  kill "${PID_WRITER_PID}" 2>/dev/null || true
  log "Server exited with code ${EXIT_CODE}"

  if [[ -f "${PROJECT_DIR}/.exit" ]]; then
    log "Server stopped by user"
    cleanup_sentinels
    exit 0
  fi

  if [[ -f "${PROJECT_DIR}/.restart" || "${EXIT_CODE}" -eq 42 ]]; then
    log "Restarting server in 2s..."
    cleanup_sentinels
    sleep 2
    continue
  fi

  if [[ "${AUTO_RESTART}" != "true" ]]; then
    break
  fi

  log "Restarting server in 2s..."
  sleep 2
done
