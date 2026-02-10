const state = {
  meetingId: null,
  meeting: null,
  lastTranscriptSegments: null,
  liveController: null,
  liveStreaming: false,
  summaryTimer: null,
  summaryInFlight: false,
  summaryIntervalMs: 30000,
  titleSaveTimer: null,
  countdownTimer: null,
  countdownSeconds: 30,
};

function debugLog(message, data = {}) {
  console.debug(`[Meeting] ${message}`, data);
}

function debugError(message, error) {
  console.error(`[Meeting] ${message}`, error);
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
    console.error("[Meeting] Failed to log client error", error);
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

function setGlobalError(message) {
  const errorEl = document.getElementById("global-error");
  errorEl.textContent = message || "";
}

function setGlobalBusy(message) {
  const busyEl = document.getElementById("global-busy");
  busyEl.textContent = message || "";
}

function setMeetingTitle(title) {
  const input = document.getElementById("meeting-title");
  input.value = title || "";
}

function setAttendeeEditor(attendees) {
  const editor = document.getElementById("attendee-editor");
  const lines = (attendees || [])
    .map((attendee) => attendee.name || attendee.label || attendee.id || "")
    .filter((line) => line);
  editor.value = lines.join("\n");
}

function buildTranscriptText(segments) {
  const attendees = state.meeting?.attendees || [];
  const attendeeMap = new Map(
    attendees.filter((attendee) => attendee.id).map((attendee) => [attendee.id, attendee])
  );

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

function setTranscriptOutput(segments) {
  const output = document.getElementById("transcript-output");
  if (!segments || !segments.length) {
    output.textContent = "No transcript yet.";
    return;
  }
  output.textContent = buildTranscriptText(segments);
}

function setTranscriptStatus(message) {
  const status = document.getElementById("transcript-status");
  status.textContent = message;
}

function setSummaryStatus(message) {
  const status = document.getElementById("summary-status");
  status.textContent = message;
}

function setSummaryOutput(message) {
  const output = document.getElementById("summary-output");
  output.textContent = message;
}

function loadMeetingId() {
  const params = new URLSearchParams(window.location.search);
  const meetingId = params.get("id");
  if (!meetingId) {
    throw new Error("Meeting id missing in URL (?id=...)");
  }
  state.meetingId = meetingId;
}

async function refreshMeeting() {
  // Log immediately at start of function
  fetch("/api/logs/client", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ level: "info", message: "[refreshMeeting] START", context: { meetingId: state.meetingId } }),
  }).catch(() => {});
  
  if (!state.meetingId) {
    return;
  }
  setGlobalBusy("Loading meeting...");
  try {
    const meeting = await fetchJson(`/api/meetings/${state.meetingId}`);
    state.meeting = meeting;
    setMeetingTitle(meeting.title || "");
    setAttendeeEditor(meeting.attendees || []);
    const meetingStatus = meeting.status === "in_progress" ? "In progress" : "Completed";
    if (meeting.transcript?.segments?.length) {
      state.lastTranscriptSegments = meeting.transcript.segments;
      setTranscriptStatus(
        `${meetingStatus} • Transcript (${meeting.transcript.segments.length} segments)`
      );
      if (!state.liveStreaming) {
        setTranscriptOutput(meeting.transcript.segments);
      }
    } else {
      setTranscriptStatus(`${meetingStatus} • No transcript yet.`);
      if (!state.liveStreaming) {
        setTranscriptOutput([]);
      }
    }
    if (meeting.summary_state) {
      const summaryUpdated = meeting.summary_state.updated_at
        ? `Last updated ${meeting.summary_state.updated_at}`
        : "Summary ready";
      setSummaryStatus(`${meetingStatus} • ${summaryUpdated}`);
      const summarized = meeting.summary_state.summarized_summary || "";
      const interim = meeting.summary_state.interim_summary || "";
      setSummaryOutput([summarized, interim].filter(Boolean).join("\n\n") || "No summary yet.");
      updateSummaryDebugPanel(meeting.summary_state);
    } else if (meeting.summary?.text) {
      const summaryUpdated = meeting.summary?.updated_at
        ? `Last updated ${meeting.summary.updated_at}`
        : "Summary ready";
      setSummaryStatus(`${meetingStatus} • ${summaryUpdated}`);
      setSummaryOutput(meeting.summary.text);
      updateSummaryDebugPanel(null);
    } else {
      setSummaryStatus(`${meetingStatus} • No summary yet.`);
      setSummaryOutput("No summary yet.");
      updateSummaryDebugPanel(null);
    }

    if (meeting.status === "in_progress") {
      // Start live transcript only for real recordings (not simulated file transcription)
      if (!meeting.simulated) {
        startLiveTranscript();
      }
      // Start summary refresh for all in-progress meetings
      startSummaryRefresh();
    } else {
      stopLiveTranscript();
      stopSummaryRefresh();
    }
    
    // Update transcription controls (stop/resume buttons)
    fetch("/api/logs/client", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ level: "info", message: "[refreshMeeting] about to call updateTranscriptionControls" }),
    }).catch(() => {});
    await updateTranscriptionControls();
  } catch (error) {
    fetch("/api/logs/client", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ level: "error", message: "[refreshMeeting] error: " + error.message }),
    }).catch(() => {});
    setGlobalError(`Failed to load meeting: ${error.message}`);
  } finally {
    setGlobalBusy("");
  }
}

