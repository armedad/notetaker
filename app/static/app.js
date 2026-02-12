const state = {
  devices: [],
  recording: false,
  lastRecordingPath: null,
  liveController: null,
  meetings: [],
  selectedMeetingId: null,
  lastTranscriptSegments: null,
  testAudioPath: "",
  testAudioName: "",
  testTranscribeController: null,
  testTranscribing: false,
  stopInFlight: false,
  transcriptionSettings: {
    live_model_size: "base",
    final_model_size: "medium",
    auto_transcribe: true,
    stream_transcribe: true,
    live_transcribe: true,
  },
  meetingsEvents: null,
  recordingSource: "device",
  fileMeetingId: null,
};

function debugLog(message, data = {}) {
  console.debug(`[Home] ${message}`, data);
}

function debugError(message, error) {
  console.error(`[Home] ${message}`, error);
}

async function logClientError(message, context = {}) {
  try {
    await fetch("/api/logs/client", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        level: "error",
        message,
        context,
      }),
    });
  } catch (error) {
    console.error("[Home] Failed to log client error", error);
  }
}

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

function setRecordingSourceNote(message) {
  const note = document.getElementById("recording-settings-note");
  if (!note) {
    return;
  }
  note.textContent = message || "";
}

function appendLogLine(message) {
  const logOutput = document.getElementById("log-output");
  if (!logOutput) {
    return;
  }
  const prefix = logOutput.textContent && logOutput.textContent !== "No errors yet."
    ? `${logOutput.textContent}\n`
    : "";
  logOutput.textContent = `${prefix}${message}`;
}

function setTranscriptStatus(message) {
  const status = document.getElementById("transcript-status");
  if (!status) {
    return;
  }
  status.textContent = message;
}

function setTestAudioStatus(message) {
  const status = document.getElementById("test-audio-status");
  if (!status) {
    return;
  }
  status.textContent = message;
}

function setRecordingToggleLabel(recording) {
  const button = document.getElementById("recording-toggle");
  if (!button) {
    return;
  }
  if (state.recordingSource === "file") {
    button.textContent = recording ? "Stop transcription" : "Start transcription";
    return;
  }
  button.textContent = recording ? "Stop recording" : "Start recording";
}

function updateGoToMeetingButton() {
  const btn = document.getElementById("go-to-meeting");
  if (!btn) return;
  
  const meetingId = state.selectedMeetingId || state.fileMeetingId;
  const isRecording = state.recording || state.testTranscribing;
  
  if (isRecording && meetingId) {
    btn.style.display = "inline-block";
    btn.onclick = () => window.location.href = `/meeting?id=${meetingId}`;
  } else {
    btn.style.display = "none";
  }
}

function setTranscriptOutput(message) {
  const output = document.getElementById("transcript-output");
  if (!output) {
    return;
  }
  output.textContent = message;
}

function resetFileInputLabel() {
  const input = document.getElementById("test-audio-upload");
  if (!input) {
    return;
  }
  input.value = "";
}

function bindFilePicker() {
  const button = document.getElementById("file-picker-button");
  const input = document.getElementById("test-audio-upload");
  if (!button || !input) {
    return;
  }
  button.addEventListener("click", () => {
    input.click();
  });
}

function setDiarizationOutput(message) {
  const output = document.getElementById("diarization-output");
  output.textContent = message;
}

function setMeetingDetail(message) {
  const output = document.getElementById("meeting-detail");
  if (!output) {
    return;
  }
  output.textContent = message;
}

function setMeetingTitle(title) {
  const input = document.getElementById("meeting-title");
  if (!input) {
    return;
  }
  input.value = title || "";
}

function setAttendeeEditor(attendees) {
  const editor = document.getElementById("attendee-editor");
  if (!editor) {
    return;
  }
  const lines = (attendees || [])
    .map((attendee) => attendee.name || attendee.label || attendee.id || "")
    .filter((line) => line);
  editor.value = lines.join("\n");
}

function updateMeetingCache(meeting) {
  if (!meeting || !meeting.id) {
    return;
  }
  const existingIndex = state.meetings.findIndex(
    (item) => item.id === meeting.id
  );
  if (existingIndex >= 0) {
    state.meetings[existingIndex] = meeting;
  } else {
    state.meetings.push(meeting);
  }
}

function rerenderTranscript() {
  if (!state.lastTranscriptSegments) {
    return;
  }
  setTranscriptOutput(buildTranscriptText(state.lastTranscriptSegments));
}

function setGlobalError(message) {
  const errorEl = document.getElementById("global-error");
  errorEl.textContent = message || "";
}

function setGlobalBusy(message) {
  const busyEl = document.getElementById("global-busy");
  busyEl.textContent = message || "";
}

