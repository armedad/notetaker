# notetaker — agent notes

Upstream: [armedad/notetaker](https://github.com/armedad/notetaker) — local meeting record, transcribe, diarize (summaries disabled in this fork).

Maintainer context: **Chee Chew** — see `\\CC\home\cursor\chee\digital-twin\` (VOICE.md, philosophies/communication.md) for user-facing copy Chee would own.

## This app

- **Stack:** Python FastAPI + static web UI (`app/`), entry `run.py` → `app.main:create_app`
- **Default URL:** `http://127.0.0.1:6684` (`config.json` → `server.port`)
- **Data:** `data/meetings/`, `data/recordings/`; config `config.json`
- **Live STT:** chunks every `transcription.live_chunk_seconds` (default 5s) during recording — unlike `voice-dictation`, which batches STT after stop
- **Start (macOS):** `./notetaker.sh` from a **deployed** copy (not the git tree — launcher exits if `.git` exists). Upstream `deploy.sh` rsyncs to `~/projects/notetaker` but only when `SRC_DIR` matches `*/coding/notetaker` — from `\\cc\apps\notetaker` use direct dev serve instead (below).
- **Dev serve (from git tree):** `uvicorn run:app --host 127.0.0.1 --port 6684` (after `install.sh` / venv + deps)
- **Start (Windows):** `start.bat` after `install.bat` (admin)

## Shared Python venv (Windows)

Same as gauth / voice-dictation: **`X:\.env`** (`\\cc\apps\.env`). Set once:

```powershell
$env:CHEEAPPS_VENV = "X:\.env"
cd X:\notetaker
.\install.bat
```

Install writes `.notetaker_venv` with the resolved path. Do not use broken `X:\notetaker\.venv` on the share — remove it if `Scripts\python.exe` is missing.

**Python version:** shared CHEEAPPS venv targets **3.12** (`X:\.env` on Windows). Recreate with `py -3.12 -m venv X:\.env`, then reinstall gauth → voice-dictation → cursor-agent → notetaker. See [`CHEEAPPS.md`](CHEEAPPS.md).

**Torch pins:** `requirements.txt` locks `torch` / `torchaudio` / `torchvision` at **2.5.1** so pyannote 3.3.2 imports on 3.12 (newer torchaudio drops `AudioMetaData`). Do not upgrade torch in the shared venv without re-testing whisperx + pyannote.

## Paths

Same repo as `\\cc\apps\notetaker` — also **`X:\notetaker`** (`\\cc\apps` is mounted as drive **X:**).

## Dev / git

Prefer **`X:\notetaker`** for git on Windows (avoids many UNC “dubious ownership” issues):

```powershell
git -C X:\notetaker status
```

If you must use UNC: `git -c safe.directory=//cc/apps/notetaker -C "\\cc\apps\notetaker" status`, or add that path to global `safe.directory` once.

## Key modules

| Area | Path |
|------|------|
| App factory | `app/main.py` |
| Recording / live transcription | `app/routers/recording.py`, `app/services/audio_capture.py` |
| Transcription | `app/routers/transcription.py` |
| Summarization / LLM | `app/routers/summarization.py`, `app/services/summarization.py`, `app/services/llm/` |
| Meetings | `app/routers/meetings.py`, `app/services/meeting_store.py` |
| Diarization | `app/services/diarization.py` |

## Sibling apps (same parent — see `X:\AGENTS.md`)

- `X:\gauth` — Gmail OAuth / API (port 4664)
- `X:\voice-dictation` — hotkey dictation → STT → cleanup → type (port 8946)
