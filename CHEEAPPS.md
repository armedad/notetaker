# CHEEAPPS shared Python environment

Apps under `coding/` that share one virtualenv via **`CHEEAPPS_VENV`**:

| App | Marker file |
|-----|-------------|
| gauth | `.gauth_venv` |
| voice-dictation-mvp | `.voice_dictation_venv` |
| notetaker | `.notetaker_venv` |
| cursor-agent | `.cursor_agent_venv` |

## Python version

**Target: Python 3.12** for all new and recreated venvs.

- **Windows (typical):** `X:\.env` on `\\cc\apps`
- **macOS (typical):** `coding/.venv` or `$HOME/venvs/cheeapps-stack`

Install helpers: [`scripts/cheeapps_python.sh`](scripts/cheeapps_python.sh), [`scripts/cheeapps_python.bat`](scripts/cheeapps_python.bat).

### Upgrade an existing venv from 3.10 / 3.13

1. Stop all four apps.
2. Backup or remove the old venv directory.
3. Create with 3.12:
   - **Windows:** `py -3.12 -m venv X:\.env`
   - **macOS:** `python3.12 -m venv /path/to/venv`
4. Reinstall each app (set `CHEEAPPS_VENV` to that path):
   - `gauth` → `voice-dictation-mvp` → `cursor-agent` → `notetaker`
   - voice-dictation: `./install.sh --recreate-venv` (or `install.bat --recreate-venv`)

### Notetaker ML stack pins

`notetaker/requirements.txt` pins `torch==2.5.1`, `torchaudio==2.5.1`, and `torchvision==0.20.1` so **pyannote.audio 3.3.2** and **whisperx 3.3.1** import on Python 3.12 (newer torchaudio drops `AudioMetaData`). If you upgrade torch in the shared venv, re-test `import whisperx` and `import pyannote.audio`.

### macOS: install Python 3.12

```bash
brew install python@3.12
```

Ensure `python3.12` is on PATH (Homebrew usually links it).
