const state = {
  devices: [],
  modelOptions: {
    openai: [],
    anthropic: [],
    ollama: [],
    lmstudio: [],
  },
  registry: [],
  selectedModel: "",
  providerDefaults: {
    openai: "https://api.openai.com",
    anthropic: "https://api.anthropic.com",
    gemini: "https://generativelanguage.googleapis.com",
    grok: "https://api.x.ai",
    ollama: "http://127.0.0.1:11434",
    lmstudio: "http://127.0.0.1:1234",
  },
  modelFilter: "",
  gpuAvailable: false,
};

let saveTimeout = null;
let saveInProgress = false;
const providerTestTimeouts = new Map();

function debugLog(message, data = {}) {
  console.debug(`[Settings] ${message}`, data);
}

function debugError(message, error) {
  console.error(`[Settings] ${message}`, error);
}

function scheduleSave(action, delay = 400) {
  if (saveTimeout) {
    clearTimeout(saveTimeout);
  }
  saveTimeout = setTimeout(async () => {
    if (saveInProgress) {
      return;
    }
    saveInProgress = true;
    try {
      await action();
    } catch (error) {
      debugError("Auto-save failed", error);
    } finally {
      saveInProgress = false;
    }
  }, delay);
}

function scheduleProviderRefresh(provider, payloadBuilder, delay = 800) {
  if (providerTestTimeouts.has(provider)) {
    clearTimeout(providerTestTimeouts.get(provider));
  }
  const timeoutId = setTimeout(() => {
    testProvider(provider, payloadBuilder());
  }, delay);
  providerTestTimeouts.set(provider, timeoutId);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

function setGlobalError(message) {
  const errorEl = document.getElementById("global-error");
  errorEl.textContent = message || "";
}

function setGlobalBusy(message) {
  const busyEl = document.getElementById("global-busy");
  busyEl.textContent = message || "";
}

function getDiarizationDescription(choice) {
  const descriptions = {
    none: "Speaker identification is disabled. Transcripts will not distinguish between speakers.",
    diart:
      "🟢 REAL-TIME: Identifies speakers as you record, with ~500ms latency. " +
      "Best for live meetings where you want speaker labels during transcription. " +
      "Uses pyannote models with streaming inference.",
    whisperx:
      "⏸️ BATCH: Runs after transcription completes. Good accuracy with WhisperX integration. " +
      "Speaker labels appear after the recording ends.",
    "pyannote-3.1":
      "⏸️ BATCH: Best accuracy, runs after transcription. Uses pyannote/speaker-diarization-3.1. " +
      (state.gpuAvailable
        ? "GPU detected — good performance expected."
        : "Note: No GPU detected. This will be slow on CPU."),
    "pyannote-3.0":
      "⏸️ BATCH: Good accuracy, faster on CPU. Runs after transcription completes. " +
      (state.gpuAvailable
        ? "You have a GPU, so pyannote 3.1 would be more accurate."
        : "Better for CPU-only systems. About 2x faster than 3.1."),
  };
  return descriptions[choice] || "";
}

const DIARIZATION_MODELS = {
  "pyannote-3.1": "pyannote/speaker-diarization-3.1",
  "pyannote-3.0": "pyannote/speaker-diarization@2.1",
  diart: "",
  whisperx: "",
  none: "",
};

function setDiarizationOutput(message) {
  const output = document.getElementById("diarization-output");
  output.textContent = message;
}

function updateDiarizationUI() {
  const provider = document.getElementById("diarization-provider").value;
  const tokenRow = document.getElementById("diarization-token-row");
  const descriptionEl = document.getElementById("diarization-description");

  // Show/hide token field based on provider
  if (tokenRow) {
    tokenRow.style.display = provider === "none" ? "none" : "block";
  }

  // Update description with GPU-aware text
  if (descriptionEl) {
    descriptionEl.textContent = getDiarizationDescription(provider);
    // Hide description box when diarization is off
    descriptionEl.style.display = provider === "none" ? "none" : "block";
  }
}

function setTranscriptionOutput(message) {
  const output = document.getElementById("transcription-output");
  if (!output) {
    return;
  }
  output.textContent = message;
}

function setModelOutput(message) {
  const output = document.getElementById("model-output");
  output.textContent = message;
}

function applySelectedModel(modelId) {
  const modelChoice = document.getElementById("model-choice");
  if (modelChoice) {
    modelChoice.value = modelId || "";
  }
}

function syncModelChoiceFromConfig() {
  if (state.selectedModel) {
    applySelectedModel(state.selectedModel);
    return;
  }
  const modelChoice = document.getElementById("model-choice");
  if (modelChoice && modelChoice.value.trim()) {
    state.selectedModel = modelChoice.value.trim();
  }
}

function syncConfigFromModelChoice() {
  const value = document.getElementById("model-choice").value.trim();
  state.selectedModel = value;
  applySelectedModel(value);
}

function setModelOptions(provider, models) {
  state.modelOptions[provider] = models || [];
  renderModelDatalist();
}

function renderModelDatalist() {
  const list = document.getElementById("model-options");
  if (!list) {
    return;
  }
  list.innerHTML = "";
  const models = state.registry.filter((model) => model.visible);
  const emptyHint = document.getElementById("model-empty-hint");
  if (emptyHint) {
    emptyHint.style.display = models.length ? "none" : "block";
  }
  models.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    list.appendChild(option);
  });
}

