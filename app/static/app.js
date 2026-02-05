const state = {
  devices: [],
  recording: false,
};

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json();
}

function setOutput(message) {
  const output = document.getElementById("recording-output");
  output.textContent = message;
}

function setStatus(message) {
  const status = document.getElementById("recording-status");
  status.textContent = message;
}

function setStatusError(message) {
  const statusError = document.getElementById("status-error");
  statusError.textContent = message;
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

  if (state.devices.length > 0) {
    const initial = state.devices[0];
    document.getElementById("channels").value = Math.min(
      2,
      initial.max_input_channels
    );
  }
}

async function refreshDevices() {
  setOutput("Loading devices...");
  try {
    state.devices = await fetchJson("/api/audio/devices");
    state.devices = state.devices.map((device) => ({
      ...device,
      channels: Math.min(2, device.max_input_channels),
    }));
    renderDevices();
    setOutput(`Loaded ${state.devices.length} devices.`);
  } catch (error) {
    setOutput(`Failed to load devices: ${error.message}`);
  }
}

async function refreshHealth() {
  const statusEl = document.getElementById("health-status");
  const versionBadge = document.getElementById("version-badge");
  try {
    const data = await fetchJson("/api/health");
    statusEl.textContent = `Status: ${data.status} (${data.version})`;
    versionBadge.textContent = data.version;
  } catch (error) {
    statusEl.textContent = `Health check failed: ${error.message}`;
    versionBadge.textContent = "v?.?.?.?";
  }
}

async function refreshRecordingStatus() {
  try {
    const data = await fetchJson("/api/recording/status");
    state.recording = data.recording;
    setStatus(
      data.recording
        ? `Recording ${data.recording_id} since ${data.started_at}`
        : "Not recording"
    );
    setStatusError("");
  } catch (error) {
    setStatus(`Status error: ${error.message}`);
    setStatusError("Status refresh failed. See Console Errors below.");
  }
}

async function refreshLogs() {
  const logOutput = document.getElementById("log-output");
  try {
    const data = await fetchJson("/api/logs/errors");
    if (!data.lines || data.lines.length === 0) {
      logOutput.textContent = "No errors yet.";
      return;
    }
    logOutput.textContent = data.lines.join("\n");
  } catch (error) {
    logOutput.textContent = `Log fetch failed: ${error.message}`;
  }
}

async function startRecording() {
  const select = document.getElementById("device-select");
  const samplerate = Number(document.getElementById("samplerate").value);
  const channels = Number(document.getElementById("channels").value);
  const deviceIndex = Number(select.value);
  const selected = state.devices.find((device) => device.index === deviceIndex);
  const maxChannels = selected ? selected.max_input_channels : channels;
  const safeChannels = Math.min(channels, maxChannels || channels);

  setOutput("Starting recording...");
  setStatusError("");
  try {
    const data = await fetchJson("/api/recording/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        device_index: deviceIndex,
        samplerate,
        channels: safeChannels,
      }),
    });
    setOutput(`Recording started: ${data.recording_id}`);
    await refreshRecordingStatus();
  } catch (error) {
    setOutput(`Failed to start: ${error.message}`);
    setStatusError("Start recording failed. Check Console Errors below.");
  }
}

async function stopRecording() {
  setOutput("Stopping recording...");
  setStatusError("");
  try {
    const data = await fetchJson("/api/recording/stop", {
      method: "POST",
    });
    setOutput(`Recording saved: ${data.file_path}`);
    await refreshRecordingStatus();
  } catch (error) {
    setOutput(`Failed to stop: ${error.message}`);
    setStatusError("Stop recording failed. Check Console Errors below.");
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  document
    .getElementById("refresh-devices")
    .addEventListener("click", refreshDevices);
  document
    .getElementById("start-recording")
    .addEventListener("click", startRecording);
  document
    .getElementById("stop-recording")
    .addEventListener("click", stopRecording);

  await refreshHealth();
  await refreshDevices();
  await refreshRecordingStatus();
  await refreshLogs();

  setInterval(refreshLogs, 5000);
});
