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

// Real-time diarization helpers
function setRealtimeDiarizationOutput(message) {
  const output = document.getElementById("realtime-diarization-output");
  if (output) output.textContent = message;
}

function updateRealtimeDiarizationUI() {
  const enabled = document.getElementById("realtime-diarization-enabled").checked;
  const providerSelect = document.getElementById("realtime-diarization-provider");
  const deviceRow = document.getElementById("realtime-device-row");
  const performanceRow = document.getElementById("realtime-performance-row");
  const tokenRow = document.getElementById("realtime-token-row");
  
  const showFields = enabled && providerSelect.value !== "none";
  
  if (deviceRow) deviceRow.style.display = showFields ? "block" : "none";
  if (performanceRow) performanceRow.style.display = showFields ? "block" : "none";
  if (tokenRow) tokenRow.style.display = showFields ? "block" : "none";
  
  // Update GPU hint
  const gpuHint = document.getElementById("realtime-gpu-hint");
  if (gpuHint) {
    gpuHint.textContent = state.gpuAvailable 
      ? "GPU available for faster processing." 
      : "No GPU detected. Using CPU.";
  }
}

// Batch diarization helpers
function setBatchDiarizationOutput(message) {
  const output = document.getElementById("batch-diarization-output");
  if (output) output.textContent = message;
}

function updateBatchDiarizationUI() {
  const enabled = document.getElementById("batch-diarization-enabled").checked;
  const providerSelect = document.getElementById("batch-diarization-provider");
  const modelRow = document.getElementById("batch-diarization-model")?.closest(".row");
  const deviceRow = document.getElementById("batch-device-row");
  const tokenRow = document.getElementById("batch-token-row");
  
  const showFields = enabled && providerSelect.value !== "none";
  const showModel = showFields && providerSelect.value === "pyannote";
  
  if (modelRow) modelRow.style.display = showModel ? "block" : "none";
  if (deviceRow) deviceRow.style.display = showFields ? "block" : "none";
  if (tokenRow) tokenRow.style.display = showFields ? "block" : "none";
  
  // Update GPU hint
  const gpuHint = document.getElementById("batch-gpu-hint");
  if (gpuHint) {
    gpuHint.textContent = state.gpuAvailable 
      ? "GPU available for faster processing." 
      : "No GPU detected. Processing may be slow.";
  }
}

// Legacy functions for backwards compatibility
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
  // Legacy - redirect to batch output
  setBatchDiarizationOutput(message);
}

function updateDiarizationUI() {
  // Legacy - update both UIs
  updateRealtimeDiarizationUI();
  updateBatchDiarizationUI();
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
  // Only show visible models from enabled providers
  const models = state.registry.filter((model) => model.visible && isProviderEnabled(model.provider));
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

function isProviderEnabled(provider) {
  const checkbox = document.getElementById(`${provider}-enabled`);
  return checkbox ? checkbox.checked : true; // Default to enabled if checkbox not found
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
    // Filter out models from disabled providers
    if (!isProviderEnabled(model.provider)) {
      return false;
    }
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
      if (result.can_launch && provider === "ollama") {
        _showOllamaLaunchOffer(payload, result.message);
        setProviderStatus(provider, false);
        return;
      }
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

function _showOllamaLaunchOffer(payload, errorMsg) {
  const output = document.getElementById("model-output");
  if (!output) return;
  output.textContent = "";

  const msg = document.createElement("span");
  msg.textContent = errorMsg + " ";
  output.appendChild(msg);

  const btn = document.createElement("button");
  btn.textContent = "Launch Ollama";
  btn.className = "primary small";
  btn.style.marginLeft = "8px";
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "Launching...";
    setGlobalBusy("Launching Ollama...");
    try {
      const result = await fetchJson("/api/settings/ollama/launch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (result.status === "ok") {
        setModelOptions("ollama", result.models || []);
        updateRegistryFromProvider("ollama");
        syncModelChoiceFromConfig();
        setModelOutput(`ollama OK. ${result.models?.length || 0} models.`);
        setProviderStatus("ollama", true);
        scheduleSave(saveSummarizationSettings);
      } else {
        setModelOutput(`Launch failed: ${result.message}`);
        setProviderStatus("ollama", false);
      }
    } catch (err) {
      setModelOutput(`Launch failed: ${err.message}`);
      setProviderStatus("ollama", false);
    } finally {
      setGlobalBusy("");
    }
  });
  output.appendChild(btn);
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
    document.getElementById("consolidation-max-duration").value =
      data.consolidation_max_duration ?? 15;
    document.getElementById("consolidation-max-gap").value =
      data.consolidation_max_gap ?? 2;
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

async function saveRealtimeDiarizationSettings() {
  const enabled = document.getElementById("realtime-diarization-enabled").checked;
  const provider = document.getElementById("realtime-diarization-provider").value;
  const device = document.getElementById("realtime-diarization-device").value;
  const performanceLevel = parseFloat(document.getElementById("realtime-performance-level").value);
  const hfToken = document.getElementById("realtime-hf-token").value.trim();

  setRealtimeDiarizationOutput("Saving real-time diarization settings...");
  setGlobalBusy("Saving real-time diarization settings...");
  try {
    await fetchJson("/api/settings/diarization/realtime", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled: enabled && provider !== "none",
        provider: provider,
        device: device,
        hf_token: hfToken || null,
        performance_level: performanceLevel,
      }),
    });
    setRealtimeDiarizationOutput("Real-time diarization settings saved.");
  } catch (error) {
    setRealtimeDiarizationOutput(`Failed to save: ${error.message}`);
    setGlobalError("Real-time diarization save failed.");
  } finally {
    setGlobalBusy("");
  }
}