function updateRegistryFromProvider(provider) {
  const models = state.modelOptions[provider] || [];
  const existing = new Map(state.registry.map((item) => [item.id, item]));
  const incomingIds = new Set();
  const updated = [];
  for (const modelId of models) {
    const id = `${provider}:${modelId}`;
    incomingIds.add(id);
    const current = existing.get(id);
    updated.push({
      id,
      provider,
      name: modelId,
      visible: current ? current.visible : false,
    });
  }
  for (const existingItem of state.registry) {
    if (existingItem.provider === provider && !incomingIds.has(existingItem.id)) {
      updated.push(existingItem);
    }
  }
  for (const existingItem of state.registry) {
    if (existingItem.provider !== provider) {
      updated.push(existingItem);
    }
  }
  state.registry = updated;
  renderRegistry();
  renderModelDatalist();
}

function renderRegistry() {
  const container = document.getElementById("model-registry");
  if (!container) {
    return;
  }
  container.innerHTML = "";
  const filter = state.modelFilter.trim().toLowerCase();
  const tokens = filter.split(/\s+/).filter(Boolean);
  const filtered = state.registry.filter((model) => {
    if (!tokens.length) {
      return true;
    }
    const haystack = `${model.provider} ${model.name} ${model.id}`.toLowerCase();
    return tokens.every((token) => haystack.includes(token));
  });
  if (!filtered.length) {
    container.textContent = "No models discovered yet.";
    return;
  }
  filtered.forEach((model) => {
    const row = document.createElement("div");
    row.className = "model-row";
    const label = document.createElement("div");
    label.textContent = `${model.provider} · ${model.name}`;
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = !!model.visible;
    checkbox.addEventListener("change", () => {
      model.visible = checkbox.checked;
      renderModelDatalist();
      scheduleSave(saveSummarizationSettings);
    });
    row.appendChild(label);
    row.appendChild(checkbox);
    container.appendChild(row);
  });
}

async function testProvider(provider, payload) {
  setModelOutput(`Testing ${provider}...`);
  setGlobalBusy(`Testing ${provider}...`);
  try {
    const result = await fetchJson("/api/settings/models/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (result.status !== "ok") {
      throw new Error(result.message || "Test failed");
    }
    setModelOptions(provider, result.models || []);
    updateRegistryFromProvider(provider);
    syncModelChoiceFromConfig();
    setModelOutput(`${provider} OK. ${result.models?.length || 0} models.`);
    setProviderStatus(provider, true);
    scheduleSave(saveSummarizationSettings);
  } catch (error) {
    setModelOutput(`${provider} test failed: ${error.message}`);
    setProviderStatus(provider, false);
  } finally {
    setGlobalBusy("");
  }
}

function setProviderStatus(provider, success) {
  const status = document.getElementById(`${provider}-status`);
  if (!status) {
    return;
  }
  status.textContent = success ? "✓" : "✕";
  status.classList.toggle("ok", success);
  status.classList.toggle("error", !success);
}

function renderDevices() {
  const select = document.getElementById("device-select");
  select.innerHTML = "";
  state.devices.forEach((device) => {
    const option = document.createElement("option");
    option.value = device.index;
    option.textContent = `${device.index} — ${device.name} (${device.max_input_channels} ch)`;
    select.appendChild(option);
  });
}

async function refreshDevices() {
  setGlobalBusy("Loading devices...");
  setGlobalError("");
  try {
    state.devices = await fetchJson("/api/audio/devices");
    renderDevices();
  } catch (error) {
    setGlobalError(`Device refresh failed: ${error.message}`);
  } finally {
    setGlobalBusy("");
  }
}

