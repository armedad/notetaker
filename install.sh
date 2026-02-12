#!/usr/bin/env bash
set -euo pipefail

# Notetaker Installation Script
# Full installation of all components needed to run Notetaker

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() {
  echo "[$(date +"%H:%M:%S")] [install] $*"
}

warn() {
  echo "[$(date +"%H:%M:%S")] [install] WARNING: $*"
}

error() {
  echo "[$(date +"%H:%M:%S")] [install] ERROR: $*"
}

log "============================================"
log "Notetaker Installation Script"
log "============================================"
log "Project directory: ${PROJECT_DIR}"
log ""

# ============================================================================
# System Prerequisites (macOS)
# ============================================================================
if [[ "$(uname)" == "Darwin" ]]; then
  log "Checking macOS prerequisites..."
  
  # Check for Homebrew
  if ! command -v brew >/dev/null 2>&1; then
    log "Homebrew not found. Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  else
    log "Homebrew: installed"
  fi
  
  # Install ffmpeg (needed for audio processing)
  if ! command -v ffmpeg >/dev/null 2>&1; then
    log "Installing ffmpeg..."
    brew install ffmpeg
  else
    log "ffmpeg: installed ($(ffmpeg -version 2>&1 | head -1))"
  fi
  
  # Install portaudio (needed by sounddevice for microphone access)
  if ! brew list portaudio >/dev/null 2>&1; then
    log "Installing portaudio..."
    brew install portaudio
  else
    log "portaudio: installed"
  fi
fi

# ============================================================================
# Python Check
# ============================================================================
log ""
log "Checking Python..."

if ! command -v python3 >/dev/null 2>&1; then
  error "python3 not found."
  log "Please install Python 3.10+ via:"
  log "  brew install python@3.11"
  log "  or download from https://www.python.org/downloads/"
  exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "${PYTHON_VERSION}" | cut -d. -f1)
PYTHON_MINOR=$(echo "${PYTHON_VERSION}" | cut -d. -f2)

log "Python version: ${PYTHON_VERSION}"

if [[ "${PYTHON_MAJOR}" -lt 3 ]] || [[ "${PYTHON_MAJOR}" -eq 3 && "${PYTHON_MINOR}" -lt 10 ]]; then
  warn "Python 3.10+ recommended. Current: ${PYTHON_VERSION}"
  warn "Some features may not work correctly."
  log "To install Python 3.11: brew install python@3.11"
fi

# ============================================================================
# Virtual Environment & Python Dependencies
# ============================================================================
log ""
log "Setting up Python environment..."

cd "${PROJECT_DIR}"

if [[ ! -d ".venv" ]]; then
  log "Creating virtual environment..."
  python3 -m venv .venv
else
  log "Virtual environment: exists"
fi

source ".venv/bin/activate"

# Upgrade pip
log "Upgrading pip..."
pip install --upgrade pip --quiet

if [[ -f "requirements.txt" ]]; then
  log "Installing Python dependencies (this may take a few minutes)..."
  pip install -r requirements.txt
  log "Python dependencies: installed"
else
  error "requirements.txt not found!"
  exit 1
fi

# ============================================================================
# Create Required Directories
# ============================================================================
log ""
log "Creating required directories..."

mkdir -p "${PROJECT_DIR}/data/meetings"
mkdir -p "${PROJECT_DIR}/data/recordings"
mkdir -p "${PROJECT_DIR}/logs"
log "Directories: created"

# ============================================================================
# Create Default Config if Missing
# ============================================================================
log ""
log "Checking configuration..."

if [[ ! -f "${PROJECT_DIR}/config.json" ]]; then
  log "Creating default config.json..."
  cat > "${PROJECT_DIR}/config.json" << 'CONFIGEOF'
{
  "server": {
    "host": "127.0.0.1",
    "port": 6684
  },
  "transcription": {
    "provider": "faster-whisper",
    "model_size": "base",
    "device": "cpu",
    "compute_type": "int8",
    "live_chunk_seconds": 5.0,
    "live_model_size": "base",
    "live_device": "cpu",
    "live_compute_type": "int8",
    "final_model_size": "medium",
    "final_device": "cpu",
    "final_compute_type": "int8"
  },
  "diarization": {
    "enabled": false,
    "provider": "pyannote",
    "model": "pyannote/speaker-diarization-3.1",
    "device": "cpu",
    "hf_token": ""
  },
  "models": {
    "registry": [],
    "selected_model": ""
  },
  "providers": {
    "openai": {
      "enabled": false,
      "api_key": "",
      "base_url": "https://api.openai.com"
    },
    "anthropic": {
      "enabled": false,
      "api_key": "",
      "base_url": "https://api.anthropic.com"
    },
    "gemini": {
      "enabled": false,
      "api_key": "",
      "base_url": "https://generativelanguage.googleapis.com"
    },
    "grok": {
      "enabled": false,
      "api_key": "",
      "base_url": "https://api.x.ai"
    },
    "ollama": {
      "enabled": true,
      "api_key": "",
      "base_url": "http://127.0.0.1:11434"
    },
    "lmstudio": {
      "enabled": false,
      "api_key": "",
      "base_url": "http://127.0.0.1:1234"
    }
  }
}
CONFIGEOF
  log "config.json: created with defaults"
else
  log "config.json: exists"
fi

# ============================================================================
# Ollama Installation
# ============================================================================
log ""
log "Setting up Ollama..."

# Find Ollama CLI - check PATH first, then macOS app bundle
OLLAMA_CMD=""
if command -v ollama >/dev/null 2>&1; then
  OLLAMA_CMD="ollama"
  log "Ollama found in PATH"
