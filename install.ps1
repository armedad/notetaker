# Notetaker Installation Script for Windows
# Run this script in PowerShell as Administrator
# Usage: .\install.ps1

$ErrorActionPreference = "Stop"

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "HH:mm:ss"
    Write-Host "[$timestamp] [install] $Message"
}

function Write-Warn {
    param([string]$Message)
    $timestamp = Get-Date -Format "HH:mm:ss"
    Write-Host "[$timestamp] [install] WARNING: $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    $timestamp = Get-Date -Format "HH:mm:ss"
    Write-Host "[$timestamp] [install] ERROR: $Message" -ForegroundColor Red
}

Write-Log "============================================"
Write-Log "Notetaker Installation Script (Windows)"
Write-Log "============================================"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Log "Project directory: $ProjectDir"
Write-Log ""

# ============================================================================
# Check for Administrator privileges
# ============================================================================
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Warn "Not running as Administrator. Some installations may fail."
    Write-Log "To run as Administrator: Right-click PowerShell -> Run as Administrator"
}

# ============================================================================
# Check for winget (Windows Package Manager)
# ============================================================================
Write-Log "Checking for winget..."
$hasWinget = $null -ne (Get-Command winget -ErrorAction SilentlyContinue)
if (-not $hasWinget) {
    Write-Warn "winget not found. Please install App Installer from Microsoft Store."
    Write-Log "https://apps.microsoft.com/store/detail/app-installer/9NBLGGH4NNS1"
}

# ============================================================================
# Python Installation
# ============================================================================
Write-Log ""
Write-Log "Checking Python..."

$pythonCmd = $null
$pythonPaths = @("python", "python3", "py -3")

foreach ($cmd in $pythonPaths) {
    try {
        $version = & $cmd.Split()[0] $cmd.Split()[1..99] --version 2>&1
        if ($version -match "Python 3\.(\d+)") {
            $pythonCmd = $cmd
            Write-Log "Found Python: $version"
            break
        }
    } catch {
        continue
    }
}

if (-not $pythonCmd) {
    Write-Log "Python not found. Installing Python 3.11..."
    if ($hasWinget) {
        winget install Python.Python.3.11 --accept-source-agreements --accept-package-agreements
        $pythonCmd = "py -3"
        Write-Log "Python installed. You may need to restart PowerShell."
    } else {
        Write-Err "Cannot install Python automatically. Please install Python 3.11+ from:"
        Write-Log "https://www.python.org/downloads/"
        Write-Log "Make sure to check 'Add Python to PATH' during installation."
        exit 1
    }
}

# Check Python version
$versionOutput = & $pythonCmd.Split()[0] $pythonCmd.Split()[1..99] -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
$pythonVersion = $versionOutput.Trim()
Write-Log "Python version: $pythonVersion"

$versionParts = $pythonVersion.Split(".")
$major = [int]$versionParts[0]
$minor = [int]$versionParts[1]

if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
    Write-Warn "Python 3.10+ recommended. Current: $pythonVersion"
    Write-Warn "Some features may not work correctly."
}

# ============================================================================
# ffmpeg Installation
# ============================================================================
Write-Log ""
Write-Log "Checking ffmpeg..."

$hasFFmpeg = $null -ne (Get-Command ffmpeg -ErrorAction SilentlyContinue)
if (-not $hasFFmpeg) {
    Write-Log "Installing ffmpeg..."
    if ($hasWinget) {
        winget install Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
        Write-Log "ffmpeg installed."
    } else {
        Write-Warn "Cannot install ffmpeg automatically."
        Write-Log "Please download from: https://www.gyan.dev/ffmpeg/builds/"
        Write-Log "Or install via chocolatey: choco install ffmpeg"
    }
} else {
    $ffmpegVersion = (ffmpeg -version 2>&1 | Select-Object -First 1)
    Write-Log "ffmpeg: $ffmpegVersion"
}

# ============================================================================
# Virtual Environment & Python Dependencies
# ============================================================================
Write-Log ""
Write-Log "Setting up Python environment..."

Set-Location $ProjectDir

