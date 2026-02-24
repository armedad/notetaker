const state = {
  devices: [],
  recording: false,
  lastRecordingPath: null,
  liveController: null,
  meetings: [],
  selectedMeetingId: null,
  selectedMeetingIds: new Set(),  // Multi-select state for meeting list
  lastTranscriptSegments: null,
  testAudioPath: "",
  testAudioName: "",
  testTranscribeController: null,
  testTranscribing: false,
  stopInFlight: false,
  transcriptionSettings: {
    live_model_size: "base",
    final_model_size: "medium",
    live_transcribe: true,
  },
  meetingsEvents: null,
  recordingSource: "device",
  fileMeetingId: null,
  overallChat: null,  // ChatUI instance for overall chat
  // Search state
  searchQuery: "",
  searchResults: [],
  showSearchResults: false,
  // Finalization tracking: meetingId -> { stageText, startedAt }
  finalizingMeetings: {},
};

// --- Multi-select helper functions ---
function toggleMeetingSelection(meetingId) {
  if (state.selectedMeetingIds.has(meetingId)) {
    state.selectedMeetingIds.delete(meetingId);
  } else {
    state.selectedMeetingIds.add(meetingId);
  }
  updateMeetingSelectionUI();
}

function clearMeetingSelection() {
  state.selectedMeetingIds.clear();
  updateMeetingSelectionUI();
}

function getSelectedMeetingIds() {
  return Array.from(state.selectedMeetingIds);
}

function updateMeetingSelectionUI() {
  // Update selected class on meeting items
  const items = document.querySelectorAll(".meeting-item");
  items.forEach((item) => {
    const meetingId = item.dataset.meetingId;
    if (state.selectedMeetingIds.has(meetingId)) {
      item.classList.add("selected");
    } else {
      item.classList.remove("selected");
    }
  });
  
  // Show/hide selection toolbar
  const toolbar = document.getElementById("selection-toolbar");
  if (toolbar) {
    const count = state.selectedMeetingIds.size;
    if (count > 0) {
      toolbar.hidden = false;
      const countEl = toolbar.querySelector(".selection-count");
      if (countEl) {
        countEl.textContent = `${count} selected`;
      }
    } else {
      toolbar.hidden = true;
    }
  }
}

function debugLog(message, data = {}) {
  console.debug(`[Home] ${message}`, data);
}

// --- Search functions ---
function toggleSearch() {
  const searchBar = document.getElementById("search-bar");
  const searchToggle = document.getElementById("search-toggle");
  const searchInput = document.getElementById("search-input");
  
  if (!searchBar) return;
  
  if (searchBar.style.display === "none") {
    // Open search
    searchBar.style.display = "flex";
    searchToggle.classList.add("active");
    searchInput?.focus();
  } else {
    // Close search
    closeSearch();
  }
}

function closeSearch() {
  const searchBar = document.getElementById("search-bar");
  const searchToggle = document.getElementById("search-toggle");
  const searchInput = document.getElementById("search-input");
  const searchCount = document.getElementById("search-count");
  
  if (searchBar) searchBar.style.display = "none";
  if (searchToggle) searchToggle.classList.remove("active");
  if (searchInput) searchInput.value = "";
  if (searchCount) searchCount.textContent = "";
  
  state.searchQuery = "";
  state.searchResults = [];
  state.showSearchResults = false;
  
  // Restore meetings list
  renderMeetings();
}

async function performSearch(query) {
  if (!query || query.length < 2) {
    state.searchResults = [];
    state.showSearchResults = false;
    renderMeetings();
    return;
  }
  
  state.searchQuery = query;
  const searchCount = document.getElementById("search-count");
  if (searchCount) searchCount.textContent = "Searching...";
  
  try {
    const results = await fetchJson(`/api/search?q=${encodeURIComponent(query)}&limit=50`);
    state.searchResults = results;
    state.showSearchResults = true;
    
    if (searchCount) {
      searchCount.textContent = `${results.length} match${results.length !== 1 ? "es" : ""}`;
    }
    
    renderSearchResults();
  } catch (error) {
    debugLog("Search failed", { error: error.message });
    if (searchCount) searchCount.textContent = "Error";
    state.searchResults = [];
    state.showSearchResults = false;
    renderMeetings();
  }
}