async function saveBatchDiarizationSettings() {
  const enabled = document.getElementById("batch-diarization-enabled").checked;
  const provider = document.getElementById("batch-diarization-provider").value;
  const model = document.getElementById("batch-diarization-model").value;
  const device = document.getElementById("batch-diarization-device").value;
  const hfToken = document.getElementById("batch-hf-token").value.trim();

  setBatchDiarizationOutput("Saving batch diarization settings...");
  setGlobalBusy("Saving batch diarization settings...");
  try {
    await fetchJson("/api/settings/diarization/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled: enabled && provider !== "none",
        provider: provider,
        model: model,
        device: device,
        hf_token: hfToken || null,
      }),
    });
    setBatchDiarizationOutput("Batch diarization settings saved.");
  } catch (error) {
    setBatchDiarizationOutput(`Failed to save: ${error.message}`);
    setGlobalError("Batch diarization save failed.");
  } finally {
    setGlobalBusy("");
  }
}

// Legacy function - now saves both settings
async function saveDiarizationSettings() {
  await saveRealtimeDiarizationSettings();
  await saveBatchDiarizationSettings();
}

async function saveTranscriptionSettings() {
  const payload = {
    live_model_size: document.getElementById("live-model-size").value,
    final_model_size: document.getElementById("final-model-size").value,
    auto_transcribe: document.getElementById("auto-transcribe").checked,
    stream_transcribe: document.getElementById("stream-transcribe").checked,
    live_transcribe: document.getElementById("live-transcribe").checked,
    consolidation_max_duration: parseFloat(document.getElementById("consolidation-max-duration").value) || 15,
    consolidation_max_gap: parseFloat(document.getElementById("consolidation-max-gap").value) || 2,
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

function updateProviderUI(provider) {
  const enabledCheckbox = document.getElementById(`${provider}-enabled`);
  const settingsDiv = document.getElementById(`${provider}-settings`);
  const block = document.getElementById(`${provider}-block`);
  if (!enabledCheckbox || !settingsDiv || !block) return;
  
  const isEnabled = enabledCheckbox.checked;
  if (isEnabled) {
    settingsDiv.classList.remove("collapsed");
    block.classList.remove("disabled");
  } else {
    settingsDiv.classList.add("collapsed");
    block.classList.add("disabled");
  }
}

async function loadSummarizationSettings() {
  try {
    const data = await fetchJson("/api/settings/providers");
    if (!data || Object.keys(data).length === 0) {
      return;
    }
    // Load enabled state and settings for each provider
    const providers = ["openai", "anthropic", "gemini", "grok", "ollama", "lmstudio"];
    for (const provider of providers) {
      const enabledCheckbox = document.getElementById(`${provider}-enabled`);
      if (enabledCheckbox) {
        // Default to true if enabled field is not set (backward compatibility)
        enabledCheckbox.checked = data[provider]?.enabled !== false;
        updateProviderUI(provider);
      }
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

async function loadRealtimeDiarizationSettings() {
  try {
    const data = await fetchJson("/api/settings/diarization/realtime");
    
    // Store GPU availability for recommendations
    state.gpuAvailable = data?.gpu_available ?? false;

    document.getElementById("realtime-diarization-enabled").checked = data.enabled || false;
    document.getElementById("realtime-diarization-provider").value = data.provider || "none";
    document.getElementById("realtime-diarization-device").value = data.device || "cpu";
    document.getElementById("realtime-performance-level").value = data.performance_level ?? 0.5;
    document.getElementById("realtime-hf-token").value = data.hf_token || "";
    
    updateRealtimeDiarizationUI();
  } catch (error) {
    setGlobalError(`Failed to load real-time diarization settings: ${error.message}`);
  }
}

async function loadBatchDiarizationSettings() {
  try {
    const data = await fetchJson("/api/settings/diarization/batch");
    
    // Store GPU availability for recommendations
    state.gpuAvailable = data?.gpu_available ?? false;

    document.getElementById("batch-diarization-enabled").checked = data.enabled || false;
    document.getElementById("batch-diarization-provider").value = data.provider || "none";
    document.getElementById("batch-diarization-model").value = data.model || "pyannote/speaker-diarization-3.1";
    document.getElementById("batch-diarization-device").value = data.device || "cpu";
    document.getElementById("batch-hf-token").value = data.hf_token || "";
    
    updateBatchDiarizationUI();
  } catch (error) {
    setGlobalError(`Failed to load batch diarization settings: ${error.message}`);
  }
}

// Legacy function - now loads both settings
async function loadDiarizationSettings() {
  await loadRealtimeDiarizationSettings();
  await loadBatchDiarizationSettings();
}

async function testDiarizationAccess() {
  setBatchDiarizationOutput("Testing HuggingFace access...");
  setGlobalBusy("Testing HuggingFace access...");
  try {
    const result = await fetchJson("/api/settings/diarization/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (result.status === "ok") {
      setBatchDiarizationOutput("All models accessible. You're ready to use diarization.");
    } else {
      let msg = result.message || "Test failed";
      if (result.models) {
        const issues = result.models
          .filter(m => m.status !== "ok")
          .map(m => `${m.model}: ${m.message}`)
          .join("\n");
        if (issues) msg += "\n" + issues;
      }
      setBatchDiarizationOutput(msg);
    }
  } catch (error) {
    setBatchDiarizationOutput(`Test failed: ${error.message}`);
  } finally {
    setGlobalBusy("");
  }
}

async function saveSummarizationSettings() {
  syncConfigFromModelChoice();
  const payload = {
    openai: {
      enabled: document.getElementById("openai-enabled").checked,
      api_key: document.getElementById("openai-api-key").value.trim(),
      base_url: document.getElementById("openai-base-url").value.trim(),
    },
    anthropic: {
      enabled: document.getElementById("anthropic-enabled").checked,
      api_key: document.getElementById("anthropic-api-key").value.trim(),
      base_url: document.getElementById("anthropic-base-url").value.trim(),
    },
    gemini: {
      enabled: document.getElementById("gemini-enabled").checked,
      api_key: document.getElementById("gemini-api-key").value.trim(),
      base_url: document.getElementById("gemini-base-url").value.trim(),
    },
    grok: {
      enabled: document.getElementById("grok-enabled").checked,
      api_key: document.getElementById("grok-api-key").value.trim(),
      base_url: document.getElementById("grok-base-url").value.trim(),
    },
    ollama: {
      enabled: document.getElementById("ollama-enabled").checked,
      api_key: document.getElementById("ollama-api-key").value.trim(),
      base_url: document.getElementById("ollama-base-url").value.trim(),
    },
    lmstudio: {
      enabled: document.getElementById("lmstudio-enabled").checked,
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

// ── Settings tab navigation ───────────────────────────────────────────
function initSettingsTabs() {
  const STORAGE_KEY = "notetaker-settings-tab";
  const tabs = document.querySelectorAll(".settings-tab");
  const panes = document.querySelectorAll(".settings-tab-content");
  if (!tabs.length) return;

  function activate(tabName) {
    tabs.forEach((t) => t.classList.toggle("active", t.dataset.tab === tabName));
    panes.forEach((p) => p.classList.toggle("active", p.dataset.tab === tabName));
    try { localStorage.setItem(STORAGE_KEY, tabName); } catch (_) { /* ok */ }
  }

  tabs.forEach((t) => t.addEventListener("click", () => activate(t.dataset.tab)));

  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved && document.querySelector(`.settings-tab[data-tab="${saved}"]`)) {
    activate(saved);
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  // Tab navigation (must run before async loads so the right pane is visible)
  initSettingsTabs();

  // Provider enabled toggles
  const providers = ["openai", "anthropic", "gemini", "grok", "ollama", "lmstudio"];
  for (const provider of providers) {
    const toggle = document.getElementById(`${provider}-enabled`);
    if (toggle) {
      toggle.addEventListener("change", () => {
        updateProviderUI(provider);
        renderRegistry();
        renderModelDatalist();
        scheduleSave(saveSummarizationSettings);
      });
    }
  }
  
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
  // Real-time diarization event listeners
  document
    .getElementById("realtime-diarization-enabled")
    .addEventListener("change", () => {
      updateRealtimeDiarizationUI();
      scheduleSave(saveRealtimeDiarizationSettings);
    });
  document
    .getElementById("realtime-diarization-provider")
    .addEventListener("change", () => {
      updateRealtimeDiarizationUI();
      scheduleSave(saveRealtimeDiarizationSettings);
    });
  document
    .getElementById("realtime-diarization-device")
    .addEventListener("change", () => scheduleSave(saveRealtimeDiarizationSettings));
  document
    .getElementById("realtime-performance-level")
    .addEventListener("input", () => scheduleSave(saveRealtimeDiarizationSettings, 500));
  document
    .getElementById("realtime-hf-token")
    .addEventListener("input", () => scheduleSave(saveRealtimeDiarizationSettings, 800));

  // Batch diarization event listeners
  document
    .getElementById("batch-diarization-enabled")
    .addEventListener("change", () => {
      updateBatchDiarizationUI();
      scheduleSave(saveBatchDiarizationSettings);
    });
  document
    .getElementById("batch-diarization-provider")
    .addEventListener("change", () => {
      updateBatchDiarizationUI();
      scheduleSave(saveBatchDiarizationSettings);
    });
  document
    .getElementById("batch-diarization-model")
    .addEventListener("change", () => scheduleSave(saveBatchDiarizationSettings));
  document
    .getElementById("batch-diarization-device")
    .addEventListener("change", () => scheduleSave(saveBatchDiarizationSettings));
  document
    .getElementById("batch-hf-token")
    .addEventListener("input", () => scheduleSave(saveBatchDiarizationSettings, 800));
  document
    .getElementById("test-diarization-access")
    .addEventListener("click", testDiarizationAccess);
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
    .getElementById("consolidation-max-duration")
    .addEventListener("change", () => scheduleSave(saveTranscriptionSettings));
  document
    .getElementById("consolidation-max-gap")
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

  // Theme selector
  const themeSelect = document.getElementById("theme-select");
  if (themeSelect) {
    themeSelect.addEventListener("change", () => {
      const theme = themeSelect.value;
      // Apply immediately via theme.js
      if (window.NotetakerTheme) {
        window.NotetakerTheme.set(theme);
      }
      // Save to server
      scheduleSave(() => saveAppearanceSettings());
    });
  }

  await refreshVersion();
  await refreshDevices();
  await loadAudioSettings();
  await loadTranscriptionSettings();
  await loadSummarizationSettings();
  await loadDiarizationSettings();
  await loadAppearanceSettings();

  // Data folder
  dataDirInit();
  await dataDirLoad();

  // HuggingFace model downloads
  hfInitEvents();
  await hfLoadModels();

  // Initialize debug flags UI and load settings
  initDebugFlagsUI();
  await loadDebugFlags();
  
  // Initialize debug section (test/debug infrastructure)
  testInitDebugSection();
});

// ── HuggingFace model management ──────────────────────────────────────

let _hfModels = [];

async function hfLoadModels() {
  const container = document.getElementById("hf-models-list");
  if (!container) return;
  try {
    const data = await fetchJson("/api/settings/hf-models");
    _hfModels = data.models || [];

    // Global toggle
    const cb = document.getElementById("hf-auto-download");
    if (cb) cb.checked = !!data.auto_download;

    hfRender();
  } catch (err) {
    container.innerHTML = `<div class="hint">Failed to load models: ${err.message}</div>`;
    debugError("hfLoadModels", err);
  }
}

function hfInitEvents() {
  const cb = document.getElementById("hf-auto-download");
  if (cb) cb.addEventListener("change", () => hfSetGlobal(cb.checked));

  const checkAll = document.getElementById("hf-check-all");
  if (checkAll) checkAll.addEventListener("click", hfCheckAll);
}

async function hfSetGlobal(enabled) {
  try {
    await fetchJson("/api/settings/hf-models/global", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_download: enabled }),
    });
  } catch (err) {
    debugError("hfSetGlobal", err);
  }
}

function hfRender() {
  const container = document.getElementById("hf-models-list");
  if (!container) return;
  if (!_hfModels.length) {
    container.innerHTML = '<div class="hint">No HuggingFace models found.</div>';
    return;
  }

  let html = "";
  let lastGroup = "";
  for (const m of _hfModels) {
    if (m.group !== lastGroup) {
      lastGroup = m.group;
      html += `<div class="hf-group-label">${lastGroup}</div>`;
    }

    const cached = m.cached;
    const sizeTxt = cached ? `${m.size_mb} MB` : "not downloaded";
    const statusCls = cached ? "cached" : "not-cached";
    const statusTxt = cached ? "Cached" : "Not cached";
    const gatedBadge = m.gated ? '<span class="hf-badge gated">gated</span>' : "";

    html += `
      <div class="hf-model-row" data-model-id="${m.id}">
        <div class="hf-model-info">
          <div class="hf-model-name">${m.label}${gatedBadge}</div>
          <div class="hf-model-meta">${m.id} · ${sizeTxt}</div>
          <div class="hf-model-status ${statusCls}" data-hf-status="${m.id}">${statusTxt}</div>
        </div>
        <div class="hf-model-actions">
          <button class="secondary small" data-hf-check="${m.id}">Check</button>
          <button class="secondary small" data-hf-download="${m.id}" style="display:none">Download</button>
        </div>
      </div>`;
  }
  container.innerHTML = html;

  container.querySelectorAll("[data-hf-check]").forEach((el) => {
    el.addEventListener("click", () => hfCheck(el.dataset.hfCheck));
  });
  container.querySelectorAll("[data-hf-download]").forEach((el) => {
    el.addEventListener("click", () => hfDownload(el.dataset.hfDownload));
  });
}

function _hfSetStatus(modelId, text, cls) {
  const el = document.querySelector(`[data-hf-status="${modelId}"]`);
  if (el) {
    el.textContent = text;
    el.className = `hf-model-status ${cls || ""}`;
  }
}

function _hfShowDownload(modelId, show) {
  const btn = document.querySelector(`[data-hf-download="${modelId}"]`);
  if (btn) btn.style.display = show ? "inline-block" : "none";
}

async function hfCheck(modelId) {
  _hfSetStatus(modelId, "Checking…", "");
  try {
    const c = await fetchJson("/api/settings/hf-models/check-update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: modelId }),
    });
    if (c.error) {
      _hfSetStatus(modelId, c.message, "error");
    } else if (c.update_available) {
      _hfSetStatus(modelId, c.message, "update-available");
      _hfShowDownload(modelId, true);
    } else {
      _hfSetStatus(modelId, c.message, "cached");
      _hfShowDownload(modelId, false);
    }
  } catch (err) {
    _hfSetStatus(modelId, `Error: ${err.message}`, "error");
    debugError("hfCheck", err);
  }
}

async function hfCheckAll() {
  for (const m of _hfModels) {
    await hfCheck(m.id);
  }
}

async function hfDownload(modelId) {
  const btn = document.querySelector(`[data-hf-download="${modelId}"]`);
  if (btn) {
    btn.textContent = "Downloading…";
    btn.classList.add("downloading");
  }
  _hfSetStatus(modelId, "Downloading…", "");
  try {
    const d = await fetchJson("/api/settings/hf-models/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: modelId }),
    });
    if (d.status === "ok") {
      _hfSetStatus(modelId, `Downloaded · ${d.size_mb || "?"} MB`, "cached");
      _hfShowDownload(modelId, false);
      await hfLoadModels();
    } else {
      _hfSetStatus(modelId, d.message || "Download failed", "error");
    }
  } catch (err) {
    _hfSetStatus(modelId, `Error: ${err.message}`, "error");
    debugError("hfDownload", err);
  } finally {
    if (btn) {
      btn.textContent = "Download";
      btn.classList.remove("downloading");
    }
  }
}

// ── Appearance settings ───────────────────────────────────────────────

async function loadAppearanceSettings() {
  try {
    const response = await fetch("/api/settings/appearance");
    if (!response.ok) {
      return;
    }
    const data = await response.json();
    const themeSelect = document.getElementById("theme-select");
    if (themeSelect && data.theme) {
      themeSelect.value = data.theme;
      // Sync with theme.js (in case localStorage differs from server)
      if (window.NotetakerTheme) {
        window.NotetakerTheme.syncFromServer(data.theme);
      }
    }
  } catch (error) {
    debugError("Failed to load appearance settings", error);
  }
}

async function saveAppearanceSettings() {
  const themeSelect = document.getElementById("theme-select");
  if (!themeSelect) {
    return;
  }
  try {
    const response = await fetch("/api/settings/appearance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        theme: themeSelect.value,
      }),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    debugLog("Appearance settings saved");
  } catch (error) {
    debugError("Failed to save appearance settings", error);
  }
}

// =============================================================================
// Debug Flags Functions
// =============================================================================

async function loadDebugFlags() {
  try {
    const response = await fetch("/api/settings/debug");
    if (!response.ok) return;
    const data = await response.json();
    
    // Sync with frontend debug module
    if (window.NotetakerDebug) {
      window.NotetakerDebug.syncFromServer(data);
    }
    
    // Update master toggle
    const masterToggle = document.getElementById("debug-master-toggle");
    if (masterToggle) {
      masterToggle.checked = data.enabled || false;
    }
    
    // Render individual flags
    renderDebugFlags(data.definitions || {}, data.flags || {});
  } catch (error) {
    debugError("Failed to load debug flags", error);
  }
}

function renderDebugFlags(definitions, currentFlags) {
  const container = document.getElementById("debug-flags-list");
  if (!container) return;
  
  container.innerHTML = Object.entries(definitions).map(([flag, def]) => {
    const isEnabled = currentFlags[flag] ?? def.default;
    return `
      <div class="debug-flag-item">
        <label>
          <input type="checkbox" data-flag="${flag}" ${isEnabled ? "checked" : ""} />
          <span class="debug-flag-name">${flag}</span>
        </label>
        <span class="debug-flag-desc">${def.desc}</span>
      </div>
    `;
  }).join("");
  
  // Add change handlers for individual toggles
  container.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
    checkbox.addEventListener("change", () => {
      const flag = checkbox.dataset.flag;
      if (window.NotetakerDebug) {
        window.NotetakerDebug.setFlag(flag, checkbox.checked);
      }
    });
  });
}

