#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${PROJECT_DIR}/.notetaker.pid"
VERSION_FILE="${PROJECT_DIR}/VERSION.txt"
LAST_VERSION_FILE="${PROJECT_DIR}/.last_version"
LOGS_DIR="${PROJECT_DIR}/logs"
FORCE_RESTART=false

if [[ "${1:-}" == "--restart" ]]; then
  FORCE_RESTART=true
fi

cd "${PROJECT_DIR}"
mkdir -p "${LOGS_DIR}"

if [[ ! -f "${VERSION_FILE}" ]]; then
  echo "Missing VERSION.txt in ${PROJECT_DIR}"
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
      echo "Stopping previous server (pid ${OLD_PID}) due to deploy change"
      kill "${OLD_PID}"
      sleep 1
    fi
  fi
  echo "${CURRENT_VERSION}" > "${LAST_VERSION_FILE}"
fi

echo "Ensuring no stray notetaker processes are running"
pkill -f "uvicorn run:app" >/dev/null 2>&1 || true
pkill -f "run.py" >/dev/null 2>&1 || true

if [[ ! -f "requirements.txt" ]]; then
  echo "Missing requirements.txt in ${PROJECT_DIR}"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Please install Python 3.10+."
  exit 1
fi

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi

source ".venv/bin/activate"

pip install -r requirements.txt

LOG_FILE="${LOGS_DIR}/launcher_$(date +\"%Y-%m-%d_%H-%M-%S\").log"
echo "Starting server for ${CURRENT_VERSION} (logs: ${LOG_FILE})"

python -m uvicorn run:app --host 127.0.0.1 --port 6684 --reload --log-level debug >> "${LOG_FILE}" 2>&1 &
echo $! > "${PID_FILE}"
wait