function startMeetingsEventStream() {
  if (state.meetingsEvents) {
    return;
  }
  const source = new EventSource("/api/meetings/events");
  state.meetingsEvents = source;
  source.onmessage = (event) => {
    if (!event.data) {
      return;
    }
    let payload = null;
    try {
      payload = JSON.parse(event.data);
    } catch (error) {
      return;
    }
    if (!payload || payload.type === "heartbeat") {
      return;
    }
    debugLog("Meetings SSE event", payload);
    refreshMeetings();
  };
  source.onerror = (error) => {
    debugError("Meetings SSE error", error);
    logClientError("Meetings SSE error", {
      message: error?.message,
      type: error?.type,
    });
    source.close();
    state.meetingsEvents = null;
  };
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
  const select = document.getElementById("device-select");
  if (!select) {
    return;
  }
  setOutput("Loading devices...");
  setGlobalBusy("Loading devices...");
  setGlobalError("");
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
    setGlobalError("Device refresh failed.");
  } finally {
    setGlobalBusy("");
  }
}

async function loadAudioSettings() {
  const select = document.getElementById("device-select");
  if (!select) {
    return;
  }
  try {
    const data = await fetchJson("/api/settings/audio");
    if (data.device_index !== null && data.device_index !== undefined) {
      select.value = data.device_index;
    }
    if (data.samplerate) {
      document.getElementById("samplerate").value = data.samplerate;
    }
    if (data.channels) {
      document.getElementById("channels").value = data.channels;
    }
  } catch (error) {
    setGlobalError("Audio settings load failed.");
  }
}

// Track the first server version we see to detect updates
let initialServerVersion = null;

async function refreshHealth() {
  const statusEl = document.getElementById("health-status");
  const versionBadge = document.getElementById("version-badge");
  try {
    const data = await fetchJson("/api/health");
    statusEl.textContent = `Status: ${data.status} (${data.version})`;
    versionBadge.textContent = data.version;
    
    // Track version changes and show alert if server was updated
    if (data.version) {
      if (initialServerVersion === null) {
        initialServerVersion = data.version;
      } else if (data.version !== initialServerVersion) {
        showVersionUpdateBanner();
      }
    }
  } catch (error) {
    statusEl.textContent = `Health check failed: ${error.message}`;
    versionBadge.textContent = "v?.?.?.?";
    setGlobalError("Health check failed.");
  }
}

function showVersionUpdateBanner() {
  // Only show once
  if (document.getElementById("version-update-banner")) return;
  
  const banner = document.createElement("div");
  banner.id = "version-update-banner";
  banner.innerHTML = `
    <span>A new version is available.</span>
    <button onclick="window.location.reload(true)">Refresh now</button>
    <button onclick="this.parentElement.remove()">Dismiss</button>
  `;
  banner.style.cssText = `
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    background: #2563eb;
    color: white;
    padding: 8px 16px;
    display: flex;
    align-items: center;
    gap: 12px;
    justify-content: center;
    font-size: 14px;
    z-index: 9999;
  `;
  banner.querySelectorAll("button").forEach(btn => {
    btn.style.cssText = `
      background: white;
      color: #2563eb;
      border: none;
      padding: 4px 12px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 13px;
    `;
  });
  document.body.prepend(banner);
}

async function loadTranscriptionSettings() {
  try {
    const data = await fetchJson("/api/settings/transcription");
    if (!data || Object.keys(data).length === 0) {
      return;
    }
    state.transcriptionSettings = {
      ...state.transcriptionSettings,
      live_model_size: data.live_model_size || state.transcriptionSettings.live_model_size,
      final_model_size:
        data.final_model_size || state.transcriptionSettings.final_model_size,
      auto_transcribe:
        data.auto_transcribe ?? state.transcriptionSettings.auto_transcribe,
      stream_transcribe:
        data.stream_transcribe ?? state.transcriptionSettings.stream_transcribe,
      live_transcribe:
        data.live_transcribe ?? state.transcriptionSettings.live_transcribe,
    };
  } catch (error) {
    setGlobalError("Transcription settings load failed.");
  }
}

async function refreshRecordingStatus() {
  try {
    const data = await fetchJson("/api/recording/status");
    state.recording = data.recording;
    if (data.file_path) {
      state.lastRecordingPath = data.file_path;
    }
    setRecordingToggleLabel(state.recording || state.testTranscribing);
    if (state.testTranscribing) {
      setStatus(
        state.fileMeetingId
          ? `Transcribing file (meeting ${state.fileMeetingId})`
          : "Transcribing file"
      );
      setRecordingSourceNote("Recording source: File");
    } else {
      setStatus(
        data.recording
          ? `Recording ${data.recording_id} since ${data.started_at}`
          : "Not recording"
      );
    }
    setStatusError("");
  } catch (error) {
    setStatus(`Status error: ${error.message}`);
    setStatusError("Status refresh failed. See Console Errors below.");
    setGlobalError("Recording status failed.");
  }
  updateGoToMeetingButton();
}