function startLiveTranscript() {
  if (state.liveController || !state.meetingId) {
    return;
  }
  const controller = new AbortController();
  state.liveController = controller;
  state.liveStreaming = true;
  debugLog("Starting live transcript", { meetingId: state.meetingId });
  streamLiveTranscript(controller)
    .catch((error) => {
      if (controller.signal.aborted) {
        return;
      }
      debugError("Live transcript failed", error);
      setTranscriptStatus(`Live transcript error: ${error.message}`);
      setGlobalError("Live transcript failed.");
      logClientError("Live transcript failed", {
        meeting_id: state.meetingId,
        message: error.message,
        name: error.name,
        stack: error.stack,
      });
    })
    .finally(() => {
      if (state.liveController === controller) {
        state.liveController = null;
      }
      state.liveStreaming = false;
      debugLog("Live transcript ended");
    });
}

function stopLiveTranscript() {
  if (!state.liveController) {
    return;
  }
  debugLog("Stopping live transcript");
  state.liveController.abort();
  state.liveController = null;
  state.liveStreaming = false;
}

async function streamLiveTranscript(controller) {
  const segments = state.lastTranscriptSegments
    ? [...state.lastTranscriptSegments]
    : [];
  let language = "unknown";
  let done = false;

  const response = await fetch("/api/transcribe/live", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: controller.signal,
    body: JSON.stringify({
      meeting_id: state.meetingId,
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
        setTranscriptStatus(`In progress • Live transcript (${language})`);
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
}

async function saveMeetingTitle() {
  if (!state.meetingId) {
    return;
  }
  const title = document.getElementById("meeting-title").value.trim();
  if (!title) {
    setGlobalError("Title cannot be empty.");
    return;
  }
  if (state.meeting?.title === title) {
    return;
  }
  setGlobalBusy("Saving title...");
  try {
    debugLog("Saving meeting title", { title });
    await fetchJson(`/api/meetings/${state.meetingId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, title_source: "manual" }),
    });
    debugLog("Meeting title saved", { meeting_id: state.meetingId, title });
    await refreshMeeting();
  } catch (error) {
    debugError("Meeting title save failed", error);
    logClientError("Meeting title save failed", {
      meeting_id: state.meetingId,
      message: error.message,
      stack: error.stack,
    });
    setGlobalError(`Failed to save title: ${error.message}`);
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
  if (!state.meetingId) {
    return;
  }
  const editor = document.getElementById("attendee-editor");
  const lines = editor.value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  setGlobalBusy("Saving attendees...");
  try {
    const payload = buildAttendeePayload(lines, state.meeting?.attendees || []);
    await fetchJson(`/api/meetings/${state.meetingId}/attendees`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ attendees: payload }),
    });
    await refreshMeeting();
  } catch (error) {
    setGlobalError(`Failed to save attendees: ${error.message}`);
  } finally {
    setGlobalBusy("");
  }
}

async function summarizeMeetingAuto() {
  if (!state.meetingId || state.summaryInFlight) {
    return;
  }
  if (!state.meeting?.transcript?.segments?.length && !state.meeting?.summary_state?.streaming_text) {
    debugLog("Skip auto summary (no transcript yet)");
    return;
  }
  state.summaryInFlight = true;
  debugLog("Auto summary start (step_summary_state)");
  try {
    // Use the smart real-time summary step endpoint instead of full summarize
    await fetchJson(`/api/meetings/${state.meetingId}/summary-state/step`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    await refreshMeeting();
    debugLog("Auto summary step complete");
  } catch (error) {
    debugError("Auto summary step failed", error);
    // Don't show error to user for summary ticks - they're non-critical
    debugLog("Summary tick error (non-critical): " + error.message);
  } finally {
    state.summaryInFlight = false;
  }
}

function startSummaryRefresh() {
  if (state.summaryTimer) {
    return;
  }
  debugLog("Starting summary refresh timer", {
    intervalMs: state.summaryIntervalMs,
  });
  resetCountdown();
  state.summaryTimer = setInterval(() => {
    summarizeMeetingAuto();
    resetCountdown();
  }, state.summaryIntervalMs);
  startCountdown();
}

function stopSummaryRefresh() {
  if (!state.summaryTimer) {
    return;
  }
  debugLog("Stopping summary refresh timer");
  clearInterval(state.summaryTimer);
  state.summaryTimer = null;
  stopCountdown();
}

function resetCountdown() {
  state.countdownSeconds = Math.round(state.summaryIntervalMs / 1000);
  updateCountdownDisplay();
}

function startCountdown() {
  if (state.countdownTimer) {
    return;
  }
  state.countdownTimer = setInterval(() => {
    if (state.countdownSeconds > 0) {
      state.countdownSeconds--;
      updateCountdownDisplay();
    }
  }, 1000);
}

function stopCountdown() {
  if (state.countdownTimer) {
    clearInterval(state.countdownTimer);
    state.countdownTimer = null;
  }
  const display = document.getElementById("countdown-display");
  if (display) {
    display.textContent = "--";
    display.className = "countdown-display";
  }
}

function updateCountdownDisplay() {
  const display = document.getElementById("countdown-display");
  if (!display) return;
  
  display.textContent = state.countdownSeconds;
  
  // Update color based on urgency
  display.className = "countdown-display";
  if (state.countdownSeconds <= 5) {
    display.classList.add("imminent");
  } else if (state.countdownSeconds <= 10) {
    display.classList.add("warning");
  }
}

function doItNow() {
  if (state.summaryInFlight) {
    debugLog("Summary already in flight, skipping do-it-now");
    return;
  }
  debugLog("Do it now triggered");
  
  // Stop the current timer
  if (state.summaryTimer) {
    clearInterval(state.summaryTimer);
    state.summaryTimer = null;
  }
  
  // Run summary immediately
  summarizeMeetingAuto();
  
  // Restart the timer with reset countdown
  resetCountdown();
  state.summaryTimer = setInterval(() => {
    summarizeMeetingAuto();
    resetCountdown();
  }, state.summaryIntervalMs);
}

function updateSummaryInterval(seconds) {
  const newIntervalMs = seconds * 1000;
  if (newIntervalMs === state.summaryIntervalMs) {
    return;
  }
  
  debugLog("Updating summary interval", { seconds, newIntervalMs });
  state.summaryIntervalMs = newIntervalMs;
  
  // Update the display
  const valueEl = document.getElementById("interval-value");
  if (valueEl) {
    valueEl.textContent = seconds;
  }
  
  // If timer is running, restart it with new interval
  if (state.summaryTimer) {
    clearInterval(state.summaryTimer);
    state.summaryTimer = null;
    resetCountdown();
    state.summaryTimer = setInterval(() => {
      summarizeMeetingAuto();
      resetCountdown();
    }, state.summaryIntervalMs);
  }
}

function updateSummaryDebugPanel(summaryState) {
  const panel = document.getElementById("summary-debug-panel");
  if (!panel || panel.style.display === "none") {
    return;
  }
  const doneEl = document.getElementById("debug-done");
  const draftEl = document.getElementById("debug-draft");
  const streamingEl = document.getElementById("debug-streaming");
  const summarizedEl = document.getElementById("debug-summarized");
  const interimEl = document.getElementById("debug-interim");
  if (!summaryState) {
    if (doneEl) doneEl.value = "";
    if (draftEl) draftEl.value = "";
    if (streamingEl) streamingEl.value = "";
    if (summarizedEl) summarizedEl.value = "";
    if (interimEl) interimEl.value = "";
    return;
  }
  if (doneEl) {
    doneEl.value = summaryState.done_text || "";
    doneEl.scrollTop = doneEl.scrollHeight;
  }
  if (draftEl) {
    draftEl.value = summaryState.draft_text || "";
    draftEl.scrollTop = draftEl.scrollHeight;
  }
  if (streamingEl) {
    streamingEl.value = summaryState.streaming_text || "";
    streamingEl.scrollTop = streamingEl.scrollHeight;
  }
  if (summarizedEl) {
    summarizedEl.value = summaryState.summarized_summary || "";
    summarizedEl.scrollTop = summarizedEl.scrollHeight;
  }
  if (interimEl) {
    interimEl.value = summaryState.interim_summary || "";
    interimEl.scrollTop = interimEl.scrollHeight;
  }
}

function scheduleTitleSave() {
  if (state.titleSaveTimer) {
    clearTimeout(state.titleSaveTimer);
  }
  state.titleSaveTimer = setTimeout(() => {
    saveMeetingTitle();
  }, 600);
}

async function deleteMeeting() {
  if (!state.meetingId) {
    return;
  }
  setGlobalBusy("Deleting meeting...");
  try {
    await fetchJson(`/api/meetings/${state.meetingId}`, { method: "DELETE" });
    window.location.href = "/";
  } catch (error) {
    setGlobalError(`Failed to delete meeting: ${error.message}`);
  } finally {
    setGlobalBusy("");
  }
}

function exportMeeting() {
  if (!state.meetingId) {
    return;
  }
  window.open(`/api/meetings/${state.meetingId}/export`, "_blank");
}

// Track the first server version we see to detect updates
let initialServerVersion = null;

async function refreshVersion() {
  try {
    const data = await fetchJson("/api/health");
    const badge = document.getElementById("version-badge");
    badge.textContent = data.version;
    
    // Track version changes and show alert if server was updated
    if (data.version) {
      if (initialServerVersion === null) {
        initialServerVersion = data.version;
      } else if (data.version !== initialServerVersion) {
        showVersionUpdateBanner();
      }
    }
  } catch (error) {
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

async function getActiveTranscription() {
  try {
    return await fetchJson("/api/transcribe/active");
  } catch (error) {
    debugError("Failed to get active transcription", error);
    return { active: false, type: null, meeting_id: null };
  }
}

async function updateTranscriptionControls() {
  const stopBtn = document.getElementById("stop-transcription");
  const resumeBtn = document.getElementById("resume-transcription");
  const statusBadge = document.getElementById("transcription-status-badge");
  
  const logToServer = (message, context) => {
    fetch("/api/logs/client", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ level: "info", message: `[TranscriptionControls] ${message}`, context }),
    }).catch(() => {});
  };
  
  logToServer("called", { 
    stopBtn: !!stopBtn, 
    resumeBtn: !!resumeBtn, 
    statusBadge: !!statusBadge 
  });
  
  if (!stopBtn || !resumeBtn || !statusBadge) {
    logToServer("missing elements, returning");
    return;
  }
  
  const meeting = state.meeting;
  if (!meeting) {
    logToServer("no meeting");
    stopBtn.style.display = "none";
    resumeBtn.style.display = "none";
    statusBadge.textContent = "";
    statusBadge.className = "status-badge";
    return;
  }
  
  const active = await getActiveTranscription();
  const isThisMeetingActive = active.active && active.meeting_id === state.meetingId;
  const isAnyActive = active.active;
  const meetingStatus = meeting.status;
  
  logToServer("state", {
    meetingStatus,
    audioPath: meeting.audio_path,
    isThisMeetingActive,
    isAnyActive,
    active
  });
  
  // Show stop button only if this meeting is currently transcribing
  if (isThisMeetingActive) {
    logToServer("showing stop (this meeting active)");
    stopBtn.style.display = "inline-block";
    resumeBtn.style.display = "none";
    statusBadge.textContent = "Transcribing";
    statusBadge.className = "status-badge in-progress";
  } else if (meetingStatus === "in_progress") {
    // Meeting is in_progress but transcription stopped (shouldn't happen normally)
    logToServer("in_progress but not active, showing resume");
    stopBtn.style.display = "none";
    resumeBtn.style.display = isAnyActive ? "none" : "inline-block";
    statusBadge.textContent = isAnyActive ? "Paused (another active)" : "Paused";
    statusBadge.className = isAnyActive ? "status-badge blocked" : "status-badge in-progress";
  } else if (meetingStatus === "completed" && meeting.audio_path) {
    // Meeting is completed but has audio - can resume
    logToServer("completed with audio, showing resume");
    stopBtn.style.display = "none";
    resumeBtn.style.display = isAnyActive ? "none" : "inline-block";
    statusBadge.textContent = isAnyActive ? "Completed (another active)" : "Completed";
    statusBadge.className = isAnyActive ? "status-badge blocked" : "status-badge completed";
  } else {
    // No audio path or other state
    logToServer("else branch - hiding all", { meetingStatus, audioPath: meeting.audio_path });
    stopBtn.style.display = "none";
    resumeBtn.style.display = "none";
    statusBadge.textContent = meetingStatus === "completed" ? "Completed" : "";
    statusBadge.className = "status-badge completed";
  }
}

async function stopTranscription() {
  if (!state.meetingId) return;
  
  setGlobalBusy("Stopping transcription...");
  try {
    await fetchJson(`/api/transcribe/stop/${state.meetingId}`, { method: "POST" });
    debugLog("Transcription stopped", { meetingId: state.meetingId });
    await refreshMeeting();
  } catch (error) {
    setGlobalError(`Failed to stop transcription: ${error.message}`);
    debugError("Stop transcription failed", error);
  } finally {
    setGlobalBusy("");
  }
}

async function resumeTranscription() {
  if (!state.meetingId) return;
  
  setGlobalBusy("Resuming transcription...");
  try {
    await fetchJson(`/api/transcribe/resume/${state.meetingId}`, { method: "POST" });
    debugLog("Transcription resumed", { meetingId: state.meetingId });
    await refreshMeeting();
  } catch (error) {
    setGlobalError(`Failed to resume transcription: ${error.message}`);
    debugError("Resume transcription failed", error);
  } finally {
    setGlobalBusy("");
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  try {
    loadMeetingId();
  } catch (error) {
    setGlobalError(error.message);
    return;
  }

  const titleInput = document.getElementById("meeting-title");
  if (titleInput) {
    titleInput.addEventListener("input", scheduleTitleSave);
  }
  const saveTitleButton = document.getElementById("save-title");
  if (saveTitleButton) {
    saveTitleButton.addEventListener("click", saveMeetingTitle);
  }
  document
    .getElementById("save-attendees")
    .addEventListener("click", saveAttendees);
  document
    .getElementById("delete-meeting")
    .addEventListener("click", deleteMeeting);
  document
    .getElementById("export-meeting")
    .addEventListener("click", exportMeeting);
  document.getElementById("back-home").addEventListener("click", () => {
    window.location.href = "/";
  });
  
  // Transcription controls
  const stopBtn = document.getElementById("stop-transcription");
  if (stopBtn) {
    stopBtn.addEventListener("click", stopTranscription);
  }
  const resumeBtn = document.getElementById("resume-transcription");
  if (resumeBtn) {
    resumeBtn.addEventListener("click", resumeTranscription);
  }
  
  document
    .getElementById("toggle-summary-debug")
    .addEventListener("click", () => {
      const panel = document.getElementById("summary-debug-panel");
      if (!panel) return;
      const isHidden = panel.style.display === "none" || !panel.style.display;
      panel.style.display = isHidden ? "block" : "none";
      if (isHidden) {
        updateSummaryDebugPanel(state.meeting?.summary_state || null);
        // Initialize countdown display when panel opens
        if (state.summaryTimer) {
          updateCountdownDisplay();
        }
      }
    });

  // Do it now button
  const doItNowButton = document.getElementById("do-it-now");
  if (doItNowButton) {
    doItNowButton.addEventListener("click", doItNow);
  }

  // Interval slider
  const intervalSlider = document.getElementById("interval-slider");
  if (intervalSlider) {
    // Initialize slider to current value
    intervalSlider.value = Math.round(state.summaryIntervalMs / 1000);
    const valueEl = document.getElementById("interval-value");
    if (valueEl) {
      valueEl.textContent = intervalSlider.value;
    }
    
    intervalSlider.addEventListener("input", (e) => {
      const seconds = parseInt(e.target.value, 10);
      const valueEl = document.getElementById("interval-value");
      if (valueEl) {
        valueEl.textContent = seconds;
      }
    });
    
    intervalSlider.addEventListener("change", (e) => {
      const seconds = parseInt(e.target.value, 10);
      updateSummaryInterval(seconds);
    });
  }
  window.addEventListener("beforeunload", () => {
    stopLiveTranscript();
    stopSummaryRefresh();
  });

  await refreshVersion();
  await refreshMeeting();
  setInterval(refreshMeeting, 5000);
});
