#!/usr/bin/env bash
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR="${HOME}/projects/notetaker"
VERSION_FILE="${SRC_DIR}/VERSION.txt"

if [[ ! -f "${VERSION_FILE}" ]]; then
  echo "Missing VERSION.txt in ${SRC_DIR}"
  exit 1
fi

if [[ "${SRC_DIR}" == "${DEST_DIR}" ]]; then
  echo "Refusing to deploy: SRC_DIR and DEST_DIR are the same (${SRC_DIR})"
  exit 1
fi

if [[ "${SRC_DIR}" != */coding/notetaker ]]; then
  echo "Refusing to deploy: SRC_DIR must be .../coding/notetaker (got ${SRC_DIR})"
  exit 1
fi

VERSION_RAW="$(cat "${VERSION_FILE}")"
if [[ ! "${VERSION_RAW}" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
  echo "Invalid version format in VERSION.txt: ${VERSION_RAW}"
  exit 1
fi

MAJOR="${BASH_REMATCH[1]}"
MINOR="${BASH_REMATCH[2]}"
PATCH="${BASH_REMATCH[3]}"
BUILD="${BASH_REMATCH[4]}"
NEXT_BUILD="$((BUILD + 1))"
NEXT_VERSION="v${MAJOR}.${MINOR}.${PATCH}.${NEXT_BUILD}"

echo "${NEXT_VERSION}" > "${VERSION_FILE}"
echo "Version bumped to ${NEXT_VERSION}"

mkdir -p "${DEST_DIR}"

# Remove stale .git if present — rsync --delete won't touch excluded paths
rm -rf "${DEST_DIR}/.git"

rsync -av --delete \
  --exclude ".git/" \
  --exclude "__pycache__/" \
  --exclude "*.pyc" \
  --exclude ".venv/" \
  --exclude "venv/" \
  --exclude "data/" \
  --exclude "logs/" \
  "${SRC_DIR}/" "${DEST_DIR}/"

# Copy static data files (not user data) to deployed data folder
mkdir -p "${DEST_DIR}/data"
cp "${SRC_DIR}/data/whisper_models.json" "${DEST_DIR}/data/" 2>/dev/null || true

echo "Deployed to ${DEST_DIR}"