async function loadAudioSettings() {
  try {
    const data = await fetchJson("/api/settings/audio");
    if (data.device_index !== null && data.device_index !== undefined) {
      document.getElementById("device-select").value = data.device_index;
    }
    if (data.samplerate) {
      document.getElementById("samplerate").value = data.samplerate;
    }
    if (data.channels) {
      document.getElementById("channels").value = data.channels;
    }
  } catch (error) {
    setGlobalError(`Failed to load audio settings: ${error.message}`);
  }
}

async function loadTranscriptionSettings() {
  try {
    const data = await fetchJson("/api/settings/transcription");
    if (!data || Object.keys(data).length === 0) {
      setDiarizationDeviceState(false);
      setPerformanceLabel(50);
      return;
    }
    if (data.live_model_size) {
      document.getElementById("live-model-size").value = data.live_model_size;
    }
    if (data.final_model_size) {
      document.getElementById("final-model-size").value = data.final_model_size;
    }
    document.getElementById("auto-transcribe").checked =
      data.auto_transcribe ?? true;
    document.getElementById("stream-transcribe").checked =
      data.stream_transcribe ?? true;
    document.getElementById("live-transcribe").checked =
      data.live_transcribe ?? true;
  } catch (error) {
    setGlobalError(`Failed to load transcription settings: ${error.message}`);
  }
}

async function saveAudioSettings() {
  const deviceIndex = Number(document.getElementById("device-select").value);
  const samplerate = Number(document.getElementById("samplerate").value);
  const channels = Number(document.getElementById("channels").value);
  setGlobalBusy("Saving audio settings...");
  try {
    await fetchJson("/api/settings/audio", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        device_index: deviceIndex,
        samplerate,
        channels,
      }),
    });
  } catch (error) {
    setGlobalError(`Failed to save audio settings: ${error.message}`);
  } finally {
    setGlobalBusy("");
  }
}

async function saveDiarizationSettings() {
  const providerChoice = document.getElementById("diarization-provider").value;
  const hfToken = document.getElementById("hf-token").value.trim();

  // Map UI choice to backend provider and model
  let backendProvider = providerChoice;
  let model = DIARIZATION_MODELS[providerChoice] || "";
  let enabled = providerChoice !== "none";

  if (providerChoice === "pyannote-3.1" || providerChoice === "pyannote-3.0") {
    backendProvider = "pyannote";
  }
  // diart and whisperx use their own names as provider

  setDiarizationOutput("Saving diarization settings...");
  setGlobalBusy("Saving diarization settings...");
  try {
    await fetchJson("/api/settings/diarization", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled,
        provider: backendProvider,
        model,
        device: "cpu", // Default to CPU for simplicity
        hf_token: hfToken || null,
        performance_level: 0.5,
      }),
    });
    setDiarizationOutput("Diarization settings saved.");
  } catch (error) {
    setDiarizationOutput(`Failed to save: ${error.message}`);
    setGlobalError("Diarization save failed.");
  } finally {
    setGlobalBusy("");
  }
}