$venvPath = Join-Path $ProjectDir ".venv"
if (-not (Test-Path $venvPath)) {
    Write-Log "Creating virtual environment..."
    & $pythonCmd.Split()[0] $pythonCmd.Split()[1..99] -m venv .venv
} else {
    Write-Log "Virtual environment: exists"
}

# Activate virtual environment
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
if (Test-Path $activateScript) {
    . $activateScript
} else {
    Write-Err "Could not find virtual environment activation script"
    exit 1
}

# Upgrade pip
Write-Log "Upgrading pip..."
python -m pip install --upgrade pip --quiet

# Install dependencies
$requirementsPath = Join-Path $ProjectDir "requirements.txt"
if (Test-Path $requirementsPath) {
    Write-Log "Installing Python dependencies (this may take several minutes)..."
    pip install -r requirements.txt
    Write-Log "Python dependencies: installed"
} else {
    Write-Err "requirements.txt not found!"
    exit 1
}

# ============================================================================
# Create Required Directories
# ============================================================================
Write-Log ""
Write-Log "Creating required directories..."

$directories = @(
    (Join-Path $ProjectDir "data\meetings"),
    (Join-Path $ProjectDir "data\recordings"),
    (Join-Path $ProjectDir "logs")
)

foreach ($dir in $directories) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}
Write-Log "Directories: created"

# ============================================================================
# Create Default Config if Missing
# ============================================================================
Write-Log ""
Write-Log "Checking configuration..."

$configPath = Join-Path $ProjectDir "config.json"
if (-not (Test-Path $configPath)) {
    Write-Log "Creating default config.json..."
    $defaultConfig = @'
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
'@
    $defaultConfig | Out-File -FilePath $configPath -Encoding utf8
    Write-Log "config.json: created with defaults"
} else {
    Write-Log "config.json: exists"
}

# ============================================================================
# Ollama Installation
# ============================================================================
Write-Log ""
Write-Log "Setting up Ollama..."

$ollamaCmd = $null
$hasOllama = $null -ne (Get-Command ollama -ErrorAction SilentlyContinue)

if ($hasOllama) {
    $ollamaCmd = "ollama"
    Write-Log "Ollama found in PATH"
} else {
    # Check common install locations
    $ollamaPaths = @(
        "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe",
        "$env:ProgramFiles\Ollama\ollama.exe",
        "C:\Ollama\ollama.exe"
    )
    
    foreach ($path in $ollamaPaths) {
        if (Test-Path $path) {
            $ollamaCmd = $path
            Write-Log "Ollama found at: $path"
            break
        }
    }
}

if (-not $ollamaCmd) {
    Write-Log "Installing Ollama..."
    if ($hasWinget) {
        winget install Ollama.Ollama --accept-source-agreements --accept-package-agreements
        # After install, check if it's now in PATH
        $hasOllama = $null -ne (Get-Command ollama -ErrorAction SilentlyContinue)
        if ($hasOllama) {
            $ollamaCmd = "ollama"
        } else {
            $ollamaCmd = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
        }
        Write-Log "Ollama installed."
    } else {
        Write-Warn "Cannot install Ollama automatically."
        Write-Log "Please download from: https://ollama.com/download/windows"
    }
}