function renderSearchResults() {
  const list = document.getElementById("meeting-list");
  if (!list) return;
  
  list.innerHTML = "";
  
  if (state.searchResults.length === 0) {
    const empty = document.createElement("div");
    empty.className = "search-empty";
    empty.textContent = `No results for "${state.searchQuery}"`;
    list.appendChild(empty);
    return;
  }
  
  state.searchResults.forEach((result) => {
    const item = document.createElement("div");
    item.className = "search-result-item";
    item.dataset.meetingId = result.meeting_id;
    
    // Meeting title
    const title = document.createElement("div");
    title.className = "search-result-title";
    title.textContent = result.meeting_title || "Untitled meeting";
    
    // Field type badge
    const badge = document.createElement("span");
    badge.className = `search-field-badge badge-${result.field_type}`;
    badge.textContent = formatFieldType(result.field_type);
    
    // Snippet with highlighted match
    const snippet = document.createElement("div");
    snippet.className = "search-snippet";
    snippet.innerHTML = highlightMatch(result.snippet, state.searchQuery);
    
    // Date
    const meta = document.createElement("div");
    meta.className = "search-result-meta";
    meta.textContent = result.created_at || "";
    
    item.appendChild(title);
    item.appendChild(badge);
    item.appendChild(snippet);
    item.appendChild(meta);
    
    // Click to navigate to meeting
    item.addEventListener("click", () => {
      window.location.href = `/meeting?id=${result.meeting_id}`;
    });
    
    list.appendChild(item);
  });
}

function formatFieldType(fieldType) {
  const labels = {
    title: "Title",
    summary: "Summary",
    transcript: "Transcript",
    attendee: "Attendee",
    user_note: "Note",
    manual_notes: "Notes",
    chat: "Chat",
  };
  return labels[fieldType] || fieldType;
}

function highlightMatch(text, query) {
  if (!text || !query) return text || "";
  
  // Escape HTML first
  const escaped = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  
  // Escape regex special chars in query
  const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  
  // Case-insensitive replace with <mark>
  const regex = new RegExp(`(${escapedQuery})`, "gi");
  return escaped.replace(regex, "<mark>$1</mark>");
}

function initSearch() {
  const searchToggle = document.getElementById("search-toggle");
  const searchClose = document.getElementById("search-close");
  const searchInput = document.getElementById("search-input");
  
  if (searchToggle) {
    searchToggle.addEventListener("click", toggleSearch);
  }
  
  if (searchClose) {
    searchClose.addEventListener("click", closeSearch);
  }
  
  if (searchInput) {
    // Search on Enter
    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        performSearch(searchInput.value.trim());
      } else if (e.key === "Escape") {
        closeSearch();
      }
    });
  }
  
  // Ctrl+F / Cmd+F to open search
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "f") {
      e.preventDefault();
      toggleSearch();
    }
  });
}

/**
 * Attach a right-click "Submit and Log" debug context menu to a ChatUI
 * instance's send button. This is notetaker-specific debug tooling that
 * lives outside the reusable ChatUI component.
 */
function _attachDebugContextMenu(chatInstance) {
  if (!chatInstance || !chatInstance.sendBtn) return;

  chatInstance.sendBtn.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    // Remove any existing menu
    const existing = document.querySelector('.test-chat-context-menu');
    if (existing) existing.remove();

    const menu = document.createElement('div');
    menu.className = 'test-chat-context-menu';
    menu.style.cssText = `
      position: fixed; left: ${e.clientX}px; top: ${e.clientY}px;
      background: #1a1a2e; color: #e0e0e0; border: 1px solid #444;
      border-radius: 4px; box-shadow: 0 2px 8px rgba(0,0,0,0.4);
      z-index: 10000; padding: 4px 0; min-width: 150px;
    `;

    const option = document.createElement('div');
    option.textContent = 'Submit and Log';
    option.style.cssText = 'padding: 8px 16px; cursor: pointer; font-size: 14px; color: #e0e0e0;';
    option.addEventListener('mouseenter', () => { option.style.background = '#2a2a4a'; });
    option.addEventListener('mouseleave', () => { option.style.background = 'transparent'; });
    option.addEventListener('click', () => {
      menu.remove();
      // Set a one-shot flag so the next sendMessage adds test_log_this
      chatInstance.onSendMessage = (payload) => {
        payload.test_log_this = true;
        chatInstance.onSendMessage = null; // one-shot
      };
      chatInstance.sendMessage();
    });

    menu.appendChild(option);
    document.body.appendChild(menu);

    const closeMenu = (event) => {
      if (!menu.contains(event.target)) {
        menu.remove();
        document.removeEventListener('click', closeMenu);
      }
    };
    setTimeout(() => document.addEventListener('click', closeMenu), 10);
  });
}

