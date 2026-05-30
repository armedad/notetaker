#!/usr/bin/env bash
# Resolve Python 3.12 for CHEEAPPS shared venv creation. Source from install scripts:
#   source "$(dirname "$0")/../scripts/cheeapps_python.sh"  # adjust relative path
#   cheeapps_resolve_python
#   "$CHEEAPPS_PY" -m venv "$VENV_DIR"

cheeapps_resolve_python() {
  CHEEAPPS_PY=""
  if command -v python3.12 >/dev/null 2>&1; then
    CHEEAPPS_PY=python3.12
  elif command -v python3 >/dev/null 2>&1; then
    local ver
    ver="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if [[ "$ver" == "3.12" ]]; then
      CHEEAPPS_PY=python3
    fi
  fi
  if [[ -z "$CHEEAPPS_PY" ]]; then
    echo "error: Python 3.12 is required for CHEEAPPS venvs." >&2
    echo "  macOS: brew install python@3.12" >&2
    echo "  Windows: py -3.12 or install from https://www.python.org/downloads/" >&2
    return 1
  fi
  export CHEEAPPS_PY
}

# Warn when reusing an existing venv built with another Python minor version.
cheeapps_warn_venv_python() {
  local venv_dir="$1"
  local cfg="$venv_dir/pyvenv.cfg"
  [[ -f "$cfg" ]] || return 0
  local venv_ver
  venv_ver="$(grep -E '^version' "$cfg" | sed 's/version = //' | cut -d. -f1,2)"
  local want_ver
  want_ver="$("$CHEEAPPS_PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [[ -n "$venv_ver" && "$venv_ver" != "$want_ver" ]]; then
    echo "warning: existing venv is Python $venv_ver; CHEEAPPS stack targets 3.12." >&2
    echo "  Recreate: remove venv and re-run install, or ./install.sh --recreate-venv where supported." >&2
  fi
}