async function loadTestAudioPath() {
  try {
    const data = await fetchJson("/api/settings/testing");
    state.testAudioPath = data.audio_path || "";
    state.testAudioName = data.audio_name || "";
    updateTestAudioUi();
  } catch (error) {
    setGlobalError("Test audio settings load failed.");
  }
}

async function startFileRecording() {
  debugLog("startFileRecording", { audioPath: state.testAudioPath });
  setStatus("Transcribing file...");
  setRecordingSourceNote("Recording source: File");
  setOutput(`Transcribing file: ${state.testAudioName || state.testAudioPath}`);
  state.testTranscribing = true;
  setRecordingToggleLabel(true);
  try {
    const response = await fetchJson("/api/transcribe/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        audio_path: state.testAudioPath,
      }),
    });
    state.fileMeetingId = response.meeting_id || null;
    setStatus(
      response.meeting_id
        ? `Transcribing file (meeting ${response.meeting_id})`
        : "Transcribing file"
    );
    // Navigate to the newly created meeting
    if (response.meeting_id) {
      window.location.href = `/meeting?id=${response.meeting_id}`;
    }
  } catch (error) {
    if (error.name !== "AbortError") {
      setStatusError(`File transcription failed: ${error.message}`);
      setGlobalError("File transcription failed.");
    }
    debugError("file recording failed", error);
  } finally {
    state.testTranscribeController = null;
    await refreshMeetings();
  }
}

async function stopFileRecording() {
  debugLog("stopFileRecording", { audioPath: state.testAudioPath });
  
  // Disable toggle button to prevent multiple clicks
  const toggleBtn = document.getElementById("recording-toggle");
  if (toggleBtn) {
    toggleBtn.disabled = true;
    toggleBtn.textContent = "Stopping...";
  }
  
  setGlobalBusy("Stopping file ingestion...");
  setStatus("Stopped reading file. Finishing transcription of read audio...");
  
  try {
    const result = await fetchJson(
      `/api/transcribe/simulate/stop?audio_path=${encodeURIComponent(
        state.testAudioPath
      )}`,
      { method: "POST" }
    );
    debugLog("File stop requested", { result });
    
    // The stop request returns immediately. File reading has stopped.
    // Transcription of already-read audio continues in background.
    setGlobalBusy("File reading stopped. Finishing transcription...");
    setStatus("File reading stopped. Processing remaining audio...");
    
    // Poll for completion since transcription continues in background
    let attempts = 0;
    const maxAttempts = 120; // 2 minutes max wait
    
    while (attempts < maxAttempts) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      attempts++;
      
      // Check if transcription has stopped
      try {
        const status = await fetchJson(
          `/api/transcribe/simulate/status?audio_path=${encodeURIComponent(state.testAudioPath)}`
        );
        if (status.status === "idle") {
          debugLog("File transcription fully stopped", { attempts });
          break;
        }
      } catch (e) {
        // Status check failed, assume stopped
        break;
      }
      
      // Show progress message
      if (attempts <= 5) {
        setGlobalBusy("Processing remaining read audio...");
      } else if (attempts <= 30) {
        setGlobalBusy(`Finishing transcription... (${attempts}s)`);
      } else {
        setGlobalBusy(`Still processing... (${attempts}s, Whisper uses 30s chunks)`);
      }
    }
    
    state.testTranscribing = false;
    setRecordingToggleLabel(state.recording);
    setOutput("File transcription complete.");
    setStatus("File transcription complete.");
    setRecordingSourceNote("Recording source: File");
    await refreshMeetings();
  } catch (error) {
    setStatusError(`Stop file transcription failed: ${error.message}`);
    debugError("stopFileRecording failed", error);
  } finally {
    setGlobalBusy("");
    if (toggleBtn) {
      toggleBtn.disabled = false;
      setRecordingToggleLabel(false);
    }
  }
}

async function loadAudioSource() {
  try {
    const data = await fetchJson("/api/settings/audio");
    state.recordingSource = data.source || "device";
    setRecordingSourceNote(
      state.recordingSource === "file"
        ? "Recording source: File"
        : "Recording source: Microphone"
    );
    renderRecordingSources();
    const select = document.getElementById("recording-source");
    if (select) {
      select.value = state.recordingSource;
    }
    updateFileSourceVisibility();
  } catch (error) {
    debugError("Audio source load failed", error);
  }
}

function renderRecordingSources() {
  const select = document.getElementById("recording-source");
  if (!select) {
    return;
  }
  select.innerHTML = "";
  const deviceOption = document.createElement("option");
  deviceOption.value = "device";
  deviceOption.textContent = "Microphone";
  select.appendChild(deviceOption);
  state.devices.forEach((device) => {
    const option = document.createElement("option");
    option.value = `device:${device.index}`;
    option.textContent = device.name;
    select.appendChild(option);
  });
  const fileOption = document.createElement("option");
  fileOption.value = "file";
  fileOption.textContent = "File";
  select.appendChild(fileOption);

  if (state.recordingSource === "file") {
    select.value = "file";
  } else if (state.recordingSource === "device") {
    select.value = "device";
  } else if (state.recordingSource?.startsWith("device:")) {
    select.value = state.recordingSource;
  }
}