elif [[ -x "/Applications/Ollama.app/Contents/Resources/ollama" ]]; then
  OLLAMA_CMD="/Applications/Ollama.app/Contents/Resources/ollama"
  log "Ollama found in app bundle"
else
  log "Installing Ollama..."
  if [[ "$(uname)" == "Darwin" ]]; then
    curl -fsSL https://ollama.com/install.sh | sh
    # After install, check app bundle location
    if [[ -x "/Applications/Ollama.app/Contents/Resources/ollama" ]]; then
      OLLAMA_CMD="/Applications/Ollama.app/Contents/Resources/ollama"
    elif command -v ollama >/dev/null 2>&1; then
      OLLAMA_CMD="ollama"
    fi
  elif [[ "$(uname)" == "Linux" ]]; then
    curl -fsSL https://ollama.com/install.sh | sh
    OLLAMA_CMD="ollama"
  else
    warn "Unsupported OS for automatic Ollama installation"
    warn "Please install Ollama manually from https://ollama.com"
    OLLAMA_CMD=""
  fi
fi

if [[ -n "${OLLAMA_CMD}" ]]; then
  log "Ollama version: $(${OLLAMA_CMD} --version 2>&1 || echo 'unknown')"
  
  # Start Ollama service if not running
  log "Checking Ollama service..."
  if ! curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    log "Starting Ollama service..."
    ${OLLAMA_CMD} serve &>/dev/null &
    sleep 5
    if curl -s http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
      log "Ollama service: started"
    else
      warn "Ollama service may not have started"
    fi
  else
    log "Ollama service: running"
  fi
  
  # Pull models
  MODELS=(
    "deepseek-r1:7b"
    "deepseek-r1:14b"
  )
  
  log ""
  log "Pulling Ollama models (this may take a while)..."
  for model in "${MODELS[@]}"; do
    # Check if model already exists
    if ${OLLAMA_CMD} list 2>/dev/null | grep -q "^${model}"; then
      log "  ${model}: already installed"
    else
      log "  Pulling ${model}..."
      if ${OLLAMA_CMD} pull "${model}" 2>&1 | tail -1; then
        log "  ${model}: installed"
      else
        warn "  Failed to pull ${model}"
      fi
    fi
  done
else
  warn "Ollama not available - local LLM features will not work"
fi

# ============================================================================
# Verify Python Imports
# ============================================================================
log ""
log "Verifying Python imports..."

python3 - <<'PY'
import sys
errors = []

# Core dependencies
try:
    import fastapi
    print(f"  fastapi: {fastapi.__version__}")
except ImportError as e:
    errors.append(f"fastapi: {e}")

try:
    import uvicorn
    print(f"  uvicorn: OK")
except ImportError as e:
    errors.append(f"uvicorn: {e}")

# Audio processing
try:
    import sounddevice
    print(f"  sounddevice: {sounddevice.__version__}")
except ImportError as e:
    errors.append(f"sounddevice: {e}")

try:
    import soundfile
    print(f"  soundfile: {soundfile.__version__}")
except ImportError as e:
    errors.append(f"soundfile: {e}")

# ML/Transcription
try:
    import torch
    print(f"  torch: {torch.__version__} (MPS: {torch.backends.mps.is_available() if hasattr(torch.backends, 'mps') else 'N/A'})")
except ImportError as e:
    errors.append(f"torch: {e}")

try:
    import whisperx
    print(f"  whisperx: OK")
except ImportError as e:
    errors.append(f"whisperx: {e}")

try:
    import faster_whisper
    print(f"  faster_whisper: OK")
except ImportError as e:
    errors.append(f"faster_whisper: {e}")

# Diarization
try:
    import pyannote.audio
    print(f"  pyannote.audio: {pyannote.audio.__version__}")
except ImportError as e:
    errors.append(f"pyannote.audio: {e}")

try:
    import diart
    print(f"  diart: OK")
except ImportError as e:
    errors.append(f"diart: {e}")

if errors:
    print("\nImport errors:")
    for err in errors:
        print(f"  ERROR: {err}")
    sys.exit(1)
else:
    print("\nAll imports successful!")
PY

# ============================================================================
# Installation Summary
# ============================================================================
log ""
log "============================================"
log "Installation Complete!"
log "============================================"
log ""
log "System components:"
log "  Python: $(python3 --version 2>&1)"
if command -v ffmpeg >/dev/null 2>&1; then
  log "  ffmpeg: installed"
fi
if [[ -n "${OLLAMA_CMD:-}" ]]; then
  log "  Ollama: installed"
  log ""
  log "Available Ollama models:"
  ${OLLAMA_CMD} list 2>/dev/null | head -10 || log "  (could not list models)"
fi
log ""
log "============================================"
log "Next Steps:"
log "============================================"
log ""
log "1. Start the server:"
log "   ./notetaker.sh"
log ""
log "2. Open the web interface:"
log "   http://127.0.0.1:6684"
log ""
log "3. Configure AI models in Settings > AI Models"
log "   - For local LLM: Select Ollama with deepseek-r1:7b or deepseek-r1:14b"
log "   - For cloud LLM: Add API keys for OpenAI, Anthropic, etc."
log ""
log "4. (Optional) For speaker diarization:"
log "   - Get a HuggingFace token: https://huggingface.co/settings/tokens"
log "   - Accept pyannote licenses:"
log "     https://huggingface.co/pyannote/speaker-diarization-3.1"
log "     https://huggingface.co/pyannote/segmentation-3.0"
log "   - Add token in Settings > Diarization"
log ""
log "============================================"