if ($ollamaCmd -and (Test-Path $ollamaCmd -ErrorAction SilentlyContinue)) {
    # Get Ollama version
    try {
        $ollamaVersion = & $ollamaCmd --version 2>&1
        Write-Log "Ollama version: $ollamaVersion"
    } catch {
        Write-Log "Ollama: installed"
    }
    
    # Check if Ollama service is running
    Write-Log "Checking Ollama service..."
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5 -ErrorAction SilentlyContinue
        Write-Log "Ollama service: running"
    } catch {
        Write-Log "Starting Ollama service..."
        Start-Process -FilePath $ollamaCmd -ArgumentList "serve" -WindowStyle Hidden
        Start-Sleep -Seconds 5
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5 -ErrorAction SilentlyContinue
            Write-Log "Ollama service: started"
        } catch {
            Write-Warn "Ollama service may not have started. Please start it manually."
        }
    }
    
    # Pull models
    $models = @("deepseek-r1:7b", "deepseek-r1:14b")
    
    Write-Log ""
    Write-Log "Pulling Ollama models (this may take a while)..."
    
    foreach ($model in $models) {
        # Check if model exists
        try {
            $modelList = & $ollamaCmd list 2>&1
            if ($modelList -match [regex]::Escape($model)) {
                Write-Log "  ${model}: already installed"
            } else {
                Write-Log "  Pulling ${model}..."
                & $ollamaCmd pull $model
                Write-Log "  ${model}: installed"
            }
        } catch {
            Write-Warn "  Failed to pull ${model}: $_"
        }
    }
} elseif ($ollamaCmd) {
    Write-Warn "Ollama command found but executable not accessible"
    Write-Log "You may need to restart PowerShell or log out and back in."
}

# ============================================================================
# Verify Python Imports
# ============================================================================
Write-Log ""
Write-Log "Verifying Python imports..."

$verifyScript = @'
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
    cuda_available = torch.cuda.is_available()
    print(f"  torch: {torch.__version__} (CUDA: {cuda_available})")
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
'@

python -c $verifyScript

# ============================================================================
# Create Start Script
# ============================================================================
Write-Log ""
Write-Log "Creating start script..."

$startScript = @'
# Notetaker Start Script
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

# Activate virtual environment
. ".\.venv\Scripts\Activate.ps1"

# Start server
Write-Host "Starting Notetaker server..."
Write-Host "Web interface: http://127.0.0.1:6684"
Write-Host "Press Ctrl+C to stop"
Write-Host ""

python -m uvicorn run:app --host 127.0.0.1 --port 6684
'@

$startScriptPath = Join-Path $ProjectDir "start.ps1"
$startScript | Out-File -FilePath $startScriptPath -Encoding utf8
Write-Log "Created start.ps1"

# Also create a batch file for easier launching
$startBatch = @'
@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "start.ps1"
pause
'@

$startBatchPath = Join-Path $ProjectDir "start.bat"
$startBatch | Out-File -FilePath $startBatchPath -Encoding ascii
Write-Log "Created start.bat"

# ============================================================================
# Installation Summary
# ============================================================================
Write-Log ""
Write-Log "============================================"
Write-Log "Installation Complete!"
Write-Log "============================================"
Write-Log ""
Write-Log "System components:"
Write-Log "  Python: $pythonVersion"

if ($hasFFmpeg -or (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Log "  ffmpeg: installed"
}

if ($ollamaCmd) {
    Write-Log "  Ollama: installed"
    Write-Log ""
    Write-Log "Available Ollama models:"
    try {
        & $ollamaCmd list 2>&1 | Select-Object -First 10
    } catch {
        Write-Log "  (could not list models)"
    }
}

Write-Log ""
Write-Log "============================================"
Write-Log "Next Steps:"
Write-Log "============================================"
Write-Log ""
Write-Log "1. Start the server:"
Write-Log "   Double-click start.bat"
Write-Log "   OR run: .\start.ps1"
Write-Log ""
Write-Log "2. Open the web interface:"
Write-Log "   http://127.0.0.1:6684"
Write-Log ""
Write-Log "3. Configure AI models in Settings > AI Models"
Write-Log "   - For local LLM: Select Ollama with deepseek-r1:7b or deepseek-r1:14b"
Write-Log "   - For cloud LLM: Add API keys for OpenAI, Anthropic, etc."
Write-Log ""
Write-Log "4. (Optional) For speaker diarization:"
Write-Log "   - Get a HuggingFace token: https://huggingface.co/settings/tokens"
Write-Log "   - Accept pyannote licenses:"
Write-Log "     https://huggingface.co/pyannote/speaker-diarization-3.1"
Write-Log "     https://huggingface.co/pyannote/segmentation-3.0"
Write-Log "   - Add token in Settings > Diarization"
Write-Log ""
Write-Log "============================================"

Write-Host ""
Write-Host "Press any key to exit..." -ForegroundColor Cyan
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
