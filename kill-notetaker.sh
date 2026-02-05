#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Stopping any running notetaker processes..."
PIDS=""
PIDS="${PIDS} $(lsof -ti :6684 2>/dev/null || true)"
PIDS="${PIDS} $(pgrep -f \"uvicorn run:app\" || true)"
PIDS="${PIDS} $(pgrep -f \"run.py\" || true)"

PIDS="$(echo "${PIDS}" | tr ' ' '\n' | awk 'NF' | sort -u | tr '\n' ' ')"

if [[ -n "${PIDS// }" ]]; then
  echo "Killing PIDs: ${PIDS}"
  kill ${PIDS} >/dev/null 2>&1 || true
  sleep 1
  kill -9 ${PIDS} >/dev/null 2>&1 || true
else
  echo "No matching processes found."
fi

PID_FILE="${PROJECT_DIR}/.notetaker.pid"
if [[ -f "${PID_FILE}" ]]; then
  OLD_PID="$(cat "${PID_FILE}")"
  if ps -p "${OLD_PID}" >/dev/null 2>&1; then
    kill "${OLD_PID}" >/dev/null 2>&1 || true
  fi
  rm -f "${PID_FILE}"
fi

if lsof -i :6684 >/dev/null 2>&1; then
  echo "Port 6684 is still in use. Listing processes:"
  lsof -i :6684
  exit 1
fi

echo "Notetaker processes stopped."