function initDebugFlagsUI() {
  // Master toggle
  const masterToggle = document.getElementById("debug-master-toggle");
  if (masterToggle) {
    masterToggle.addEventListener("change", () => {
      if (window.NotetakerDebug) {
        window.NotetakerDebug.setEnabled(masterToggle.checked);
      }
    });
  }
  
  // All On button
  const allOnBtn = document.getElementById("debug-flags-all-on");
  if (allOnBtn) {
    allOnBtn.addEventListener("click", () => {
      if (window.NotetakerDebug) {
        window.NotetakerDebug.setAllFlags(true);
      }
      // Update checkboxes
      document.querySelectorAll("#debug-flags-list input[type='checkbox']").forEach(cb => {
        cb.checked = true;
      });
    });
  }
  
  // All Off button
  const allOffBtn = document.getElementById("debug-flags-all-off");
  if (allOffBtn) {
    allOffBtn.addEventListener("click", () => {
      if (window.NotetakerDebug) {
        window.NotetakerDebug.setAllFlags(false);
      }
      // Update checkboxes
      document.querySelectorAll("#debug-flags-list input[type='checkbox']").forEach(cb => {
        cb.checked = false;
      });
    });
  }
}

// =============================================================================
// Debug/Test Functions (test_ prefix indicates debug infrastructure)
// =============================================================================