async function saveTranscriptionSettings() {
  const payload = {
    live_model_size: document.getElementById("live-model-size").value,
    final_model_size: document.getElementById("final-model-size").value,
    auto_transcribe: document.getElementById("auto-transcribe").checked,
    stream_transcribe: document.getElementById("stream-transcribe").checked,
    live_transcribe: document.getElementById("live-transcribe").checked,
  };
  setTranscriptionOutput("Saving transcription settings...");
  setGlobalBusy("Saving transcription settings...");
  try {
    await fetchJson("/api/settings/transcription", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setTranscriptionOutput("Transcription settings saved.");
  } catch (error) {
    setTranscriptionOutput(`Failed to save: ${error.message}`);
    setGlobalError("Transcription settings failed to save.");
  } finally {
    setGlobalBusy("");
  }
}

async function loadSummarizationSettings() {
  try {
    const data = await fetchJson("/api/settings/providers");
    if (!data || Object.keys(data).length === 0) {
      return;
    }
    document.getElementById("openai-api-key").value =
      data.openai?.api_key || "";
    document.getElementById("openai-base-url").value =
      data.openai?.base_url || state.providerDefaults.openai;
    document.getElementById("anthropic-api-key").value =
      data.anthropic?.api_key || "";
    document.getElementById("anthropic-base-url").value =
      data.anthropic?.base_url || state.providerDefaults.anthropic;
    document.getElementById("gemini-api-key").value =
      data.gemini?.api_key || "";
    document.getElementById("gemini-base-url").value =
      data.gemini?.base_url || state.providerDefaults.gemini;
    document.getElementById("grok-api-key").value =
      data.grok?.api_key || "";
    document.getElementById("grok-base-url").value =
      data.grok?.base_url || state.providerDefaults.grok;
    document.getElementById("ollama-api-key").value =
      data.ollama?.api_key || "";
    document.getElementById("ollama-base-url").value =
      data.ollama?.base_url || state.providerDefaults.ollama;
    document.getElementById("lmstudio-api-key").value =
      data.lmstudio?.api_key || "";
    document.getElementById("lmstudio-base-url").value =
      data.lmstudio?.base_url || state.providerDefaults.lmstudio;
    await loadModelRegistry();
  } catch (error) {
    setGlobalError(`Failed to load model settings: ${error.message}`);
  }
}

async function loadModelRegistry() {
  try {
    const data = await fetchJson("/api/settings/models");
    state.registry = data.registry || [];
    state.selectedModel = data.selected_model || "";
    renderRegistry();
    renderModelDatalist();
    syncModelChoiceFromConfig();
  } catch (error) {
    setGlobalError(`Failed to load model registry: ${error.message}`);
  }
}

async function loadDiarizationSettings() {
  try {
    const data = await fetchJson("/api/settings/diarization");

    // Store GPU availability for recommendations
    state.gpuAvailable = data?.gpu_available ?? false;

    if (!data || Object.keys(data).length === 0) {
      updateDiarizationUI();
      return;
    }

    // Map backend provider + model to UI choice
    let uiChoice = "none";
    if (data.enabled) {
      if (data.provider === "pyannote") {
        if (data.model && data.model.includes("3.1")) {
          uiChoice = "pyannote-3.1";
        } else {
          uiChoice = "pyannote-3.0";
        }
      } else if (data.provider === "whisperx") {
        uiChoice = "whisperx";
      } else if (data.provider === "diart") {
        uiChoice = "diart";
      }
    }

    document.getElementById("diarization-provider").value = uiChoice;
    document.getElementById("hf-token").value = data.hf_token || "";
    updateDiarizationUI();
  } catch (error) {
    setGlobalError(`Failed to load diarization settings: ${error.message}`);
  }
}

async function saveSummarizationSettings() {
  syncConfigFromModelChoice();
  const payload = {
    openai: {
      api_key: document.getElementById("openai-api-key").value.trim(),
      base_url: document.getElementById("openai-base-url").value.trim(),
    },
    anthropic: {
      api_key: document.getElementById("anthropic-api-key").value.trim(),
      base_url: document.getElementById("anthropic-base-url").value.trim(),
    },
    gemini: {
      api_key: document.getElementById("gemini-api-key").value.trim(),
      base_url: document.getElementById("gemini-base-url").value.trim(),
    },
    grok: {
      api_key: document.getElementById("grok-api-key").value.trim(),
      base_url: document.getElementById("grok-base-url").value.trim(),
    },
    ollama: {
      api_key: document.getElementById("ollama-api-key").value.trim(),
      base_url: document.getElementById("ollama-base-url").value.trim(),
    },
    lmstudio: {
      api_key: document.getElementById("lmstudio-api-key").value.trim(),
      base_url: document.getElementById("lmstudio-base-url").value.trim(),
    },
  };
  setModelOutput("Saving model settings...");
  setGlobalBusy("Saving model settings...");
  try {
    await fetchJson("/api/settings/providers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    await fetchJson("/api/settings/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        registry: state.registry,
        selected_model: state.selectedModel,
      }),
    });
    setModelOutput("Model settings saved.");
  } catch (error) {
    setModelOutput(`Failed to save: ${error.message}`);
    setGlobalError("Model settings failed to save.");
  } finally {
    setGlobalBusy("");
  }
}