/**
 * Initialize the overall chat UI component for querying all meetings.
 */
function initOverallChat() {
  const container = document.getElementById("overall-chat-container");
  if (!container || typeof ChatUI === "undefined") {
    console.warn("Overall chat container or ChatUI not available");
    return;
  }
  
  state.overallChat = new ChatUI({
    container: container,
    endpoint: "/api/chat/overall",
    historyEndpoint: "/api/chat/homepage/history",
    buildPayload: (question) => ({
      question: question,
      max_meetings: 5,
      include_transcripts: true,
    }),
    placeholder: "Ask a question about your meetings...",
    title: "Search All Meetings",
    emptyText: "Ask a question about your meetings.",
    fullscreen: true,
    onSendMessage: null,  // debug hook attached below if needed
  });

  // Debug: right-click send button → "Submit and Log"
  _attachDebugContextMenu(state.overallChat);
}

/**
 * Initialize collapsible panels.
 */
function initCollapsiblePanels() {
  const logsToggle = document.getElementById("logs-toggle");
  const logsBody = document.getElementById("logs-body");
  if (logsToggle && logsBody) {
    logsToggle.addEventListener("click", () => {
      logsBody.classList.toggle("collapsed");
      const indicator = logsToggle.querySelector(".collapse-indicator");
      if (indicator) {
        indicator.textContent = logsBody.classList.contains("collapsed") ? "▸" : "▾";
      }
    });
  }
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
  if (output) {
    output.textContent = message;
  }
}

function setStatus(message) {
  const status = document.getElementById("recording-status");
  if (status) {
    status.textContent = message;
  }
}

