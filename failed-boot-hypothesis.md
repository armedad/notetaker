# Failed Boot Hypotheses

Document capturing potential causes of server boot failure based on diff analysis between checked-in code and current working tree.

## RESOLVED - Root Cause Identified

**Issue**: The `notetaker.sh` script was hanging before launching uvicorn.

**Root Cause**: The script uses `exec > >(tee -a "${LAUNCHER_LOG}") 2>&1` at line 14 to redirect all output through `tee`. Later, the `start_watcher()` and `start_pid_writer()` functions spawn background subshells that inherited these file descriptors. When bash executed `WATCHER_PID="$(start_watcher)"`, it waited for all output from the command substitution to complete, but the backgrounded subshells kept the pipe open, causing a deadlock.

**Fix**: Added `</dev/null >/dev/null 2>&1` before the `&` in both `start_pid_writer()` and `start_watcher()` to detach the background processes from the inherited file descriptors:

```bash
start_pid_writer() {
  (
    # ... loop body ...
  ) </dev/null >/dev/null 2>&1 &
  echo $!
}
```

**Lesson**: When using `exec` to redirect stdout/stderr through a pipe (like `tee`), any background subshells must explicitly close or redirect away from those file descriptors to avoid blocking the parent process.

---

---

## Hypothesis 1: Missing Dependencies in requirements.txt

**Evidence from diff:**
```
+faster-whisper==1.1.0
+whisperx==3.3.1
+pyannote.audio==3.3.2
+python-multipart==0.0.9
```

**Problem:** New packages are added but may not be installed in the deployed `.venv`, or they may have conflicting dependencies (especially `whisperx`, `pyannote.audio`, and `torch`).

**Why it could prevent boot:**
- `app/services/diarization/__init__.py` imports `PyannoteProvider` and `WhisperXProvider` at module load time
- `app/services/summarization.py` imports from `app/services/llm` which requires `requests` (should be fine) but the LLM providers are always imported
- If any import fails, Python will error out before `create_app()` is even called

**How to test:**
```bash
cd /Users/chee/projects/notetaker
source .venv/bin/activate
python -c "import app.main; print('OK')"
```
If this fails with an ImportError or ModuleNotFoundError, this hypothesis is confirmed.

---

## Hypothesis 2: Circular Import or Import-Time Exception

**Evidence from diff:**
`app/main.py` now imports several new modules:
```python
from app.routers.meetings import create_meetings_router
from app.routers.settings import create_settings_router
from app.routers.summarization import create_summarization_router
from app.routers.uploads import create_uploads_router
from app.services.meeting_store import MeetingStore
from app.services.summarization import SummarizationConfig, SummarizationService
```

**Import chain:**
- `app.main` → `app.routers.transcription` → `app.services.diarization` → `app.services.diarization.providers.pyannote_provider` → `pyannote.audio`
- `app.main` → `app.services.summarization` → `app.services.llm` → `anthropic_provider`, `openai_provider`, `ollama_provider`
- `app.main` → `app.routers.transcription` → `app.services.diarization.providers.whisperx_provider` → `whisperx`, `torch`

**Why it could prevent boot:**
- Any exception during import (e.g., missing env var, bad configuration, import error) will prevent the module from loading
- The boot trace `[boot] app.main module import...` is only printed AFTER all imports in that file complete

**How to test:**
```bash
cd /Users/chee/projects/notetaker
source .venv/bin/activate
python -c "
import sys
sys.path.insert(0, '.')
print('Testing import chain...')
try:
    from app.services.diarization import DiarizationService
    print('diarization OK')
except Exception as e:
    print(f'diarization FAIL: {e}')
try:
    from app.services.llm import AnthropicProvider, OpenAIProvider, OllamaProvider
    print('llm OK')
except Exception as e:
    print(f'llm FAIL: {e}')
try:
    from app.services.summarization import SummarizationService
    print('summarization OK')
except Exception as e:
    print(f'summarization FAIL: {e}')
try:
    from app.services.meeting_store import MeetingStore
    print('meeting_store OK')
except Exception as e:
    print(f'meeting_store FAIL: {e}')
try:
    from app.routers.transcription import create_transcription_router
    print('transcription router OK')
except Exception as e:
    print(f'transcription router FAIL: {e}')
try:
    import app.main
    print('app.main OK')
except Exception as e:
    print(f'app.main FAIL: {e}')
"
```

---

## Hypothesis 3: `whisperx` or `torch` Import Crash

**Evidence from diff:**
`app/services/diarization/providers/whisperx_provider.py` and `notetaker.sh` both reference whisperx:
```python
import whisperx
import torch
```

The shell script has a preflight check:
```bash
log "Preflight: whisperx/torch availability"
python - <<'PY'
import torch
import whisperx
PY
```

**Why it could prevent boot:**
- `whisperx` and `torch` are heavy packages that can segfault or hang during import on certain systems (especially macOS with MPS/Metal)
- If the preflight passes but actual import during app load fails, it could be a race condition or environment difference
- The diarization `__init__.py` imports `WhisperXProvider` at the top level, which doesn't import `whisperx` itself (deferred), but `pyannote_provider.py` may indirectly trigger torch loading

**How to test:**
```bash
cd /Users/chee/projects/notetaker
source .venv/bin/activate
python -c "
import time
print('Importing torch...')
start = time.time()
import torch
print(f'torch OK in {time.time()-start:.2f}s, version={torch.__version__}')
print('Importing whisperx...')
start = time.time()
import whisperx
print(f'whisperx OK in {time.time()-start:.2f}s')
"
```