async function refreshVersion() {
  try {
    const data = await fetchJson("/api/health");
    const badge = document.getElementById("version-badge");
    badge.textContent = data.version;
  } catch (error) {
    setGlobalError("Health check failed.");
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  document
    .getElementById("refresh-devices")
    .addEventListener("click", async () => {
      await refreshDevices();
      await loadAudioSettings();
    });
  document
    .getElementById("device-select")
    .addEventListener("change", () => scheduleSave(saveAudioSettings));
  document
    .getElementById("samplerate")
    .addEventListener("change", () => scheduleSave(saveAudioSettings));
  document
    .getElementById("channels")
    .addEventListener("change", () => scheduleSave(saveAudioSettings));
  document
    .getElementById("diarization-provider")
    .addEventListener("change", () => {
      updateDiarizationUI();
      scheduleSave(saveDiarizationSettings);
    });
  document
    .getElementById("hf-token")
    .addEventListener("input", () => scheduleSave(saveDiarizationSettings, 800));
  document
    .getElementById("live-model-size")
    .addEventListener("change", () => scheduleSave(saveTranscriptionSettings));
  document
    .getElementById("final-model-size")
    .addEventListener("change", () => scheduleSave(saveTranscriptionSettings));
  document
    .getElementById("auto-transcribe")
    .addEventListener("change", () => scheduleSave(saveTranscriptionSettings));
  document
    .getElementById("stream-transcribe")
    .addEventListener("change", () => scheduleSave(saveTranscriptionSettings));
  document
    .getElementById("live-transcribe")
    .addEventListener("change", () => scheduleSave(saveTranscriptionSettings));
  document
    .getElementById("model-choice")
    .addEventListener("change", () => scheduleSave(saveSummarizationSettings));
  document
    .getElementById("model-filter")
    .addEventListener("input", (event) => {
      state.modelFilter = event.target.value || "";
      renderRegistry();
    });
  document
    .getElementById("openai-api-key")
    .addEventListener("input", () => {
      scheduleSave(saveSummarizationSettings, 800);
      scheduleProviderRefresh("openai", () => ({
        provider: "openai",
        api_key: document.getElementById("openai-api-key").value.trim(),
        base_url: document.getElementById("openai-base-url").value.trim(),
      }));
    });
  document
    .getElementById("openai-base-url")
    .addEventListener("change", () => {
      scheduleSave(saveSummarizationSettings);
      scheduleProviderRefresh("openai", () => ({
        provider: "openai",
        api_key: document.getElementById("openai-api-key").value.trim(),
        base_url: document.getElementById("openai-base-url").value.trim(),
      }), 200);
    });
  document
    .getElementById("openai-default")
    .addEventListener("click", () => {
      document.getElementById("openai-base-url").value =
        state.providerDefaults.openai;
      scheduleSave(saveSummarizationSettings);
    });
  document
    .getElementById("anthropic-api-key")
    .addEventListener("input", () => {
      scheduleSave(saveSummarizationSettings, 800);
      scheduleProviderRefresh("anthropic", () => ({
        provider: "anthropic",
        api_key: document.getElementById("anthropic-api-key").value.trim(),
        base_url: document.getElementById("anthropic-base-url").value.trim(),
      }));
    });
  document
    .getElementById("anthropic-base-url")
    .addEventListener("change", () => {
      scheduleSave(saveSummarizationSettings);
      scheduleProviderRefresh("anthropic", () => ({
        provider: "anthropic",
        api_key: document.getElementById("anthropic-api-key").value.trim(),
        base_url: document.getElementById("anthropic-base-url").value.trim(),
      }), 200);
    });
  document
    .getElementById("anthropic-default")
    .addEventListener("click", () => {
      document.getElementById("anthropic-base-url").value =
        state.providerDefaults.anthropic;
      scheduleSave(saveSummarizationSettings);
    });
  document
    .getElementById("gemini-api-key")
    .addEventListener("input", () => {
      scheduleSave(saveSummarizationSettings, 800);
      scheduleProviderRefresh("gemini", () => ({
        provider: "gemini",
        api_key: document.getElementById("gemini-api-key").value.trim(),
        base_url: document.getElementById("gemini-base-url").value.trim(),
      }));
    });
  document
    .getElementById("gemini-base-url")
    .addEventListener("change", () => {
      scheduleSave(saveSummarizationSettings);
      scheduleProviderRefresh("gemini", () => ({
        provider: "gemini",
        api_key: document.getElementById("gemini-api-key").value.trim(),
        base_url: document.getElementById("gemini-base-url").value.trim(),
      }), 200);
    });
  document
    .getElementById("gemini-default")
    .addEventListener("click", () => {
      document.getElementById("gemini-base-url").value =
        state.providerDefaults.gemini;
      scheduleSave(saveSummarizationSettings);
    });
  document
    .getElementById("grok-api-key")
    .addEventListener("input", () => {
      scheduleSave(saveSummarizationSettings, 800);
      scheduleProviderRefresh("grok", () => ({
        provider: "grok",
        api_key: document.getElementById("grok-api-key").value.trim(),
        base_url: document.getElementById("grok-base-url").value.trim(),
      }));
    });
  document
    .getElementById("grok-base-url")
    .addEventListener("change", () => {
      scheduleSave(saveSummarizationSettings);
      scheduleProviderRefresh("grok", () => ({
        provider: "grok",
        api_key: document.getElementById("grok-api-key").value.trim(),
        base_url: document.getElementById("grok-base-url").value.trim(),
      }), 200);
    });
  document
    .getElementById("grok-default")
    .addEventListener("click", () => {
      document.getElementById("grok-base-url").value =
        state.providerDefaults.grok;
      scheduleSave(saveSummarizationSettings);
    });
  document
    .getElementById("ollama-api-key")
    .addEventListener("input", () => {
      scheduleSave(saveSummarizationSettings, 800);
      scheduleProviderRefresh("ollama", () => ({
        provider: "ollama",
        base_url: document.getElementById("ollama-base-url").value.trim(),
      }));
    });
  document
    .getElementById("ollama-base-url")
    .addEventListener("change", () => {
      scheduleSave(saveSummarizationSettings);
      scheduleProviderRefresh("ollama", () => ({
        provider: "ollama",
        base_url: document.getElementById("ollama-base-url").value.trim(),
      }), 200);
    });
  document
    .getElementById("ollama-default")
    .addEventListener("click", () => {
      document.getElementById("ollama-base-url").value =
        state.providerDefaults.ollama;
      scheduleSave(saveSummarizationSettings);
    });
  document
    .getElementById("lmstudio-api-key")
    .addEventListener("input", () => {
      scheduleSave(saveSummarizationSettings, 800);
      scheduleProviderRefresh("lmstudio", () => ({
        provider: "lmstudio",
        base_url: document.getElementById("lmstudio-base-url").value.trim(),
      }));
    });
  document
    .getElementById("lmstudio-base-url")
    .addEventListener("change", () => {
      scheduleSave(saveSummarizationSettings);
      scheduleProviderRefresh("lmstudio", () => ({
        provider: "lmstudio",
        base_url: document.getElementById("lmstudio-base-url").value.trim(),
      }), 200);
    });
  document
    .getElementById("lmstudio-default")
    .addEventListener("click", () => {
      document.getElementById("lmstudio-base-url").value =
        state.providerDefaults.lmstudio;
      scheduleSave(saveSummarizationSettings);
    });
  document.getElementById("test-ollama").addEventListener("click", () => {
    testProvider("ollama", {
      provider: "ollama",
      base_url: document.getElementById("ollama-base-url").value.trim(),
    });
  });
  document.getElementById("test-openai").addEventListener("click", () => {
    testProvider("openai", {
      provider: "openai",
      api_key: document.getElementById("openai-api-key").value.trim(),
      base_url: document.getElementById("openai-base-url").value.trim(),
    });
  });
  document.getElementById("test-anthropic").addEventListener("click", () => {
    testProvider("anthropic", {
      provider: "anthropic",
      api_key: document.getElementById("anthropic-api-key").value.trim(),
      base_url: document.getElementById("anthropic-base-url").value.trim(),
    });
  });
  document.getElementById("test-gemini").addEventListener("click", () => {
    testProvider("gemini", {
      provider: "gemini",
      api_key: document.getElementById("gemini-api-key").value.trim(),
      base_url: document.getElementById("gemini-base-url").value.trim(),
    });
  });
  document.getElementById("test-grok").addEventListener("click", () => {
    testProvider("grok", {
      provider: "grok",
      api_key: document.getElementById("grok-api-key").value.trim(),
      base_url: document.getElementById("grok-base-url").value.trim(),
    });
  });
  document.getElementById("test-lmstudio").addEventListener("click", () => {
    testProvider("lmstudio", {
      provider: "lmstudio",
      base_url: document.getElementById("lmstudio-base-url").value.trim(),
    });
  });
  document.getElementById("test-ollama").addEventListener("click", () => {
    testProvider("ollama", {
      provider: "ollama",
      base_url: document.getElementById("ollama-base-url").value.trim(),
    });
  });

  document
    .getElementById("back-home")
    .addEventListener("click", () => {
      window.location.href = "/";
    });

  await refreshVersion();
  await refreshDevices();
  await loadAudioSettings();
  await loadTranscriptionSettings();
  await loadSummarizationSettings();
  await loadDiarizationSettings();
});