function updateFileSourceVisibility() {
  const row = document.getElementById("file-source-row");
  if (!row) {
    return;
  }
  row.classList.toggle("hidden", state.recordingSource !== "file");
}

async function saveAudioSource(source, deviceIndex) {
  await fetchJson("/api/settings/audio", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source,
      device_index: deviceIndex,
    }),
  });
}

async function syncTestTranscriptionStatus() {
  if (!state.testAudioPath) {
    return;
  }
  debugLog("syncTestTranscriptionStatus", { audioPath: state.testAudioPath });
  try {
    const status = await fetchJson(
      `/api/transcribe/simulate/status?audio_path=${encodeURIComponent(
        state.testAudioPath
      )}`
    );
    debugLog("simulate status", status);
    if (status.status === "running") {
      state.testTranscribing = true;
      state.recordingSource = "file";
      state.fileMeetingId = status.meeting_id || state.fileMeetingId;
      setRecordingToggleLabel(true);
      setRecordingSourceNote("Recording source: File");
      setStatus(
        status.meeting_id
          ? `Transcribing file (meeting ${status.meeting_id})`
          : "Transcribing file"
      );
      return;
    }
    state.testTranscribing = false;
    setRecordingToggleLabel(state.recording);
  } catch (error) {
    debugError("syncTestTranscriptionStatus failed", error);
    logClientError("Test transcription status check failed", {
      message: error.message,
      stack: error.stack,
      name: error.name,
    });
  }
}

async function saveTestAudioSelection(audioPath, audioName) {
  try {
    await fetchJson("/api/settings/testing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ audio_path: audioPath || "", audio_name: audioName || "" }),
    });
  } catch (error) {
    setGlobalError("Test audio selection save failed.");
  }
}

function updateTestAudioUi() {
  if (!state.testAudioPath) {
    setTestAudioStatus("No test audio selected.");
    return;
  }
  const label = state.testAudioName || state.testAudioPath.split("/").pop() || "Selected";
  setTestAudioStatus(`Selected: ${label}`);
}

async function uploadTestAudioFile(file) {
  if (!file) {
    return;
  }
  setStatus("Uploading file...");
  setGlobalBusy("Uploading test audio...");
  try {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch("/api/uploads/audio", {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `Upload failed: ${response.status}`);
    }
    const data = await response.json();
    state.testAudioPath = data.audio_path || "";
    state.testAudioName = data.audio_name || file.name || "";
    state.lastRecordingPath = state.testAudioPath;
    setStatus("File selected.");
    updateTestAudioUi();
    resetFileInputLabel();
    await saveTestAudioSelection(state.testAudioPath, state.testAudioName);
  } catch (error) {
    setStatus(`Upload failed: ${error.message}`);
    setGlobalError("Test audio upload failed.");
  } finally {
    setGlobalBusy("");
  }
}

function stopTestTranscription() {
  if (!state.testTranscribeController) {
    return;
  }
  debugLog("stopTestTranscription");
  state.testTranscribeController.abort();
}

async function refreshLogs() {
  const logOutput = document.getElementById("log-output");
  try {
    const response = await fetch("/api/logs/errors");
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    const text = await response.text();
    if (!text) {
      logOutput.textContent = "No errors yet.";
      return;
    }
    let data = null;
    try {
      data = JSON.parse(text);
    } catch (parseError) {
      logOutput.textContent = "No errors yet.";
      return;
    }
    if (!data.lines || data.lines.length === 0) {
      logOutput.textContent = "No errors yet.";
      return;
    }
    logOutput.textContent = data.lines.join("\n");
  } catch (error) {
    logOutput.textContent = `Log fetch failed: ${error.message}`;
  }
}