If this hangs or crashes, the hypothesis is confirmed.

---

## Hypothesis 4: `pyannote.audio` Import or Initialization Failure

**Evidence from diff:**
`app/services/diarization/providers/pyannote_provider.py`:
```python
from pyannote.audio import Pipeline
```

This import is inside the `diarize()` method (lazy), BUT `pyannote_provider.py` is imported at module load time in `diarization/__init__.py`.

**Why it could prevent boot:**
- `pyannote.audio` requires `torch` and many other dependencies
- If `pyannote.audio` is partially installed or has version conflicts with `torch`, import could fail
- The `pyannote.audio==3.3.2` version may not be compatible with the torch version

**How to test:**
```bash
cd /Users/chee/projects/notetaker
source .venv/bin/activate
python -c "
print('Testing pyannote import...')
try:
    from pyannote.audio import Pipeline
    print('pyannote.audio OK')
except Exception as e:
    print(f'pyannote.audio FAIL: {e}')
"
```

---

## Hypothesis 5: Untracked Files Not Deployed

**Evidence from git status:**
```
Untracked files:
  app/routers/meetings.py
  app/routers/settings.py
  app/routers/summarization.py
  app/routers/uploads.py
  app/services/diarization/
  app/services/llm/
  app/services/meeting_store.py
  app/services/summarization.py
  ...
```

**Why it could prevent boot:**
- `rsync` in `deploy.sh` may not copy untracked files if they were never added to git
- If `deploy.sh` uses `--exclude-from=.gitignore` or similar, new files might be skipped
- The deployed `/Users/chee/projects/notetaker` may be missing these critical new modules

**How to test:**
```bash
# Check if the new files exist in the deployed location
ls -la /Users/chee/projects/notetaker/app/routers/meetings.py
ls -la /Users/chee/projects/notetaker/app/routers/settings.py
ls -la /Users/chee/projects/notetaker/app/services/diarization/__init__.py
ls -la /Users/chee/projects/notetaker/app/services/llm/__init__.py
ls -la /Users/chee/projects/notetaker/app/services/meeting_store.py
ls -la /Users/chee/projects/notetaker/app/services/summarization.py
```

If any of these are missing, `deploy.sh` is not copying all files.

---

## Hypothesis 6: FasterWhisperProvider Constructor Signature Change

**Evidence from diff:**
`app/services/transcription/whisper_local.py`:
```python
# OLD:
def __init__(self, config: WhisperConfig) -> None:

# NEW:
def __init__(self, config: WhisperConfig, diarization: DiarizationService) -> None:
```

And in `app/routers/transcription.py`, the provider is now created differently:
```python
provider_cache[key] = FasterWhisperProvider(
    WhisperConfig(...),
    diarization_service,  # NEW required argument
)
```

**Why it could prevent boot:**
- If there's any other place that instantiates `FasterWhisperProvider` with the old signature, it will fail
- This is less likely to prevent boot (would be runtime error), but worth checking

**How to test:**
```bash
cd /Users/chee/projects/notetaker
rg "FasterWhisperProvider\(" --type py
```
Verify all call sites pass both arguments.

---

## Hypothesis 7: `run.py` Entry Point Issue

**Evidence:**
The shell script runs:
```bash
python -u -m uvicorn run:app --host 127.0.0.1 --port 6684
```

This requires a `run.py` file at the project root that exposes an `app` object.

**Why it could prevent boot:**
- If `run.py` has been changed and has a bug, uvicorn will fail to import it
- The preflight check in `notetaker.sh` does test `import run`, but any exception would exit early

**How to test:**
```bash
cd /Users/chee/projects/notetaker
source .venv/bin/activate
python -c "from run import app; print(type(app))"
```

---

## Hypothesis 8: Shell Script Pipeline Masking Exit Code

**Evidence from diff:**
```bash
PYTHONUNBUFFERED=1 python -u -m uvicorn run:app \
  --host 127.0.0.1 \
  --port 6684 \
  --log-level debug 2>&1 | tee -a "${SERVER_LOG}"
EXIT_CODE=${PIPESTATUS[0]}
```

**Why it could prevent boot:**
- If `uvicorn` fails immediately with an error, the error goes to stderr which is redirected to stdout and then to tee
- If tee's buffer doesn't flush before the script checks status, the log may appear empty
- The `set +e` / `set -e` should capture the exit code, but if uvicorn crashes hard (segfault), PIPESTATUS may not be reliable

**How to test:**
```bash
cd /Users/chee/projects/notetaker
source .venv/bin/activate
# Run uvicorn directly without tee/pipes
python -u -m uvicorn run:app --host 127.0.0.1 --port 6684 --log-level debug
```

Watch the raw output. If it crashes with an error, you'll see it directly.

---

## Recommended Debugging Order

1. **Test Hypothesis 5 first** (missing deployed files) - quickest to verify
2. **Test Hypothesis 8** (run uvicorn directly) - will reveal any Python errors immediately  
3. **Test Hypothesis 1 & 2** (import chain) - systematic import testing
4. **Test Hypothesis 3 & 4** (torch/whisperx/pyannote) - heavy dependency issues

---

## Quick One-Liner Diagnostic

Run this in the deployed directory to get immediate feedback:

```bash
cd /Users/chee/projects/notetaker && source .venv/bin/activate && python -c "
import sys
print('Python:', sys.executable)
print('Version:', sys.version)
try:
    from run import app
    print('SUCCESS: app imported')
    print('App type:', type(app))
except Exception as e:
    print('FAILURE:', type(e).__name__, str(e))
    import traceback
    traceback.print_exc()
"
```