async function testLoadRagMetrics() {
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'settings.js:testLoadRagMetrics',message:'api_call_start',data:{},timestamp:Date.now(),runId:'frontend',hypothesisId:'H4'})}).catch(()=>{});
  // #endregion
  try {
    const response = await fetch("/api/test/rag-metrics");
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'settings.js:testLoadRagMetrics',message:'api_response',data:{status:response.status,ok:response.ok},timestamp:Date.now(),runId:'frontend',hypothesisId:'H4'})}).catch(()=>{});
    // #endregion
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'settings.js:testLoadRagMetrics',message:'api_data',data:{total_queries:data?.aggregate?.total_queries,recent_count:data?.recent?.length},timestamp:Date.now(),runId:'frontend',hypothesisId:'H4'})}).catch(()=>{});
    // #endregion
    
    // Update aggregate stats
    const agg = data.aggregate || {};
    document.getElementById("test-rag-total-queries").textContent = agg.total_queries ?? 0;
    document.getElementById("test-rag-avg-duration").textContent = (agg.avg_duration_ms ?? 0) + "ms";
    document.getElementById("test-rag-avg-input").textContent = agg.avg_input_tokens ?? 0;
    document.getElementById("test-rag-avg-output").textContent = agg.avg_output_tokens ?? 0;
    document.getElementById("test-rag-avg-meetings").textContent = agg.avg_meetings_loaded ?? 0;
    document.getElementById("test-rag-avg-search").textContent = agg.avg_search_calls ?? 0;
    
    // Update recent queries table
    const tbody = document.getElementById("test-rag-recent-body");
    const recent = data.recent || [];
    
    if (recent.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty">No queries yet</td></tr>';
    } else {
      tbody.innerHTML = recent.map(q => {
        const time = q.timestamp ? new Date(q.timestamp).toLocaleTimeString() : "-";
        return `<tr>
          <td>${time}</td>
          <td>${q.query_type || "-"}</td>
          <td>${q.duration_ms ?? 0}ms</td>
          <td>${q.input_tokens ?? 0}</td>
          <td>${q.output_tokens ?? 0}</td>
          <td>${q.meetings_loaded ?? 0}</td>
        </tr>`;
      }).join("");
    }
  } catch (error) {
    debugError("Failed to load RAG metrics", error);
  }
}

