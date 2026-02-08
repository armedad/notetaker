# Model Chooser Settings (Notetaker) — Spec

## Summary
Replace “Summary provider” with a single **Model Chooser**: an editable combo box listing all visible models across providers. Below it, add provider sections (OpenAI, Anthropic, Gemini, Grok) with API key + base URL, a **Default** button to restore provider defaults, and a **Test** button that validates credentials and fetches models. Successful tests add models to the chooser (grouped by provider) and show a green check.

## Goals
- Make model selection a single, visible choice.
- Support multiple providers with credentials and custom base URLs.
- Discover models and populate the chooser from provider tests.
- Persist everything in `config.json`.

## Non‑Goals
- Model routing logic beyond “selected model ID”.
- Multi‑selector slots (primary/backup).
- Provider-specific advanced options beyond base URL and key.

## User Experience

### Model Chooser (Top)
- Label: **Choose model**
- Editable combo box with dropdown.
- Shows **only visible models** (default hidden until tested + toggled visible).
- If no visible models, show empty hint: “Enable models below.”

### Provider Sections (Below)
For each provider (OpenAI, Anthropic, Gemini, Grok):
- API key input
- Base URL input (prefilled default; editable)
- **Default** button: restore base URL default
- **Test** button:
  - Validates URL + key
  - Fetches models
  - Adds models to registry (hidden by default)
  - Shows green check on success; red error on failure

### Model Registry
- List of discovered models grouped by provider.
- Each model has a **Visible** toggle (default off).
- Toggling visibility updates the chooser immediately.

## Behavior Details

### Visibility Rules
- New models default to `visible = false`.
- Only visible models appear in the chooser.
- If a selected model becomes invisible, selection is cleared and UI prompts user.

### Selection Rules
- Selection stored as full model ID including provider prefix: `provider:model-id`.
- If only one visible model exists, auto‑select it.

### Defaults
- Base URL defaults:
  - OpenAI: `https://api.openai.com`
  - Anthropic: `https://api.anthropic.com`
  - Gemini: `https://generativelanguage.googleapis.com`
  - Grok: `https://api.x.ai`
- “Default” resets base URL to provider default (does not clear key).

## Data Model (config.json)

```json
{
  "models": {
    "registry": [
      {"id":"openai:gpt-4o-mini","provider":"openai","name":"gpt-4o-mini","visible":false}
    ],
    "selected_model": "openai:gpt-4o-mini"
  },
  "providers": {
    "openai": {"api_key":"", "base_url":"https://api.openai.com"},
    "anthropic": {"api_key":"", "base_url":"https://api.anthropic.com"},
    "gemini": {"api_key":"", "base_url":"https://generativelanguage.googleapis.com"},
    "grok": {"api_key":"", "base_url":"https://api.x.ai"}
  }
}
```

## API Endpoints

### POST `/api/settings/models/test`
**Request**
```json
{"provider":"openai","api_key":"sk-...","base_url":"https://api.openai.com"}
```

**Response**
```json
{"status":"ok","models":["gpt-4o-mini","gpt-4o"]}
```

### GET `/api/settings/models`
Returns registry + selected model.

### POST `/api/settings/models`
Persists registry + selected model.

### GET/POST `/api/settings/providers`
Gets/sets provider keys + base URLs.

## UI Requirements
- Model chooser is the **primary selector**.
- Provider section buttons: **Default** and **Test**.
- Green check on successful test.
- Model registry grouped by provider.

## Errors
- Invalid key or URL: show provider‑specific error.
- No models found: show empty message.
