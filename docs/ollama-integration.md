# Ollama Integration

How the notetaker connects to Ollama for local LLM inference.

## Architecture Overview

Notetaker talks to Ollama **directly over HTTP** using the `requests` library. There is no SDK, no proxy, and no intermediate service. The `OllamaProvider` class makes raw REST calls to the Ollama server.

```
Settings UI
    ↓ writes provider + model selection
config.json  (data/config.json at runtime)
    ↓ read on each LLM call
SummarizationService._get_provider()
    ↓ creates provider instance
OllamaProvider(base_url, model)
    ↓ direct HTTP (requests library)
Ollama server at http://127.0.0.1:11434
    POST /api/generate   (all LLM generation)
    GET  /api/tags        (health check + model discovery)
```

## Ollama REST API Endpoints Used

| Endpoint | Method | Purpose | Used By |
|---|---|---|---|
| `/api/generate` | POST | Text generation (streaming and non-streaming) | `OllamaProvider._call_api`, `_call_api_stream` |
| `/api/tags` | GET | Health check, detect if Ollama is running, discover available models | `ensure_ollama_running`, settings UI model discovery |

The app does **not** use `/api/chat`. All prompts go through the completion-style `/api/generate` endpoint. System prompts are prepended to the user prompt as a single string rather than using Ollama's chat message format.

## Provider Class

**File:** `app/services/llm/ollama_provider.py`

`OllamaProvider` extends `BaseLLMProvider` with two core methods:

**Non-streaming** (`_call_api`): Sends `POST /api/generate` with `"stream": false`. Returns the full response text from `data["response"]`.

**Streaming** (`_call_api_stream`): Sends `POST /api/generate` with `"stream": true` and `stream=True` on the requests call. Iterates over NDJSON lines. Each line is a JSON object with a `"response"` field containing one token. `"done": true` signals completion.

Request body format:

```json
{
  "model": "llama3",
  "prompt": "system prompt text\n\nuser prompt text",
  "stream": true,
  "format": "json"
}
```

- `format: "json"` is only included when JSON mode is requested (e.g., for structured extraction).
- Temperature is not currently passed through to the Ollama API.

## Configuration

**Source:** `config.json` at `data/config.json` (runtime path)

```json
{
  "providers": {
    "ollama": {
      "enabled": true,
      "api_key": "",
      "base_url": "http://127.0.0.1:11434"
    }
  },
  "models": {
    "selected_model": "ollama:llama3"
  }
}
```

- **`providers.ollama.base_url`** — The Ollama server address. Default: `http://127.0.0.1:11434`. Editable in the Settings UI.
- **`models.selected_model`** — Format is `provider:model_id` (e.g., `ollama:llama3`). The part after the colon is the Ollama model name exactly as it appears in `ollama list`.
- **`api_key`** — Not used by Ollama, included for provider interface consistency.

The config is read fresh on every LLM call (`SummarizationService._get_provider()` in `app/services/summarization.py`), so changes take effect immediately without restart.

## Provider Selection

`SummarizationService._get_provider()` reads `config.json`, splits `selected_model` on `:`, and routes to the appropriate provider class:

```python
if provider_name == "ollama":
    if not base_url:
        base_url = "http://127.0.0.1:11434"
    return OllamaProvider(base_url=base_url, model=model_id)
```

A new `OllamaProvider` instance is created per call (stateless).

## Auto-Launch

**File:** `app/services/llm/ollama_provider.py` — `ensure_ollama_running(base_url)`

When Ollama is the selected provider, the app automatically launches it if it's not already running. This happens in two places:

1. **App boot** (`app/main.py`): If the selected model starts with `ollama:`, launches in a background daemon thread.
2. **Settings change** (`app/routers/settings.py`): If the user switches to an Ollama model, launches in a background daemon thread.

The auto-launch sequence:

1. **Check:** `GET /api/tags` with a 3-second timeout.
2. **If reachable:** Done, Ollama is already running (possibly started by another app).
3. **If not reachable and base_url is remote:** Log a warning and stop. Never launch locally when the user has configured a remote Ollama server.
4. **If not reachable and base_url is localhost:** Find the launch command:
   - macOS: `open -a /Applications/Ollama.app`
   - Windows: `%LOCALAPPDATA%/Programs/Ollama/ollama.exe serve`
   - Fallback: `ollama serve` (if on PATH)
4. **Launch:** `subprocess.Popen` (detached, stdout/stderr suppressed).
5. **Poll:** Hit `GET /api/tags` every 1 second for up to 30 seconds until Ollama responds.

Both launch sites use `threading.Thread(daemon=True)` so the launch never blocks the server or the settings request.

## What Ollama Is Used For

Ollama serves as the LLM backend for all AI features when selected:

- Meeting summarization
- Title generation
- Chat (meeting-specific and cross-meeting)
- Action item extraction
- Speaker name suggestions

All these features go through the same `SummarizationService._get_provider()` → `OllamaProvider` path.

## Launch Offer in Settings

When a user clicks "Test" for Ollama in Settings and it fails:

- **Local URL** (localhost/127.0.0.1): The test returns `can_launch: true`. The UI shows the error message with a "Launch Ollama" button. Clicking it calls `POST /api/settings/ollama/launch`, which runs `ensure_ollama_running` synchronously (blocks until Ollama is reachable or times out ~30s), then returns the available models on success.
- **Remote URL**: The test returns a plain error. No launch button is shown — you can't start a remote server from here.

## Troubleshooting

**"Failed to reach Ollama"** — The Ollama server isn't running and auto-launch failed. Manually start Ollama (open the app on macOS, or run `ollama serve`).

**Wrong models showing** — The Settings UI discovers models via `GET /api/tags`. If you've pulled new models, they should appear immediately. If they don't, check that the base URL in settings points to the right Ollama instance.

**Slow responses** — Ollama runs models locally. Performance depends on your hardware. Smaller models (e.g., `llama3:8b`) are faster but less capable than larger ones.