async function testResetRagMetrics() {
  try {
    const response = await fetch("/api/test/rag-metrics/reset", { method: "POST" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await testLoadRagMetrics();
  } catch (error) {
    debugError("Failed to reset RAG metrics", error);
  }
}

async function testLoadLlmLogs() {
  try {
    const response = await fetch("/api/test/llm-logs");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    
    const container = document.getElementById("test-llm-log-list");
    const logs = data.logs || [];
    
    if (logs.length === 0) {
      container.innerHTML = '<div class="empty">No log files</div>';
    } else {
      container.innerHTML = logs.map(log => `
        <div class="debug-log-item" data-filename="${log.filename}">
          <span class="debug-log-name">${log.filename}</span>
          <span class="debug-log-size">${(log.size / 1024).toFixed(1)}KB</span>
        </div>
      `).join("");
      
      // Add click handlers
      container.querySelectorAll(".debug-log-item").forEach(item => {
        item.addEventListener("click", () => testViewLog(item.dataset.filename));
      });
    }
  } catch (error) {
    debugError("Failed to load LLM logs", error);
  }
}

async function testViewLog(filename) {
  try {
    const response = await fetch(`/api/test/llm-logs/${encodeURIComponent(filename)}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    
    document.getElementById("test-llm-log-filename").textContent = filename;
    document.getElementById("test-llm-log-content").textContent = data.content || "(empty)";
    document.getElementById("test-llm-log-viewer").style.display = "block";
  } catch (error) {
    debugError("Failed to view log", error);
  }
}

function testCloseLogViewer() {
  document.getElementById("test-llm-log-viewer").style.display = "none";
}

async function testClearLlmLogs() {
  if (!confirm("Delete all LLM log files?")) return;
  
  try {
    const response = await fetch("/api/test/llm-logs", { method: "DELETE" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await testLoadLlmLogs();
    testCloseLogViewer();
  } catch (error) {
    debugError("Failed to clear LLM logs", error);
  }
}

async function testLoadLogAllStatus() {
  try {
    const response = await fetch("/api/test/llm-logging");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    
    const checkbox = document.getElementById("test-log-all-enabled");
    if (checkbox) checkbox.checked = data.enabled || false;
  } catch (error) {
    debugError("Failed to load log-all status", error);
  }
}

async function testToggleLogAll(enabled) {
  try {
    const response = await fetch("/api/test/llm-logging", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
  } catch (error) {
    debugError("Failed to toggle log-all", error);
  }
}

function testInitDebugSection() {
  // RAG metrics buttons
  const refreshBtn = document.getElementById("test-refresh-rag-metrics");
  const resetBtn = document.getElementById("test-reset-rag-metrics");
  if (refreshBtn) refreshBtn.addEventListener("click", testLoadRagMetrics);
  if (resetBtn) resetBtn.addEventListener("click", testResetRagMetrics);
  
  // LLM logging buttons
  const refreshLogsBtn = document.getElementById("test-refresh-llm-logs");
  const clearLogsBtn = document.getElementById("test-clear-llm-logs");
  const closeLogBtn = document.getElementById("test-llm-log-close");
  if (refreshLogsBtn) refreshLogsBtn.addEventListener("click", testLoadLlmLogs);
  if (clearLogsBtn) clearLogsBtn.addEventListener("click", testClearLlmLogs);
  if (closeLogBtn) closeLogBtn.addEventListener("click", testCloseLogViewer);
  
  // Log-all toggle
  const logAllCheckbox = document.getElementById("test-log-all-enabled");
  if (logAllCheckbox) {
    logAllCheckbox.addEventListener("change", () => testToggleLogAll(logAllCheckbox.checked));
  }
  
  // Finalization controls
  const restartFinalizationBtn = document.getElementById("restart-finalization-btn");
  const refreshFinalizationBtn = document.getElementById("refresh-finalization-btn");
  if (restartFinalizationBtn) restartFinalizationBtn.addEventListener("click", restartFinalization);
  if (refreshFinalizationBtn) refreshFinalizationBtn.addEventListener("click", loadFinalizationStatus);
  
  // Initial load
  testLoadRagMetrics();
  testLoadLlmLogs();
  testLoadLogAllStatus();
  loadFinalizationStatus();
}

// =============================================================================
// Finalization Status Functions
// =============================================================================

async function loadFinalizationStatus() {
  try {
    const response = await fetch("/api/test/finalization-status");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    
    // Update status text
    const statusEl = document.getElementById("finalization-status-text");
    if (statusEl) {
      if (data.error) {
        statusEl.textContent = "Unavailable";
      } else if (data.active) {
        statusEl.textContent = "Active";
      } else if (data.running) {
        statusEl.textContent = "Idle";
      } else {
        statusEl.textContent = "Stopped";
      }
    }
    
    // Update pending count
    const pendingEl = document.getElementById("finalization-pending-count");
    if (pendingEl) {
      pendingEl.textContent = data.pending_count ?? 0;
    }
    
    // Show/hide current work info
    const currentWorkEl = document.getElementById("finalization-current-work");
    const currentMeetingEl = document.getElementById("finalization-current-meeting");
    const currentStageEl = document.getElementById("finalization-current-stage");
    
    if (currentWorkEl) {
      if (data.active && data.current_meeting_id) {
        currentWorkEl.style.display = "block";
        if (currentMeetingEl) currentMeetingEl.textContent = data.current_meeting_id.slice(0, 8) + "...";
        if (currentStageEl) currentStageEl.textContent = data.current_stage || "unknown";
      } else {
        currentWorkEl.style.display = "none";
      }
    }
    
    // Update restart button state
    const restartBtn = document.getElementById("restart-finalization-btn");
    if (restartBtn) {
      restartBtn.disabled = data.active || data.error;
      restartBtn.textContent = data.active ? "Finalization Running..." : "Restart Finalization";
    }
  } catch (error) {
    debugError("Failed to load finalization status", error);
    
    const statusEl = document.getElementById("finalization-status-text");
    if (statusEl) statusEl.textContent = "Error";
    
    const restartBtn = document.getElementById("restart-finalization-btn");
    if (restartBtn) restartBtn.disabled = true;
  }
}

async function restartFinalization() {
  const restartBtn = document.getElementById("restart-finalization-btn");
  if (restartBtn) {
    restartBtn.disabled = true;
    restartBtn.textContent = "Restarting...";
  }
  
  try {
    const response = await fetch("/api/test/restart-finalization", { method: "POST" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    
    if (data.status === "ok") {
      NotificationCenter.success("Finalization restarted");
    } else if (data.status === "already_active") {
      NotificationCenter.info("Finalization already in progress");
    }
    
    // Refresh status after a short delay
    setTimeout(loadFinalizationStatus, 1000);
  } catch (error) {
    debugError("Failed to restart finalization", error);
    NotificationCenter.error(`Failed to restart finalization: ${error.message}`);
  } finally {
    if (restartBtn) {
      restartBtn.textContent = "Restart Finalization";
    }
    // Refresh status to get accurate state
    await loadFinalizationStatus();
  }
}

// ── Data folder configuration ─────────────────────────────────────────

let _dataDirCurrent = "";
let _dataDirDefault = "";
let _folderBrowserPath = "";
let _folderBrowserSelected = "";

async function dataDirLoad() {
  try {
    const resp = await fetch("/api/settings/data-dir");
    if (!resp.ok) return;
    const data = await resp.json();
    _dataDirCurrent = data.data_dir || "";
    _dataDirDefault = data.default_data_dir || "";
    const input = document.getElementById("data-dir-input");
    if (input) input.value = _dataDirCurrent;
  } catch (err) {
    debugError("dataDirLoad", err);
  }
}

function dataDirInit() {
  const browseBtn = document.getElementById("data-dir-browse");
  const resetBtn = document.getElementById("data-dir-reset");
  if (browseBtn) browseBtn.addEventListener("click", () => folderBrowserOpen(_dataDirCurrent || _dataDirDefault));
  if (resetBtn) resetBtn.addEventListener("click", dataDirReset);

  // Modal close buttons
  const closeModal = document.getElementById("folder-browser-close");
  if (closeModal) closeModal.addEventListener("click", folderBrowserClose);
  const closeAction = document.getElementById("data-dir-action-close");
  if (closeAction) closeAction.addEventListener("click", dataDirActionClose);

  // Folder browser buttons
  const upBtn = document.getElementById("folder-browser-up");
  if (upBtn) upBtn.addEventListener("click", folderBrowserUp);
  const newBtn = document.getElementById("folder-browser-new");
  if (newBtn) newBtn.addEventListener("click", folderBrowserNewFolder);
  const selectBtn = document.getElementById("folder-browser-select");
  if (selectBtn) selectBtn.addEventListener("click", folderBrowserSelectCurrent);

  // Action buttons
  const moveBtn = document.getElementById("data-dir-action-move");
  const copyBtn = document.getElementById("data-dir-action-copy");
  const freshBtn = document.getElementById("data-dir-action-fresh");
  if (moveBtn) moveBtn.addEventListener("click", () => dataDirApply("move"));
  if (copyBtn) copyBtn.addEventListener("click", () => dataDirApply("copy"));
  if (freshBtn) freshBtn.addEventListener("click", () => dataDirApply("fresh"));
}

async function dataDirReset() {
  if (!_dataDirDefault) return;
  if (_dataDirCurrent === _dataDirDefault) {
    _dataDirOutput("Already using default folder.", "");
    return;
  }
  dataDirShowActionDialog(_dataDirDefault);
}

function _dataDirOutput(msg, cls) {
  const el = document.getElementById("data-dir-output");
  if (el) {
    el.textContent = msg;
    el.className = "output" + (cls ? " " + cls : "");
  }
}

// ── Folder browser ────────────────────────────────────────────────────

async function folderBrowserOpen(startPath) {
  _folderBrowserSelected = "";
  const modal = document.getElementById("folder-browser-modal");
  if (modal) modal.style.display = "flex";
  await folderBrowserNavigate(startPath || "");
}

function folderBrowserClose() {
  const modal = document.getElementById("folder-browser-modal");
  if (modal) modal.style.display = "none";
}

async function folderBrowserNavigate(path) {
  const listEl = document.getElementById("folder-browser-list");
  const pathEl = document.getElementById("folder-browser-path");
  if (!listEl) return;
  listEl.innerHTML = '<div class="hint">Loading…</div>';

  try {
    const url = "/api/settings/browse-folders" + (path ? "?path=" + encodeURIComponent(path) : "");
    const resp = await fetch(url);
    const data = await resp.json();
    if (data.status === "error") {
      listEl.innerHTML = `<div class="hint">${data.message}</div>`;
      return;
    }
    _folderBrowserPath = data.path;
    _folderBrowserSelected = "";
    if (pathEl) pathEl.textContent = data.path;

    if (!data.dirs || data.dirs.length === 0) {
      listEl.innerHTML = '<div class="hint">No subdirectories</div>';
      return;
    }
    listEl.innerHTML = "";
    for (const dir of data.dirs) {
      const item = document.createElement("div");
      item.className = "folder-browser-item";
      item.textContent = dir.name;
      item.dataset.path = dir.path;
      item.addEventListener("click", () => {
        document.querySelectorAll(".folder-browser-item.selected")
          .forEach(el => el.classList.remove("selected"));
        item.classList.add("selected");
        _folderBrowserSelected = dir.path;
      });
      item.addEventListener("dblclick", () => {
        folderBrowserNavigate(dir.path);
      });
      listEl.appendChild(item);
    }
  } catch (err) {
    listEl.innerHTML = `<div class="hint">Error: ${err.message}</div>`;
    debugError("folderBrowserNavigate", err);
  }
}

function folderBrowserUp() {
  if (!_folderBrowserPath) return;
  const parts = _folderBrowserPath.split("/");
  if (parts.length <= 2) {
    folderBrowserNavigate("/");
  } else {
    parts.pop();
    folderBrowserNavigate(parts.join("/"));
  }
}

async function folderBrowserNewFolder() {
  const name = prompt("New folder name:");
  if (!name || !name.trim()) return;
  const newPath = _folderBrowserPath + "/" + name.trim();
  try {
    const resp = await fetch("/api/settings/data-dir/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_path: newPath, action: "mkdir" }),
    });
    const data = await resp.json();
    if (data.status === "ok") {
      await folderBrowserNavigate(_folderBrowserPath);
    }
  } catch (err) {
    debugError("folderBrowserNewFolder", err);
  }
}

function folderBrowserSelectCurrent() {
  const chosen = _folderBrowserSelected || _folderBrowserPath;
  if (!chosen) return;
  folderBrowserClose();

  if (chosen === _dataDirCurrent) {
    _dataDirOutput("Already using this folder.", "");
    return;
  }
  dataDirShowActionDialog(chosen);
}

// ── Move / Copy / Fresh dialog ────────────────────────────────────────

function dataDirShowActionDialog(newPath) {
  const modal = document.getElementById("data-dir-action-modal");
  const desc = document.getElementById("data-dir-action-desc");
  const output = document.getElementById("data-dir-action-output");
  if (output) { output.textContent = ""; output.className = "output"; }
  if (desc) {
    desc.innerHTML = `Changing data folder from<br><strong>${_dataDirCurrent}</strong><br>to<br><strong>${newPath}</strong>`;
  }
  if (modal) {
    modal.dataset.newPath = newPath;
    modal.style.display = "flex";
  }
}

function dataDirActionClose() {
  const modal = document.getElementById("data-dir-action-modal");
  if (modal) modal.style.display = "none";
}

async function dataDirApply(action) {
  const modal = document.getElementById("data-dir-action-modal");
  const newPath = modal ? modal.dataset.newPath : "";
  if (!newPath) return;

  const output = document.getElementById("data-dir-action-output");
  if (output) { output.textContent = "Working…"; output.className = "output"; }

  // Disable buttons while working
  const btns = document.querySelectorAll(".data-dir-action-buttons button");
  btns.forEach(b => b.disabled = true);

  try {
    const resp = await fetch("/api/settings/data-dir/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_path: newPath, action }),
    });
    const data = await resp.json();
    if (data.status === "ok") {
      dataDirActionClose();
      _dataDirCurrent = newPath;
      const input = document.getElementById("data-dir-input");
      if (input) input.value = newPath;
      _dataDirOutput("Folder changed. All services now using the new location.", "success");
    } else {
      if (output) { output.textContent = data.message || "Failed"; output.className = "output error"; }
    }
  } catch (err) {
    if (output) { output.textContent = "Error: " + err.message; output.className = "output error"; }
    debugError("dataDirApply", err);
  } finally {
    btns.forEach(b => b.disabled = false);
  }
}