function renderMeetings() {
  const list = document.getElementById("meeting-list");
  // #region agent log
  let lastStoppedMeetingId = null;
  try {
    lastStoppedMeetingId = localStorage.getItem("lastStoppedMeetingId");
  } catch (_) {}
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app/static/app.js:renderMeetings',message:'renderMeetings enter',data:{hasListEl:!!list,meetingCount:state.meetings?.length||0,lastStoppedMeetingId},timestamp:Date.now(),runId:'pre-fix',hypothesisId:'H6'})}).catch(()=>{});
  // #endregion
  list.innerHTML = "";
  if (!state.meetings.length) {
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app/static/app.js:renderMeetings',message:'renderMeetings empty list',data:{lastStoppedMeetingId},timestamp:Date.now(),runId:'pre-fix',hypothesisId:'H6'})}).catch(()=>{});
    // #endregion
    return;
  }
  const meetingIds = (state.meetings || []).map((m) => m.id);
  const hasLastStoppedInState = lastStoppedMeetingId
    ? meetingIds.includes(lastStoppedMeetingId)
    : null;
  state.meetings
    .slice()
    .sort((a, b) => {
      const aInProgress = a.status === "in_progress";
      const bInProgress = b.status === "in_progress";
      if (aInProgress && !bInProgress) {
        return -1;
      }
      if (!aInProgress && bInProgress) {
        return 1;
      }
      const aTime = a.created_at || "";
      const bTime = b.created_at || "";
      return bTime.localeCompare(aTime);
    })
    .forEach((meeting) => {
    const item = document.createElement("div");
    item.className = "meeting-item";
    item.dataset.meetingId = meeting.id || "";
      const label = document.createElement("div");
      label.className = "meeting-item-text";
      const title = document.createElement("div");
      title.className = "meeting-title";
      title.textContent = meeting.title || "Untitled meeting";
      const meta = document.createElement("div");
      meta.className = "meeting-meta";
      const timestamp = meeting.created_at || "";
      const inProgress = meeting.status === "in_progress";
      meta.textContent = inProgress ? `${timestamp} · In progress` : timestamp;
      label.appendChild(title);
      label.appendChild(meta);
    const button = document.createElement("button");
    button.textContent = "Open";
    item.appendChild(label);
    item.appendChild(button);
    item.addEventListener("click", () => {
      window.location.href = `/meeting?id=${meeting.id}`;
    });
    list.appendChild(item);
  });
  // #region agent log
  const renderedCount = list.children ? list.children.length : null;
  const hasLastStoppedInDom = lastStoppedMeetingId
    ? !!list.querySelector(`[data-meeting-id="${lastStoppedMeetingId}"]`)
    : null;
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app/static/app.js:renderMeetings',message:'renderMeetings rendered',data:{renderedCount,hasLastStoppedInState,hasLastStoppedInDom,lastStoppedMeetingId,firstIds:meetingIds.slice(0,10)},timestamp:Date.now(),runId:'pre-fix',hypothesisId:'H6'})}).catch(()=>{});
  // #endregion
}

function findMeetingByAudioPath(audioPath) {
  return state.meetings.find((meeting) => meeting.audio_path === audioPath);
}

async function refreshMeetings() {
  setGlobalBusy("Loading meetings...");
  try {
    state.meetings = await fetchJson("/api/meetings");
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app/static/app.js:refreshMeetings',message:'meetings loaded',data:{count:state.meetings?.length||0,ids:(state.meetings||[]).slice(0,20).map(m=>m.id),selectedMeetingId:state.selectedMeetingId||null},timestamp:Date.now(),runId:'pre-fix',hypothesisId:'H3'})}).catch(()=>{});
    // #endregion
    // #region agent log
    let lastStoppedMeetingId = null;
    try {
      lastStoppedMeetingId = localStorage.getItem("lastStoppedMeetingId");
    } catch (_) {}
    const hasLastStopped = !!lastStoppedMeetingId;
    const hasLastStoppedInList = hasLastStopped
      ? (state.meetings || []).some((m) => m.id === lastStoppedMeetingId)
      : null;
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app/static/app.js:refreshMeetings',message:'lastStoppedMeeting check',data:{lastStoppedMeetingId,hasLastStopped,hasLastStoppedInList},timestamp:Date.now(),runId:'pre-fix',hypothesisId:'H5'})}).catch(()=>{});
    // #endregion
    if (state.fileMeetingId) {
      const meeting = state.meetings.find(
        (item) => item.id === state.fileMeetingId
      );
      if (meeting && meeting.status === "completed") {
        state.testTranscribing = false;
        setRecordingToggleLabel(false);
        setTranscriptStatus("File transcription completed.");
      }
    }
    renderMeetings();
    if (!state.selectedMeetingId) {
      setAttendeeEditor([]);
    }
  } catch (error) {
    debugError("Meeting load failed", error);
    logClientError("Meeting load failed", {
      message: error.message,
      stack: error.stack,
    });
    setGlobalError("Meeting load failed.");
  } finally {
    setGlobalBusy("");
  }
}

async function loadMeeting(meetingId) {
  setMeetingDetail("Loading meeting...");
  setGlobalBusy("Loading meeting...");
  try {
    const meeting = await fetchJson(`/api/meetings/${meetingId}`);
    state.selectedMeetingId = meeting.id;
    updateMeetingCache(meeting);
    setMeetingTitle(meeting.title);
    setAttendeeEditor(meeting.attendees || []);
    const transcript = meeting.transcript?.segments
      ? buildTranscriptText(meeting.transcript.segments)
      : "No transcript";
    const summary = meeting.summary?.text || "No summary";
    const actions = meeting.action_items?.length
      ? meeting.action_items.map((item) => `- ${item.description}`).join("\n")
      : "No action items";
    setMeetingDetail(
      `Title: ${meeting.title}\n\nSummary:\n${summary}\n\nAction Items:\n${actions}\n\nTranscript:\n${transcript}`
    );
  } catch (error) {
    setMeetingDetail(`Failed to load meeting: ${error.message}`);
    setGlobalError("Meeting load failed.");
  } finally {
    setGlobalBusy("");
  }
}

