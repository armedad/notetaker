# Boot Hypotheses (Server Not Starting)

Source: review of pending changes in `@coding/notetaker` and deploy logs in `/Users/chee/projects/notetaker/logs`.

## Evidence Snapshot

- Latest deploy log shows crash during import:
  - `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`
  - Location: `app/routers/settings.py` at `hf_token: str | None = None`
- Deploy script runs under Python 3.9 (based on traceback paths).
- `@coding/notetaker` has already replaced that field with `Optional[str]`.

## Hypotheses

1) **Python 3.9 union syntax crash**
   - The deploy path still contains `str | None` type hints.
   - Expected behavior: import-time crash before uvicorn starts.

2) **Deploy not updated**
   - `@coding/notetaker` has fixes, but `/Users/chee/projects/notetaker` may still be running the older code.
   - Expected behavior: same error persists after launch.

3) **Dependency install failure**
   - WhisperX requires `faster-whisper==1.1.0`. If deploy still pins `1.0.3`, pip fails and server never starts.
   - Expected behavior: launcher log shows pip resolution error and exit code 1.

4) **Import-time failure in new diarization code**
   - If `torch` or `whisperx` imports fail at startup, uvicorn import may crash.
   - Expected behavior: traceback in server log referencing `whisperx_provider.py` or `torch`.

5) **Config schema mismatch**
   - If stored `config.json` has fields incompatible with current Pydantic models, startup may fail.
   - Expected behavior: traceback in settings or transcription router during model parsing.

6) **Entry point import failure**
   - If `run.py` or `app/main.py` references renamed/removed symbols, uvicorn import will fail.
   - Expected behavior: traceback in `run.py` import chain.

7) **Silent launcher logging change**
   - If launcher redirects output and server log path is wrong/missing, boot failure may look like “no output”.
   - Expected behavior: launcher log exists but server log missing or empty.

## Evidence Collection (Scripted in notetaker.sh)

- Prints Python version.
- Runs `pip check` after install.
- Preflight import of `run.py`.
- Preflight imports for `torch` and `whisperx`.
- Optional scan for `| None` union syntax if `rg` is available.
