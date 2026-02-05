const state = {
  devices: [],
  recording: false,
  lastRecordingPath: null,
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

function setTranscriptStatus(message) {
  const status = document.getElementById("transcript-status");
  status.textContent = message;
}

function setTranscriptOutput(message) {
  const output = document.getElementById("transcript-output");
  output.textContent = message;
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
    if (data.file_path) {
      state.lastRecordingPath = data.file_path;
    }
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
    if (data.file_path) {
      state.lastRecordingPath = data.file_path;
    }
    await refreshRecordingStatus();
  } catch (error) {
    setOutput(`Failed to start: ${error.message}`);
    setStatusError("Start recording failed. Check Console Errors below.");
  }
}

function buildTranscriptText(segments) {
  return segments
    .map((segment) => {
      const start = segment.start.toFixed(2);
      const end = segment.end.toFixed(2);
      const speaker = segment.speaker ? `[${segment.speaker}] ` : "";
      return `[${start}-${end}] ${speaker}${segment.text}`;
    })
    .join("\n");
}

async function transcribeLatest() {
  const autoToggle = document.getElementById("auto-transcribe");
  const streamToggle = document.getElementById("stream-transcribe");
  if (!state.lastRecordingPath) {
    setTranscriptStatus("No recording found yet.");
    setTranscriptOutput("");
    return;
  }

  setTranscriptStatus("Transcribing...");
  setTranscriptOutput("");
  try {
    if (streamToggle.checked) {
      await streamTranscription(state.lastRecordingPath);
    } else {
      const data = await fetchJson("/api/transcribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audio_path: state.lastRecordingPath }),
      });
      const transcriptText = buildTranscriptText(data.segments || []);
      setTranscriptStatus(
        `Transcript ready (${data.segments.length} segments, ${data.language || "unknown"}).`
      );
      setTranscriptOutput(transcriptText || "Transcript returned no segments.");
    }
  } catch (error) {
    setTranscriptStatus(`Transcription failed: ${error.message}`);
  } finally {
    if (!autoToggle.checked) {
      autoToggle.checked = false;
    }
  }
}

async function streamTranscription(audioPath) {
  const segments = [];
  let language = "unknown";
  let done = false;

  const response = await fetch("/api/transcribe/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audio_path: audioPath }),
  });

  if (!response.ok || !response.body) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (!done) {
    const { value, done: streamDone } = await reader.read();
    if (streamDone) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";

    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) {
        continue;
      }
      const payloadText = line.replace(/^data:\s*/, "");
      if (!payloadText) {
        continue;
      }
      const event = JSON.parse(payloadText);
      if (event.type === "meta") {
        language = event.language || "unknown";
        setTranscriptStatus(`Transcribing... (${language})`);
      } else if (event.type === "segment") {
        segments.push(event);
        setTranscriptOutput(buildTranscriptText(segments));
      } else if (event.type === "done") {
        done = true;
      } else if (event.type === "error") {
        throw new Error(event.message || "Transcription failed");
      }
    }
  }

  setTranscriptStatus(
    `Transcript ready (${segments.length} segments, ${language}).`
  );
}

async function stopRecording() {
  setOutput("Stopping recording...");
  setStatusError("");
  try {
    const data = await fetchJson("/api/recording/stop", {
      method: "POST",
    });
    setOutput(`Recording saved: ${data.file_path}`);
    if (data.file_path) {
      state.lastRecordingPath = data.file_path;
    }
    await refreshRecordingStatus();
    const autoToggle = document.getElementById("auto-transcribe");
    if (autoToggle.checked) {
      await transcribeLatest();
    }
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
  document
    .getElementById("transcribe-latest")
    .addEventListener("click", transcribeLatest);

  await refreshHealth();
  await refreshDevices();
  await refreshRecordingStatus();
  await refreshLogs();
  setTranscriptStatus("No transcript yet.");

  setInterval(refreshLogs, 5000);
});
