================================================================================
NOTETAKER - Local Meeting Transcription & Summarization
================================================================================

Notetaker is a local-first application for recording, transcribing, and 
summarizing meetings. It runs entirely on your machine with optional cloud 
LLM support.

Features:
- Real-time audio transcription using Whisper
- Speaker diarization (identify who said what)
- AI-powered meeting summaries
- Support for local LLMs (Ollama/DeepSeek) or cloud APIs (OpenAI, Anthropic, etc.)
- Web-based interface

================================================================================
INSTALLATION - WINDOWS
================================================================================

Requirements: Windows 10 or 11, Internet connection

Step 1: Download the Project
----------------------------
Option A - Git:
  git clone https://github.com/armedad/notetaker.git
  cd notetaker

Option B - ZIP:
  1. Go to https://github.com/armedad/notetaker
  2. Click "Code" -> "Download ZIP"
  3. Extract to a folder (e.g., C:\notetaker)

Step 2: Run the Installer
-------------------------
  1. Open the notetaker folder
  2. Right-click "install.bat" -> "Run as administrator"
  3. Wait for installation to complete (10-30 minutes)

The installer will automatically install:
  - Python 3.11
  - ffmpeg (audio processing)
  - All Python dependencies
  - Ollama (local LLM runtime)
  - DeepSeek models for local AI summarization

Step 3: Start the Server
------------------------
  1. Double-click "start.bat" in the notetaker folder
  2. Wait for the startup message

Step 4: Open the Web Interface
------------------------------
  Open a browser and go to: http://127.0.0.1:6684

Troubleshooting (Windows):
--------------------------
- "winget not found": Install "App Installer" from Microsoft Store
- "Python not found": Close and reopen PowerShell, try again
- Ollama not starting: Run "ollama serve" in a separate PowerShell window

================================================================================
INSTALLATION - macOS
================================================================================

Requirements: macOS 12+ (Monterey or later), Internet connection

Step 1: Download the Project
----------------------------
Option A - Git:
  git clone https://github.com/armedad/notetaker.git
  cd notetaker

Option B - ZIP:
  1. Go to https://github.com/armedad/notetaker
  2. Click "Code" -> "Download ZIP"
  3. Extract to a folder

Step 2: Run the Installer
-------------------------
  1. Open Terminal (Applications -> Utilities -> Terminal)
  2. Navigate to the notetaker folder:
     cd /path/to/notetaker
  3. Make the installer executable and run it:
     chmod +x install.sh
     ./install.sh
  4. Wait for installation to complete (10-30 minutes)

The installer will automatically install:
  - Homebrew (if not present)
  - ffmpeg (audio processing)
  - portaudio (microphone access)
  - All Python dependencies
  - Ollama (local LLM runtime)
  - DeepSeek models for local AI summarization

Step 3: Start the Server
------------------------
  In Terminal, from the notetaker folder:
  ./notetaker.sh

Step 4: Open the Web Interface
------------------------------
  Open a browser and go to: http://127.0.0.1:6684

Troubleshooting (macOS):
------------------------
- "Permission denied": Run chmod +x install.sh and chmod +x notetaker.sh
- Python version warning: Install Python 3.11 via "brew install python@3.11"
- Microphone not working: Grant Terminal microphone access in System Settings
  -> Privacy & Security -> Microphone

================================================================================
POST-INSTALLATION SETUP
================================================================================

Configure AI Model (Required for Summarization)
-----------------------------------------------
1. Click "Settings" (top right of web interface)
2. Scroll to "AI Models" -> "Ollama"
3. Base URL should be: http://127.0.0.1:11434
4. Click "Test" to verify connection
5. Select model: deepseek-r1:7b (faster) or deepseek-r1:14b (better quality)

Alternative: Use Cloud LLMs
---------------------------
Instead of local Ollama, you can use cloud APIs:
- OpenAI: Add your API key in Settings -> AI Models -> OpenAI
- Anthropic: Add your API key in Settings -> AI Models -> Anthropic
- Google Gemini: Add your API key in Settings -> AI Models -> Gemini

Enable Speaker Diarization (Optional)
-------------------------------------
To identify different speakers in recordings:

1. Create a HuggingFace account: https://huggingface.co/join
2. Get an access token: https://huggingface.co/settings/tokens
3. Accept the pyannote model licenses (required):
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
4. In Notetaker Settings -> Diarization, paste your HuggingFace token
5. Enable diarization and click "Save"

================================================================================
USAGE
================================================================================

Recording a Meeting
-------------------
1. Select your microphone from the "Input source" dropdown
2. Click "Start recording"
3. The app will automatically open the meeting page
4. Transcription appears in real-time
5. Click "Stop recording" when finished
6. Click "Generate Summary" for an AI summary

Transcribing an Audio File
--------------------------
1. Select "File" from the "Input source" dropdown
2. Click "Choose file" and select an audio file (WAV, MP3, etc.)
3. Click "Start transcription"
4. Wait for processing to complete

================================================================================
FILE LOCATIONS
================================================================================

Configuration:     config.json
Meeting data:      data/meetings/
Audio recordings:  data/recordings/
Server logs:       logs/

Ollama models:
  Windows:  %USERPROFILE%\.ollama\models\
  macOS:    ~/.ollama/models/

================================================================================
SUPPORT
================================================================================

GitHub Issues: https://github.com/armedad/notetaker/issues

================================================================================