async function summarizeMeeting() {
  if (!state.selectedMeetingId) {
    setMeetingDetail("Select a meeting first.");
    return;
  }
  const provider = document.getElementById("summarize-provider").value;
  setMeetingDetail("Summarizing...");
  setGlobalBusy("Summarizing...");
  try {
    const result = await fetchJson(
      `/api/meetings/${state.selectedMeetingId}/summarize`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider }),
      }
    );
    await loadMeeting(state.selectedMeetingId);
    const actionItems = (result.action_items || [])
      .map((item) => `- ${item.description || item}`)
      .join("\n");
    setMeetingDetail(
      `Summary:\n${result.summary}\n\nAction Items:\n${actionItems}`
    );
  } catch (error) {
    setMeetingDetail(`Failed to summarize: ${error.message}`);
    setGlobalError("Summarization failed.");
  } finally {
    setGlobalBusy("");
  }
}

async function saveMeetingTitle() {
  if (!state.selectedMeetingId) {
    setMeetingDetail("Select a meeting first.");
    return;
  }
  const title = document.getElementById("meeting-title").value.trim();
  if (!title) {
    setMeetingDetail("Title cannot be empty.");
    return;
  }
  setMeetingDetail("Saving title...");
  setGlobalBusy("Saving title...");
  try {
    await fetchJson(`/api/meetings/${state.selectedMeetingId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    await loadMeeting(state.selectedMeetingId);
  } catch (error) {
    setMeetingDetail(`Failed to save title: ${error.message}`);
    setGlobalError("Title save failed.");
  } finally {
    setGlobalBusy("");
  }
}

function buildAttendeePayload(lines, existingAttendees) {
  const existing = existingAttendees || [];
  return lines.map((name, index) => {
    const existingAttendee = existing[index] || {};
    return {
      id: existingAttendee.id || `manual-${index + 1}`,
      label: existingAttendee.label || null,
      name: name.trim(),
    };
  });
}

async function saveAttendees() {
  if (!state.selectedMeetingId) {
    setMeetingDetail("Select a meeting first.");
    return;
  }
  const editor = document.getElementById("attendee-editor");
  const lines = editor.value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  setMeetingDetail("Saving attendees...");
  setGlobalBusy("Saving attendees...");
  try {
    const meeting = await fetchJson(`/api/meetings/${state.selectedMeetingId}`);
    const payload = buildAttendeePayload(lines, meeting.attendees || []);
    await fetchJson(`/api/meetings/${state.selectedMeetingId}/attendees`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ attendees: payload }),
    });
    await loadMeeting(state.selectedMeetingId);
    rerenderTranscript();
  } catch (error) {
    setMeetingDetail(`Failed to save attendees: ${error.message}`);
    setGlobalError("Attendee save failed.");
  } finally {
    setGlobalBusy("");
  }
}

async function deleteMeeting() {
  if (!state.selectedMeetingId) {
    setMeetingDetail("Select a meeting first.");
    return;
  }
  setMeetingDetail("Deleting meeting...");
  setGlobalBusy("Deleting meeting...");
  try {
    await fetchJson(`/api/meetings/${state.selectedMeetingId}`, {
      method: "DELETE",
    });
    state.selectedMeetingId = null;
    setMeetingTitle("");
    await refreshMeetings();
    setMeetingDetail("Meeting deleted.");
  } catch (error) {
    setMeetingDetail(`Failed to delete meeting: ${error.message}`);
    setGlobalError("Delete failed.");
  } finally {
    setGlobalBusy("");
  }
}

async function startRecording() {
  setOutput("Starting recording...");
  setStatusError("");
  setGlobalBusy("Starting recording...");
  try {
    const audioSettings = await fetchJson("/api/settings/audio");
    const source = audioSettings.source || "device";
    const storedDeviceIndex = audioSettings.device_index;
    state.recordingSource =
      source === "device" && storedDeviceIndex !== null && storedDeviceIndex !== undefined
        ? `device:${storedDeviceIndex}`
        : source;
    setRecordingSourceNote(
      source === "file" ? "Recording source: File" : "Recording source: Microphone"
    );
    if (source === "file") {
      if (!state.testAudioPath) {
        setStatusError("Select a file to start.");
        setOutput("No file selected.");
        return;
      }
      await startFileRecording();
      return;
    }
    const deviceIndex = Number(audioSettings.device_index);
    const samplerate = Number(audioSettings.samplerate);
    const channels = Number(audioSettings.channels);
    if (!state.devices.length) {
      state.devices = await fetchJson("/api/audio/devices");
    }
    const selected = state.devices.find((device) => device.index === deviceIndex);
    const maxChannels = selected ? selected.max_input_channels : channels;
    const safeChannels = Math.min(channels, maxChannels || channels);

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
    if (data.recording_id) {
      state.selectedMeetingId = data.recording_id;
    }
    await refreshRecordingStatus();
    startLiveTranscription();
    refreshMeetings();
    // Navigate to the newly created meeting
    if (data.recording_id) {
      window.location.href = `/meeting?id=${data.recording_id}`;
    }
  } catch (error) {
    setOutput(`Failed to start: ${error.message}`);
    setStatusError("Start recording failed. Check Console Errors below.");
    setGlobalError("Start recording failed.");
  } finally {
    setGlobalBusy("");
  }
}

function buildTranscriptText(segments) {
  const attendeeMap = new Map();
  for (const meeting of state.meetings || []) {
    for (const attendee of meeting.attendees || []) {
      if (attendee && attendee.id) {
        attendeeMap.set(attendee.id, attendee);
      }
    }
  }

  return segments
    .map((segment) => {
      const start = segment.start.toFixed(2);
      const end = segment.end.toFixed(2);
      const speakerId = segment.speaker_id || segment.speaker;
      const speakerName = speakerId
        ? attendeeMap.get(speakerId)?.name || speakerId
        : "Person 1";
      return `[${start}-${end}] [${speakerName}] ${segment.text}`;
    })
    .join("\n");
}

async function transcribeLatest() {
  const streamEnabled = state.transcriptionSettings.stream_transcribe;
  const finalModel = state.transcriptionSettings.final_model_size;
  if (!state.lastRecordingPath) {
    setTranscriptStatus("No recording found yet.");
    setTranscriptOutput("");
    return;
  }

  setTranscriptStatus("Transcribing...");
  setTranscriptOutput("");
  setGlobalBusy("Transcribing...");
  try {
    if (streamEnabled) {
      await streamTranscription(state.lastRecordingPath);
    } else {
      const data = await fetchJson("/api/transcribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          audio_path: state.lastRecordingPath,
          model_size: finalModel,
        }),
      });
      const transcriptText = buildTranscriptText(data.segments || []);
      state.lastTranscriptSegments = data.segments || [];
      setTranscriptStatus(
        `Transcript ready (${data.segments.length} segments, ${data.language || "unknown"}).`
      );
      setTranscriptOutput(transcriptText || "Transcript returned no segments.");
    }
    await refreshMeetings();
    if (!state.selectedMeetingId && state.lastRecordingPath) {
      const match = findMeetingByAudioPath(state.lastRecordingPath);
      if (match) {
        await loadMeeting(match.id);
      }
    }
  } catch (error) {
    setTranscriptStatus(`Transcription failed: ${error.message}`);
    setGlobalError("Transcription failed.");
  } finally {
    setGlobalBusy("");
  }
}

async function streamTranscription(audioPath, controller = null, options = {}) {
  const finalModel = state.transcriptionSettings.final_model_size;
  const segments = [];
  let language = "unknown";
  let done = false;

  const response = await fetch("/api/transcribe/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: controller ? controller.signal : undefined,
    body: JSON.stringify({
      audio_path: audioPath,
      model_size: finalModel,
      meeting_id: options.meetingId || null,
      simulate_live: !!options.simulateLive,
    }),
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
        state.lastTranscriptSegments = segments;
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

async function streamTranscriptionLive(controller) {
  const liveModel = state.transcriptionSettings.live_model_size;
  const segments = [];
  let language = "unknown";
  let done = false;

  const response = await fetch("/api/transcribe/live", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: controller.signal,
    body: JSON.stringify({
      model_size: liveModel,
      meeting_id: state.selectedMeetingId,
    }),
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
        setTranscriptStatus(`Live transcription... (${language})`);
      } else if (event.type === "segment") {
        segments.push(event);
        state.lastTranscriptSegments = segments;
        setTranscriptOutput(buildTranscriptText(segments));
      } else if (event.type === "done") {
        done = true;
      } else if (event.type === "error") {
        throw new Error(event.message || "Live transcription failed");
      }
    }
  }

  setTranscriptStatus(
    `Live transcript ready (${segments.length} segments, ${language}).`
  );
}

async function stopRecording() {
  if (state.stopInFlight) {
    return;
  }
  state.stopInFlight = true;
  setOutput("Stopping audio capture...");
  setStatusError("");
  setGlobalBusy("Stopping audio capture...");
  try {
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app/static/app.js:stopRecording',message:'stopRecording enter',data:{recordingSource:state.recordingSource,selectedMeetingId:state.selectedMeetingId||null},timestamp:Date.now(),runId:'pre-fix',hypothesisId:'H3'})}).catch(()=>{});
    // #endregion
    if (state.recordingSource === "file") {
      await stopFileRecording();
      return;
    }
    
    // Stop live transcription SSE stream immediately
    // This signals to stop pulling audio from the queue
    await stopLiveTranscription();
    debugLog("Live transcription stream aborted");
    
    // Now stop the actual recording
    const data = await fetchJson("/api/recording/stop", {
      method: "POST",
    });
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app/static/app.js:stopRecording',message:'stopRecording response',data:{recording_id:data?.recording_id||null,file_path:data?.file_path||null},timestamp:Date.now(),runId:'pre-fix',hypothesisId:'H3'})}).catch(()=>{});
    // #endregion
    
    setOutput("Audio capture stopped. Finishing transcription...");
    setGlobalBusy("Audio capture stopped. Finishing transcription...");
    
    if (data.file_path) {
      state.lastRecordingPath = data.file_path;
    }
    await refreshRecordingStatus();
    await refreshMeetings();
    if (data.recording_id) {
      await loadMeeting(data.recording_id);
    }
    if (state.transcriptionSettings.auto_transcribe) {
      await transcribeLatest();
    }
    
    setOutput(`Recording saved: ${data.file_path}`);
    refreshMeetings();
  } catch (error) {
    setOutput(`Failed to stop: ${error.message}`);
    setStatusError("Stop recording failed. Check Console Errors below.");
    setGlobalError("Stop recording failed.");
    appendLogLine(`Stop recording error: ${error.message}`);
    debugError("Stop recording failed", error);
    logClientError("Stop recording failed", {
      message: error.message,
      stack: error.stack,
    });
  } finally {
    setGlobalBusy("");
    state.stopInFlight = false;
  }
}

// startFileRecording and stopFileRecording are defined earlier in the file

async function startLiveTranscription() {
  if (!state.transcriptionSettings.live_transcribe) {
    return;
  }
  if (state.liveController) {
    return;
  }
  setTranscriptStatus("Live transcription starting...");
  state.liveController = new AbortController();
  try {
    streamTranscriptionLive(state.liveController);
  } catch (error) {
    if (error.name !== "AbortError") {
      setTranscriptStatus(`Live transcription failed: ${error.message}`);
    }
  }
}

async function stopLiveTranscription() {
  if (!state.liveController) {
    return;
  }
  state.liveController.abort();
  state.liveController = null;
}

document.addEventListener("DOMContentLoaded", async () => {
  const recordingToggle = document.getElementById("recording-toggle");
  if (recordingToggle) {
    recordingToggle.addEventListener("click", async () => {
      const isRecording = state.recording || state.testTranscribing;
      if (isRecording) {
        await stopRecording();
      } else {
        await startRecording();
      }
    });
  }
  const testUpload = document.getElementById("test-audio-upload");
  if (testUpload) {
    testUpload.addEventListener("change", (event) => {
      const file = event.target.files ? event.target.files[0] : null;
      uploadTestAudioFile(file);
    });
  }
  bindFilePicker();
  const sourceSelect = document.getElementById("recording-source");
  if (sourceSelect) {
    sourceSelect.addEventListener("change", async (event) => {
      const value = event.target.value;
      if (value === "file") {
        state.recordingSource = "file";
        await saveAudioSource("file", null);
      } else if (value.startsWith("device:")) {
        const deviceIndex = Number(value.split(":")[1]);
        state.recordingSource = `device:${deviceIndex}`;
        await saveAudioSource("device", deviceIndex);
      } else {
        state.recordingSource = "device";
        await saveAudioSource("device", null);
      }
      updateFileSourceVisibility();
    });
  }
  const settingsButton = document.getElementById("settings-button");
  if (settingsButton) {
    settingsButton.addEventListener("click", () => {
      window.location.href = "/settings";
    });
  }
  const profileToggle = document.getElementById("profile-toggle");
  const profileMenu = document.getElementById("profile-menu");
  if (profileToggle && profileMenu) {
    profileToggle.addEventListener("click", () => {
      profileMenu.classList.toggle("open");
    });
    document.addEventListener("click", (event) => {
      if (
        !profileMenu.contains(event.target) &&
        event.target !== profileToggle
      ) {
        profileMenu.classList.remove("open");
      }
    });
  }

  await refreshHealth();
  await refreshDevices();
  await loadAudioSettings();
  await loadTranscriptionSettings();
  await loadTestAudioPath();
  await loadAudioSource();
  await syncTestTranscriptionStatus();
  await refreshRecordingStatus();
  await refreshLogs();
  await refreshMeetings();
  startMeetingsEventStream();
  setInterval(refreshLogs, 5000);
});

async function saveDiarizationSettings() {
  const enabled = document.getElementById("diarization-enabled").checked;
  const hfToken = document.getElementById("hf-token").value.trim();
  const model = document.getElementById("diarization-model").value.trim();

  setDiarizationOutput("Saving diarization settings...");
  setGlobalBusy("Saving diarization settings...");
  try {
    await fetchJson("/api/diarization/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled,
        model,
        hf_token: hfToken || null,
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

async function exportMeeting() {
  if (!state.selectedMeetingId) {
    setMeetingDetail("Select a meeting first.");
    return;
  }
  const url = `/api/meetings/${state.selectedMeetingId}/export`;
  window.open(url, "_blank");
}