function setStatusError(message) {
  const statusError = document.getElementById("status-error");
  if (statusError) {
    statusError.textContent = message;
  }
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

function setTestAudioStatus(message, fullPath = null) {
  const status = document.getElementById("test-audio-status");
  if (!status) {
    return;
  }
  status.textContent = message;
  // Set tooltip to show full filename on hover
  status.title = fullPath || message;
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
  const fileNameBox = document.getElementById("file-name-box");
  const input = document.getElementById("test-audio-upload");
  if (!fileNameBox || !input) {
    return;
  }
  fileNameBox.addEventListener("click", () => {
    input.click();
  });
}

function setDiarizationOutput(message) {
  const output = document.getElementById("diarization-output");
  if (output) {
    output.textContent = message;
  }
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
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app.js:startMeetingsEventStream',message:'SSE_CONNECT_ATTEMPT',data:{alreadyHasConnection:!!state.meetingsEvents},timestamp:Date.now(),hypothesisId:'H2'})}).catch(()=>{});
  // #endregion
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
    
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app.js:onmessage',message:'SSE_EVENT_RECEIVED',data:{type:payload.type,meeting_id:payload.meeting_id,ts:payload.timestamp,hasData:!!payload.data},timestamp:Date.now(),hypothesisId:'H1'})}).catch(()=>{});
    // #endregion
    // Track finalization progress for blue dot indicator
    if (payload.type === "finalization_status" && payload.meeting_id) {
      // #region agent log
      const _existing = state.finalizingMeetings[payload.meeting_id];
      fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app.js:finalization_status_sse',message:'FINALIZATION_STATUS_EVENT',data:{meeting_id:payload.meeting_id,statusText:payload.status_text,existingEntry:_existing||null,now:new Date().toISOString()},timestamp:Date.now(),hypothesisId:'H1'})}).catch(()=>{});
      // #endregion
      const existing = state.finalizingMeetings[payload.meeting_id];
      state.finalizingMeetings[payload.meeting_id] = {
        stageText: payload.status_text || "Finalizing...",
        startedAt: existing?.startedAt || new Date().toISOString(),
      };
      renderMeetings();
    }

    // Handle finalization events for notifications
    if (payload.type === "finalization_complete") {
      delete state.finalizingMeetings[payload.meeting_id];
      const title = payload.data?.meeting_title || "Meeting";
      const eventAge = payload.timestamp ? (Date.now() - new Date(payload.timestamp).getTime()) : null;
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app.js:finalization_complete',message:'NOTIFY_TRIGGERED',data:{title,eventTimestamp:payload.timestamp,eventAgeMs:eventAge,isStale:eventAge>30000},timestamp:Date.now(),hypothesisId:'H1'})}).catch(()=>{});
      // #endregion
      // Skip stale events (older than 30 seconds) to avoid duplicate notifications on reconnect
      if (eventAge !== null && eventAge > 30000) {
        // #region agent log
        fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app.js:finalization_complete',message:'SKIPPED_STALE_EVENT',data:{title,eventAgeMs:eventAge},timestamp:Date.now(),hypothesisId:'H1'})}).catch(()=>{});
        // #endregion
      } else {
        NotificationCenter.success(`Finalization complete: ${title}`);
      }
    } else if (payload.type === "finalization_failed") {
      delete state.finalizingMeetings[payload.meeting_id];
      const title = payload.data?.meeting_title || "Meeting";
      const errors = payload.data?.errors || [];
      const errorCount = errors.length || 1;
      const eventAge = payload.timestamp ? (Date.now() - new Date(payload.timestamp).getTime()) : null;
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app.js:finalization_failed',message:'NOTIFY_TRIGGERED',data:{title,errorCount,eventTimestamp:payload.timestamp,eventAgeMs:eventAge,isStale:eventAge>30000},timestamp:Date.now(),hypothesisId:'H1'})}).catch(()=>{});
      // #endregion
      // Skip stale events (older than 30 seconds) to avoid duplicate notifications on reconnect
      if (eventAge !== null && eventAge > 30000) {
        // #region agent log
        fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app.js:finalization_failed',message:'SKIPPED_STALE_EVENT',data:{title,eventAgeMs:eventAge},timestamp:Date.now(),hypothesisId:'H1'})}).catch(()=>{});
        // #endregion
      } else {
        // Build detailed error message with stage and error info
        let errorMsg = `Finalization failed: ${title}`;
        if (errors.length > 0) {
          const firstError = errors[0];
          errorMsg += ` — ${firstError.stage}: ${firstError.error}`;
        }
        NotificationCenter.error(errorMsg, 15000);  // Show for 15 seconds
        // Log full error details to console for debugging
        console.error("Finalization failed:", {
          meeting_id: payload.meeting_id,
          title,
          errors,
        });
      }
    }
    
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
    if (statusEl) {
      statusEl.textContent = `Status: ${data.status} (${data.version})`;
    }
    if (versionBadge) {
      versionBadge.textContent = data.version;
    }
    
    // Track version changes and show alert if server was updated
    if (data.version) {
      if (initialServerVersion === null) {
        initialServerVersion = data.version;
      } else if (data.version !== initialServerVersion) {
        showVersionUpdateBanner();
      }
    }
  } catch (error) {
    if (statusEl) {
      statusEl.textContent = `Health check failed: ${error.message}`;
    }
    if (versionBadge) {
      versionBadge.textContent = "v?.?.?.?";
    }
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
      setStatus("Recording from file");
    } else if (data.recording) {
      setStatus("Recording from mic");
    } else {
      setStatus("Not recording");
    }
    setStatusError("");
  } catch (error) {
    setStatus(`Status error: ${error.message}`);
    setStatusError("Status refresh failed.");
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
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app.js:startFileRecording',message:'startFileRecording_ENTER',data:{audioPath:state.testAudioPath,audioName:state.testAudioName},timestamp:Date.now(),runId:'start-debug',hypothesisId:'H3'})}).catch(()=>{});
  // #endregion
  debugLog("startFileRecording", { audioPath: state.testAudioPath });
  setStatus("Recording from file");
  setOutput(`Transcribing file: ${state.testAudioName || state.testAudioPath}`);
  state.testTranscribing = true;
  setRecordingToggleLabel(true);
  try {
    const response = await fetchJson("/api/transcribe/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: "file",
        audio_path: state.testAudioPath,
      }),
    });
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app.js:startFileRecording',message:'simulate_response_OK',data:{meetingId:response.meeting_id,status:response.status,speedPercent:response.speed_percent},timestamp:Date.now(),runId:'start-debug',hypothesisId:'H3'})}).catch(()=>{});
    // #endregion
    if (response.status === "running") {
      // A transcription for this file is already in progress -- tell the
      // user instead of silently navigating to the old meeting.
      setStatusError("A transcription for this file is already running.");
      setOutput("Stop the current transcription first, or wait for it to finish.");
      state.testTranscribing = false;
      setRecordingToggleLabel(false);
      return;
    }
    state.fileMeetingId = response.meeting_id || null;
    setStatus("Recording from file");
    // Navigate to the newly created meeting
    if (response.meeting_id) {
      window.location.href = `/meeting?id=${response.meeting_id}`;
    }
  } catch (error) {
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app.js:startFileRecording',message:'startFileRecording_ERROR',data:{errorMessage:error.message,errorName:error.name,errorStack:error.stack?.substring(0,500)},timestamp:Date.now(),runId:'start-debug',hypothesisId:'H3'})}).catch(()=>{});
    // #endregion
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
  debugLog("stopFileRecording", { meetingId: state.fileMeetingId, audioPath: state.testAudioPath });
  
  // Disable toggle button to prevent multiple clicks
  const toggleBtn = document.getElementById("recording-toggle");
  if (toggleBtn) {
    toggleBtn.disabled = true;
    toggleBtn.textContent = "Stopping...";
  }
  
  setGlobalBusy("Stopping file ingestion...");
  setStatus("Stopping...");
  
  try {
    // Use unified stop endpoint with meeting_id
    const meetingId = state.fileMeetingId;
    if (!meetingId) {
      throw new Error("No file meeting ID available");
    }
    const result = await fetchJson(
      `/api/transcribe/stop/${encodeURIComponent(meetingId)}`,
      { method: "POST" }
    );
    debugLog("File stop requested", { result });
    
    // The stop request returns immediately. File reading has stopped.
    // Transcription of already-read audio continues in background.
    setGlobalBusy("File reading stopped. Finishing transcription...");
    setStatus("Finishing...");
    
    // Poll for completion since transcription continues in background
    let attempts = 0;
    const maxAttempts = 120; // 2 minutes max wait
    
    while (attempts < maxAttempts) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      attempts++;
      
      // Check if transcription has stopped using unified active endpoint
      try {
        const active = await fetchJson(`/api/transcribe/active`);
        if (!active.active || active.meeting_id !== meetingId) {
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
    setStatus("Not recording");
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
  const fileNameBox = document.getElementById("file-name-box");
  if (!fileNameBox) {
    return;
  }
  // Use visibility class instead of display:none to prevent layout shift
  if (state.recordingSource === "file") {
    fileNameBox.classList.remove("hidden");
  } else {
    fileNameBox.classList.add("hidden");
  }
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
  debugLog("syncTestTranscriptionStatus", { fileMeetingId: state.fileMeetingId, audioPath: state.testAudioPath });
  try {
    // Use unified active endpoint
    const active = await fetchJson(`/api/transcribe/active`);
    debugLog("transcription active status", active);
    
    // Check if there's an active file transcription (matching our audio path or meeting id)
    if (active.active) {
      const isOurTranscription = 
        (state.fileMeetingId && active.meeting_id === state.fileMeetingId) ||
        (state.testAudioPath && active.audio_path === state.testAudioPath);
      
      if (isOurTranscription) {
        state.testTranscribing = true;
        state.recordingSource = "file";
        state.fileMeetingId = active.meeting_id || state.fileMeetingId;
        setRecordingToggleLabel(true);
        setStatus("Recording from file");
        return;
      }
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
    setTestAudioStatus("No file", "");
    return;
  }
  const fullName = state.testAudioName || state.testAudioPath.split("/").pop() || "Selected";
  setTestAudioStatus(fullName, fullName);
}

async function uploadTestAudioFile(file) {
  if (!file) {
    return;
  }
  setGlobalBusy("Uploading file...");
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
    updateTestAudioUi();
    resetFileInputLabel();
    await saveTestAudioSelection(state.testAudioPath, state.testAudioName);
  } catch (error) {
    setGlobalError(`Upload failed: ${error.message}`);
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
  if (!logOutput) {
    return;
  }
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
      // Use resolved_state for active meetings (from tracker), fall back to status
      const aState = a.resolved_state || a.status;
      const bState = b.resolved_state || b.status;
      const aActive = aState === "recording" || aState === "finalizing" || aState === "in_progress";
      const bActive = bState === "recording" || bState === "finalizing" || bState === "in_progress";
      if (aActive && !bActive) {
        return -1;
      }
      if (!aActive && bActive) {
        return 1;
      }
      const aTime = a.created_at || "";
      const bTime = b.created_at || "";
      return bTime.localeCompare(aTime);
    })
    .forEach((meeting) => {
    const item = document.createElement("div");
    item.className = "meeting-item";
    if (state.selectedMeetingIds.has(meeting.id)) {
      item.classList.add("selected");
    }
    item.dataset.meetingId = meeting.id || "";
    const titleRow = document.createElement("div");
    titleRow.className = "meeting-title-row";
    
    const title = document.createElement("div");
    title.className = "meeting-title";
    title.textContent = meeting.title || "Untitled meeting";
    titleRow.appendChild(title);
    
    // Add hourglass icon for meetings needing finalization
    if (meeting.needs_finalization && meeting.pending_stages && meeting.pending_stages.length > 0) {
      const finalizationIcon = document.createElement("span");
      finalizationIcon.className = "finalization-pending-icon";
      finalizationIcon.textContent = "⏳";

      const activeInfo = state.finalizingMeetings[meeting.id];
      const startTime = activeInfo ? new Date(activeInfo.startedAt).toLocaleTimeString() : null;
      const stageText = activeInfo?.stageText || "";

      const tooltipLines = ["Pending finalization:"];
      if (activeInfo) {
        // Show active stage with start time, then remaining pending stages
        tooltipLines.push(`  ▶ ${stageText} (started ${startTime})`);
        for (const stage of meeting.pending_stages) {
          if (!stageText.toLowerCase().includes(stage.toLowerCase())) {
            tooltipLines.push(`  - ${stage}`);
          }
        }
      } else {
        for (const stage of meeting.pending_stages) {
          tooltipLines.push(`  - ${stage}`);
        }
      }
      finalizationIcon.title = tooltipLines.join("\n");
      titleRow.appendChild(finalizationIcon);

      if (activeInfo) {
        const dot = document.createElement("span");
        dot.className = "finalization-active-dot";
        dot.title = finalizationIcon.title;
        titleRow.appendChild(dot);
      }
    }
    
    // Add warning icon for meetings with failed finalization stages
    if (meeting.failed_stages && meeting.failed_stages.length > 0) {
      const failedIcon = document.createElement("span");
      failedIcon.className = "finalization-failed-icon";
      failedIcon.textContent = "⚠️";
      failedIcon.title = `Failed: ${meeting.failed_stages.join(", ")}`;
      titleRow.appendChild(failedIcon);
    }
    
    const meta = document.createElement("div");
    meta.className = "meeting-meta";
    const timestamp = meeting.created_at || "";
    // Use resolved_state for accurate status display
    const resolvedState = meeting.resolved_state || meeting.status;
    let statusLabel = "";
    if (resolvedState === "recording") {
      statusLabel = " · Recording";
    } else if (resolvedState === "finalizing" || resolvedState === "background_finalizing") {
      statusLabel = " · Finalizing";
    } else if (resolvedState === "in_progress") {
      statusLabel = " · In progress";
    }
    meta.textContent = timestamp + statusLabel;
    item.appendChild(titleRow);
    item.appendChild(meta);
    
    // Click handler: left side toggles selection, right side navigates
    item.addEventListener("click", (e) => {
      const rect = item.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const selectZoneWidth = 24; // pixels from left edge for selection
      
      if (clickX <= selectZoneWidth) {
        // Clicked in left selection zone
        e.preventDefault();
        toggleMeetingSelection(meeting.id);
      } else {
        // Clicked on content - navigate
        window.location.href = `/meeting?id=${meeting.id}`;
      }
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
      // Use resolved_state for accurate completion check
      const resolvedState = meeting?.resolved_state || meeting?.status;
      if (meeting && resolvedState === "completed") {
        state.testTranscribing = false;
        setRecordingToggleLabel(false);
        setTranscriptStatus("File transcription completed.");
      }
    }
    // Seed finalization tracking — find which meetings are actively finalizing
    try {
      const fResp = await fetchJson("/api/transcribe/finalizing");
      const activeIds = fResp.meeting_ids || [];
      const meetingsInfo = fResp.meetings || {};
      const updated = {};
      for (const mid of activeIds) {
        const serverInfo = meetingsInfo[mid] || {};
        updated[mid] = state.finalizingMeetings[mid] || {
          stageText: serverInfo.stage || "Finalizing...",
          startedAt: serverInfo.started_at || new Date().toISOString(),
        };
      }
      state.finalizingMeetings = updated;
    } catch (_) {}

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

async function deleteSelectedMeetings() {
  const ids = getSelectedMeetingIds();
  if (ids.length === 0) {
    return;
  }
  
  const confirmMsg = ids.length === 1 
    ? "Delete this meeting?" 
    : `Delete ${ids.length} meetings?`;
  if (!confirm(confirmMsg)) {
    return;
  }
  
  setGlobalBusy(`Deleting ${ids.length} meeting(s)...`);
  try {
    let deleted = 0;
    for (const id of ids) {
      try {
        await fetchJson(`/api/meetings/${id}`, { method: "DELETE" });
        deleted++;
        setGlobalBusy(`Deleting... (${deleted}/${ids.length})`);
      } catch (error) {
        debugError(`Failed to delete meeting ${id}`, error);
      }
    }
    clearMeetingSelection();
    await refreshMeetings();
  } catch (error) {
    setGlobalError(`Delete failed: ${error.message}`);
  } finally {
    setGlobalBusy("");
  }
}

async function startRecording() {
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app.js:startRecording',message:'startRecording_ENTER',data:{recordingSource:state.recordingSource,testAudioPath:state.testAudioPath,testTranscribing:state.testTranscribing,recording:state.recording},timestamp:Date.now(),runId:'start-debug',hypothesisId:'H1'})}).catch(()=>{});
  // #endregion
  setOutput("Starting recording...");
  setStatusError("");
  setGlobalBusy("Starting recording...");
  try {
    const audioSettings = await fetchJson("/api/settings/audio");
    const source = audioSettings.source || "device";
    const storedDeviceIndex = audioSettings.device_index;
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app.js:startRecording',message:'audioSettings_fetched',data:{source,storedDeviceIndex,audioSettings},timestamp:Date.now(),runId:'start-debug',hypothesisId:'H1'})}).catch(()=>{});
    // #endregion
    state.recordingSource =
      source === "device" && storedDeviceIndex !== null && storedDeviceIndex !== undefined
        ? `device:${storedDeviceIndex}`
        : source;
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

    const data = await fetchJson("/api/transcribe/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: "mic",
        device_index: deviceIndex,
        samplerate,
        channels: safeChannels,
      }),
    });
    setOutput(`Recording started: ${data.meeting_id}`);
    if (data.meeting_id) {
      state.selectedMeetingId = data.meeting_id;
    }
    await refreshRecordingStatus();
    refreshMeetings();
    if (data.meeting_id) {
      window.location.href = `/meeting?id=${data.meeting_id}`;
    }
  } catch (error) {
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app.js:startRecording',message:'startRecording_CATCH',data:{errorMessage:error.message,errorName:error.name,errorStack:error.stack?.substring(0,500)},timestamp:Date.now(),runId:'start-debug',hypothesisId:'H1'})}).catch(()=>{});
    // #endregion
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

    const meetingId = state.selectedMeetingId;
    if (!meetingId) {
      setOutput("No active meeting to stop.");
      return;
    }
    const data = await fetchJson(`/api/transcribe/stop/${meetingId}`, {
      method: "POST",
    });
    setOutput("Audio capture stopped. Finishing transcription...");
    setGlobalBusy("Audio capture stopped. Finishing transcription...");
    await refreshRecordingStatus();
    await refreshMeetings();
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
  
  // Multi-select delete button
  const deleteSelectedBtn = document.getElementById("delete-selected-btn");
  if (deleteSelectedBtn) {
    deleteSelectedBtn.addEventListener("click", deleteSelectedMeetings);
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
  
  // Initialize collapsible panels
  initCollapsiblePanels();
  
  // Initialize overall chat for querying all meetings
  initOverallChat();
  
  // Initialize search
  initSearch();
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
