const state = {
  meetingId: null,
  meeting: null,
  lastTranscriptSegments: null,
  liveController: null,
  liveStreaming: false,
  titleSaveTimer: null,
  selectedAttendeeId: null,
  renameMode: false,
  pollIntervalId: null,
  showRawSegments: false,
  eventsSource: null,  // SSE connection for meeting events
};

// Polling removed - using SSE for all real-time updates
// Keep these stub functions for any legacy code paths
function meetingNeedsPolling() {
  return false; // Never poll, SSE handles updates
}

function startPollingIfNeeded() {
  // No-op: SSE subscription handles all updates
}

function stopPolling() {
  if (state.pollIntervalId) {
    clearInterval(state.pollIntervalId);
    state.pollIntervalId = null;
  }
}

// SSE subscription for real-time meeting events (including streaming summary)
function subscribeToMeetingEvents() {
  if (state.eventsSource) {
    state.eventsSource.close();
  }
  
  state.eventsSource = new EventSource("/api/meetings/events");
  
  state.eventsSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      
      // Only handle events for this meeting
      if (data.meeting_id !== state.meetingId) return;
      
      // #region agent log
      if (data.type === "summary_start" || data.type === "summary_complete" || 
          (data.type === "summary_token" && Math.random() < 0.05)) {
        fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:subscribeToMeetingEvents',message:'event_received',data:{type:data.type,hasText:!!data.data?.text,textLen:data.data?.text?.length},timestamp:Date.now(),hypothesisId:'H7'})}).catch(()=>{});
      }
      // #endregion
      
      handleMeetingEvent(data);
    } catch (e) {
      // Ignore parse errors (heartbeats, etc.)
    }
  };
  
  state.eventsSource.onerror = () => {
    // Reconnect after a delay
    setTimeout(() => {
      if (state.meetingId) {
        subscribeToMeetingEvents();
      }
    }, 3000);
  };
}

function unsubscribeFromMeetingEvents() {
  if (state.eventsSource) {
    state.eventsSource.close();
    state.eventsSource = null;
  }
}

function handleMeetingEvent(event) {
  const summaryEl = document.getElementById("manual-summary");
  const summaryOutputEl = document.getElementById("summary-output");
  
  switch (event.type) {
    case "summary_start":
      // Clear summary areas when streaming starts
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:handleMeetingEvent',message:'summary_start',data:{meetingId:state.meetingId},timestamp:Date.now(),hypothesisId:'SUMFIX'})}).catch(()=>{});
      // #endregion
      if (summaryEl) summaryEl.value = "";
      if (summaryOutputEl) summaryOutputEl.textContent = "";
      setSummaryStatus("Generating summary...");
      break;
      
    case "summary_token":
      // Progressive update with accumulated text
      if (event.data?.text) {
        if (summaryEl) {
          summaryEl.value = event.data.text;
          summaryEl.scrollTop = summaryEl.scrollHeight;
        }
        if (summaryOutputEl) {
          summaryOutputEl.textContent = event.data.text;
        }
      }
      break;
      
    case "summary_complete":
      // Final summary received
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:handleMeetingEvent',message:'summary_complete',data:{meetingId:state.meetingId,textLen:event.data?.text?.length||0,textPreview:(event.data?.text||'').substring(0,100)},timestamp:Date.now(),hypothesisId:'SUMFIX'})}).catch(()=>{});
      // #endregion
      if (event.data?.text) {
        if (summaryEl) {
          summaryEl.value = event.data.text;
          summaryEl.scrollTop = summaryEl.scrollHeight;
        }
        if (summaryOutputEl) {
          summaryOutputEl.textContent = event.data.text;
        }
      }
      setSummaryStatus("Summary complete.");
      // Refresh to get the complete final meeting state (action items, etc.)
      refreshMeeting();
      break;
    
    case "status_updated":
      // Meeting status changed (in_progress, completed, etc.)
      if (event.data?.status) {
        if (state.meeting) {
          state.meeting.status = event.data.status;
          state.meeting.ended_at = event.data.ended_at;
        }
        updateTranscriptionControls();
        // Update UI status displays
        const meetingStatus = event.data.status === "in_progress" ? "In progress" : "Completed";
        const transcriptCount = state.meeting?.transcript?.segments?.length || 0;
        if (transcriptCount > 0) {
          setTranscriptStatus(`${meetingStatus} • Transcript (${transcriptCount} segments)`);
        } else {
          setTranscriptStatus(`${meetingStatus} • No transcript yet.`);
        }
      }
      break;
    
    case "title_updated":
      // Title changed
      if (event.data?.title) {
        if (state.meeting) {
          state.meeting.title = event.data.title;
        }
        setMeetingTitle(event.data.title);
      }
      break;
    
    case "attendees_updated":
      // Attendees list changed
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:attendees_updated',message:'SSE attendees_updated received',data:{attendeesCount:event.data?.attendees?.length||0,attendeeIds:(event.data?.attendees||[]).map(a=>a.id).slice(0,5)},timestamp:Date.now(),runId:'attendee-debug',hypothesisId:'H4'})}).catch(()=>{});
      // #endregion
      if (event.data?.attendees) {
        if (state.meeting) {
          state.meeting.attendees = event.data.attendees;
        }
        setAttendeeEditor(event.data.attendees);
      }
      break;
    
    case "transcript_segment":
      // Single new transcript segment added
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:handleMeetingEvent',message:'transcript_segment',data:{meetingId:state.meetingId,segmentText:(event.data?.segment?.text||'').substring(0,50)},timestamp:Date.now(),hypothesisId:'TXFIX'})}).catch(()=>{});
      // #endregion
      if (event.data?.segment && state.meeting) {
        if (!state.meeting.transcript) {
          state.meeting.transcript = { segments: [] };
        }
        state.meeting.transcript.segments.push(event.data.segment);
        state.lastTranscriptSegments = state.meeting.transcript.segments;
        // Only update display if not in live streaming mode (live streaming has its own SSE)
        if (!state.liveStreaming) {
          setTranscriptOutput(state.meeting.transcript.segments);
        }
        // Also update the debug panel transcript
        updateSummaryDebugPanel(state.meeting);
        const meetingStatus = state.meeting.status === "in_progress" ? "In progress" : "Completed";
        setTranscriptStatus(`${meetingStatus} • Transcript (${state.meeting.transcript.segments.length} segments)`);
      }
      break;
    
    case "transcript_updated":
      // Full transcript update (e.g., after diarization)
      if (event.data?.segments && state.meeting) {
        if (!state.meeting.transcript) {
          state.meeting.transcript = { segments: [] };
        }
        state.meeting.transcript.segments = event.data.segments;
        state.lastTranscriptSegments = event.data.segments;
        if (!state.liveStreaming) {
          setTranscriptOutput(event.data.segments);
        }
        const meetingStatus = state.meeting.status === "in_progress" ? "In progress" : "Completed";
        setTranscriptStatus(`${meetingStatus} • Transcript (${event.data.segments.length} segments)`);
      }
      break;
    
    case "finalization_status":
      // Finalization progress update
      showFinalizationStatus(event.status_text, event.progress);
      break;
      
    case "meeting_updated":
      // General meeting update - do a full refresh
      refreshMeeting();
      break;
  }
}

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

function showFinalizationStatus(statusText, progress = null) {
  const container = document.getElementById("finalization-status");
  const textEl = document.getElementById("finalization-status-text");
  const progressBar = document.getElementById("finalization-progress-bar");
  const progressFill = document.getElementById("finalization-progress-fill");
  
  if (!container) return;
  
  container.style.display = "flex";
  if (textEl) textEl.textContent = statusText || "Processing...";
  
  if (progress !== null && progress !== undefined) {
    if (progressBar) progressBar.style.display = "block";
    if (progressFill) progressFill.style.width = `${Math.round(progress * 100)}%`;
  } else {
    if (progressBar) progressBar.style.display = "none";
  }
}

function hideFinalizationStatus() {
  const container = document.getElementById("finalization-status");
  if (container) container.style.display = "none";
}

function updateFinalizationStatusFromMeeting(meeting) {
  const finStatus = meeting?.finalization_status;
  if (finStatus && finStatus.status_text) {
    showFinalizationStatus(finStatus.status_text, finStatus.progress);
  } else {
    hideFinalizationStatus();
  }
}

function setMeetingTitle(title) {
  const input = document.getElementById("meeting-title");
  input.value = title || "";
}

function getSegmentsForAttendee(attendeeId) {
  const transcript = state.meeting?.transcript || {};
  const segments = transcript.segments || [];
  return segments.filter(
    (seg) => seg.speaker_id === attendeeId || seg.speaker === attendeeId
  );
}

function formatTimestamp(seconds) {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function renderAttendeesList(attendees) {
  const listEl = document.getElementById("attendees-list");
  if (!listEl) return;

  if (!attendees || attendees.length === 0) {
    listEl.innerHTML = '<div class="attendees-empty">No attendees detected yet.</div>';
    return;
  }

  listEl.innerHTML = attendees
    .map((attendee) => {
      const segmentCount = getSegmentsForAttendee(attendee.id).length;
      const name = attendee.name || attendee.label || attendee.id || "Unknown";
      const isSelected = state.selectedAttendeeId === attendee.id;
      const isRenaming = state.renameMode && state.selectedAttendeeId === attendee.id;
      
      if (isRenaming) {
        return `
          <div class="attendee-item selected renaming" data-attendee-id="${attendee.id}">
            <input type="text" class="attendee-inline-input" value="${escapeHtml(name)}" />
            <button class="icon-btn save-rename-inline" title="Save">&#10003;</button>
            <button class="icon-btn cancel-rename-inline" title="Cancel">&#10005;</button>
          </div>
        `;
      }
      
      return `
        <div class="attendee-item ${isSelected ? "selected" : ""}" 
             data-attendee-id="${attendee.id}">
          <span class="attendee-item-name">${escapeHtml(name)}</span>
          <div class="attendee-item-actions">
            <button class="icon-btn rename-inline" title="Rename">&#9998;</button>
            <button class="icon-btn auto-rename-inline" title="Auto-identify">&#10024;</button>
          </div>
          <span class="attendee-item-count">${segmentCount}</span>
        </div>
      `;
    })
    .join("");

  // Add click handlers for selecting attendees
  listEl.querySelectorAll(".attendee-item").forEach((item) => {
    // Click on row (but not buttons) selects the attendee
    item.addEventListener("click", (e) => {
      if (e.target.closest(".icon-btn") || e.target.closest("input")) return;
      selectAttendee(item.dataset.attendeeId);
    });
  });
  
  // Add handlers for inline rename button
  listEl.querySelectorAll(".rename-inline").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const attendeeId = btn.closest(".attendee-item").dataset.attendeeId;
      state.selectedAttendeeId = attendeeId;
      enterRenameMode();
    });
  });
  
  // Add handlers for inline auto-rename button
  listEl.querySelectorAll(".auto-rename-inline").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const attendeeId = btn.closest(".attendee-item").dataset.attendeeId;
      state.selectedAttendeeId = attendeeId;
      autoRenameAttendee();
    });
  });
  
  // Add handlers for save/cancel in rename mode
  listEl.querySelectorAll(".save-rename-inline").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const input = btn.closest(".attendee-item").querySelector(".attendee-inline-input");
      if (input) {
        saveAttendeeNameInline(input.value);
      }
    });
  });
  
  listEl.querySelectorAll(".cancel-rename-inline").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      cancelRename();
    });
  });
  
  // Handle Enter/Escape in inline input
  listEl.querySelectorAll(".attendee-inline-input").forEach((input) => {
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        saveAttendeeNameInline(input.value);
      } else if (e.key === "Escape") {
        e.preventDefault();
        cancelRename();
      }
    });
    // Focus the input
    input.focus();
    input.select();
  });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function selectAttendee(attendeeId) {
  state.selectedAttendeeId = attendeeId;
  state.renameMode = false;

  // Update list selection
  document.querySelectorAll(".attendee-item").forEach((item) => {
    item.classList.toggle("selected", item.dataset.attendeeId === attendeeId);
  });

  // Find attendee
  const attendees = state.meeting?.attendees || [];
  const attendee = attendees.find((a) => a.id === attendeeId);

  if (!attendee) {
    clearAttendeeDetail();
    return;
  }

  const segmentsEl = document.getElementById("attendee-segments");

  // Clear status
  setAutoRenameStatus("");

  // Render segments
  const segments = getSegmentsForAttendee(attendeeId);
  if (segmentsEl) {
    if (segments.length === 0) {
      segmentsEl.innerHTML =
        '<div class="attendee-segments-placeholder">No spoken content found for this attendee.</div>';
    } else {
      segmentsEl.innerHTML = segments
        .map(
          (seg) => `
          <div class="attendee-segment-item">
            <div class="attendee-segment-time">${formatTimestamp(seg.start)} - ${formatTimestamp(seg.end)}</div>
            <div class="attendee-segment-text">${escapeHtml(seg.text)}</div>
          </div>
        `
        )
        .join("");
      // Scroll to bottom
      segmentsEl.scrollTop = segmentsEl.scrollHeight;
    }
  }
}

function clearAttendeeDetail() {
  const segmentsEl = document.getElementById("attendee-segments");
  hideRenameMode();
  setAutoRenameStatus("");

  if (segmentsEl) {
    segmentsEl.innerHTML = "";
  }
}

function enterRenameMode() {
  state.renameMode = true;
  // Re-render the attendees list to show the inline input
  renderAttendeesList(state.meeting?.attendees || []);
}

function hideRenameMode() {
  state.renameMode = false;
}

function cancelRename() {
  hideRenameMode();
  // Re-render to show normal view
  renderAttendeesList(state.meeting?.attendees || []);
  // Re-select to refresh the detail panel
  if (state.selectedAttendeeId) {
    selectAttendee(state.selectedAttendeeId);
  }
}

async function saveAttendeeNameInline(newName) {
  if (!state.meetingId || !state.selectedAttendeeId) return;

  newName = newName?.trim();
  if (!newName) {
    setGlobalError("Name cannot be empty.");
    return;
  }

  setGlobalBusy("Saving name...");
  try {
    await fetchJson(
      `/api/meetings/${state.meetingId}/attendees/${state.selectedAttendeeId}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName }),
      }
    );
    debugLog("Attendee name saved", { attendeeId: state.selectedAttendeeId, name: newName });
    state.renameMode = false;
    await refreshMeeting();
    // Re-select to refresh the detail panel
    selectAttendee(state.selectedAttendeeId);
  } catch (error) {
    setGlobalError(`Failed to save name: ${error.message}`);
  } finally {
    setGlobalBusy("");
  }
}

// Legacy function for compatibility
async function saveAttendeeName() {
  const input = document.querySelector(".attendee-inline-input");
  if (input) {
    await saveAttendeeNameInline(input.value);
  }
}

function setAutoRenameStatus(message, type = "") {
  const statusEl = document.getElementById("auto-rename-status");
  if (statusEl) {
    statusEl.textContent = message;
    statusEl.className = "auto-rename-status" + (type ? ` ${type}` : "");
  }
}

async function autoRenameAttendee() {
  if (!state.meetingId || !state.selectedAttendeeId) return;

  setAutoRenameStatus("Analyzing speech to identify name...", "loading");

  try {
    const result = await fetchJson(
      `/api/meetings/${state.meetingId}/attendees/${state.selectedAttendeeId}/auto-rename`,
      { method: "POST" }
    );

    const { suggested_name, confidence, reasoning } = result;

    if (suggested_name === "Unknown Speaker") {
      setAutoRenameStatus(
        `Could not identify name. ${reasoning || ""}`,
        "error"
      );
      return;
    }

    // Show suggestion and auto-apply if confidence is high
    const confidenceText = confidence === "high" ? "" : ` (${confidence} confidence)`;
    setAutoRenameStatus(
      `Suggested: ${suggested_name}${confidenceText}. ${reasoning || ""}`,
      "success"
    );

    // Auto-apply the name
    await fetchJson(
      `/api/meetings/${state.meetingId}/attendees/${state.selectedAttendeeId}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: suggested_name }),
      }
    );

    debugLog("Auto-rename applied", {
      attendeeId: state.selectedAttendeeId,
      name: suggested_name,
      confidence,
    });

    await refreshMeeting();
    selectAttendee(state.selectedAttendeeId);
    setAutoRenameStatus(`Renamed to "${suggested_name}"`, "success");
  } catch (error) {
    debugError("Auto-rename failed", error);
    setAutoRenameStatus(`Failed: ${error.message}`, "error");
  }
}

function setAttendeeEditor(attendees) {
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:setAttendeeEditor',message:'setAttendeeEditor called',data:{attendeesCount:(attendees||[]).length,attendeeIds:(attendees||[]).map(a=>a.id).slice(0,5)},timestamp:Date.now(),runId:'attendee-debug',hypothesisId:'H4,H5'})}).catch(()=>{});
  // #endregion
  // Render the new attendee list UI
  renderAttendeesList(attendees);

  // If we had a selected attendee, re-select it
  if (state.selectedAttendeeId) {
    const stillExists = (attendees || []).some((a) => a.id === state.selectedAttendeeId);
    if (stillExists) {
      selectAttendee(state.selectedAttendeeId);
    } else {
      state.selectedAttendeeId = null;
      clearAttendeeDetail();
    }
  }
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

function setManualSummaryStatus(message) {
  const el = document.getElementById("manual-summary-status");
  if (!el) return;
  el.textContent = message || "";
}

function setManualTranscriptionBuffer(text) {
  const el = document.getElementById("manual-transcription");
  if (!el) return;
  // Only auto-scroll if user was already at bottom (within 5px threshold)
  const wasAtBottom = (el.scrollHeight - el.scrollTop - el.clientHeight) <= 5;
  el.value = text || "";
  if (wasAtBottom) {
    el.scrollTop = el.scrollHeight;
  }
}

function buildTranscriptTextSafe(meeting) {
  const segments = meeting?.transcript?.segments || [];
  return segments.length ? buildTranscriptText(segments) : "";
}

let manualBuffersSaveTimer = null;

function scheduleManualBuffersSave() {
  if (!state.meetingId) return;
  if (manualBuffersSaveTimer) {
    clearTimeout(manualBuffersSaveTimer);
  }
  manualBuffersSaveTimer = setTimeout(async () => {
    const notesEl = document.getElementById("manual-notes");
    const summaryEl = document.getElementById("manual-summary");
    const manualNotes = notesEl?.value ?? "";
    const manualSummary = summaryEl?.value ?? "";
    try {
      await fetchJson(`/api/meetings/${state.meetingId}/manual-buffers`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ manual_notes: manualNotes, manual_summary: manualSummary }),
      });
      setManualSummaryStatus("Saved.");
    } catch (error) {
      setManualSummaryStatus(`Save failed: ${error.message}`);
    }
  }, 600);
}

async function manualSummarize() {
  if (!state.meetingId) return;

  const transcriptText = buildTranscriptTextSafe(state.meeting);
  if (!transcriptText.trim()) {
    setManualSummaryStatus("No transcript yet.");
    return;
  }

  const button = document.getElementById("manual-summarize");
  if (button) button.disabled = true;
  setManualSummaryStatus("Summarizing…");
  setGlobalBusy("Summarizing...");

  // Clear both summary areas before streaming
  const summaryEl = document.getElementById("manual-summary");
  const summaryOutputEl = document.getElementById("summary-output");
  if (summaryEl) summaryEl.value = "";
  if (summaryOutputEl) summaryOutputEl.textContent = "";

  try {
    // Use streaming endpoint
    const response = await fetch(`/api/meetings/${state.meetingId}/summarize-stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript_text: transcriptText }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || `Request failed: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let accumulatedText = "";
    let buffer = "";

    // #region agent log
    let _chunkCount = 0;
    let _tokenCount = 0;
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:manualSummarize',message:'stream_reader_start',data:{},timestamp:Date.now(),hypothesisId:'H3'})}).catch(()=>{});
    // #endregion

    while (true) {
      const { done, value } = await reader.read();
      // #region agent log
      _chunkCount++;
      if (_chunkCount <= 10 || _chunkCount % 20 === 0) {
        const chunkLen = value ? value.length : 0;
        fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:manualSummarize',message:'chunk_received',data:{chunkNum:_chunkCount,chunkLen,done},timestamp:Date.now(),hypothesisId:'H3'})}).catch(()=>{});
      }
      // #endregion
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || ""; // Keep incomplete line in buffer

      for (const line of lines) {
        const trimmedLine = line.trim();
        if (!trimmedLine || !trimmedLine.startsWith("data: ")) continue;

        const dataStr = trimmedLine.slice(6); // Remove "data: " prefix
        if (dataStr === "[DONE]") {
          // Stream completed
          continue;
        }

        try {
          const data = JSON.parse(dataStr);
          if (data.token) {
            accumulatedText += data.token;
            // #region agent log
            _tokenCount++;
            if (_tokenCount <= 5 || _tokenCount % 20 === 0) {
              fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:manualSummarize',message:'token_parsed',data:{tokenNum:_tokenCount,accLen:accumulatedText.length},timestamp:Date.now(),hypothesisId:'H3,H5'})}).catch(()=>{});
            }
            // #endregion
            // Update both textareas progressively
            if (summaryEl) {
              summaryEl.value = accumulatedText;
              summaryEl.scrollTop = summaryEl.scrollHeight;
            }
            if (summaryOutputEl) {
              summaryOutputEl.textContent = accumulatedText;
            }
            setManualSummaryStatus("Receiving summary...");
          } else if (data.error) {
            throw new Error(data.error);
          }
        } catch (parseError) {
          if (parseError.message && !parseError.message.includes("JSON")) {
            throw parseError;
          }
          // Ignore JSON parse errors for incomplete data
        }
      }
    }
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:manualSummarize',message:'stream_complete',data:{totalChunks:_chunkCount,totalTokens:_tokenCount,finalLen:accumulatedText.length},timestamp:Date.now(),hypothesisId:'H3'})}).catch(()=>{});
    // #endregion

    setManualSummaryStatus("Summary complete.");
    // Schedule a save to persist the streamed summary
    scheduleManualBuffersSave();
    // Don't refresh meeting here - it would overwrite the textarea with stale data
    // before the scheduled save completes. The streamed content is already displayed.
  } catch (error) {
    setManualSummaryStatus(`Summarize failed: ${error.message}`);
    debugError("Streaming summarization failed", error);
  } finally {
    setGlobalBusy("");
    if (button) button.disabled = false;
  }
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
    // Always fetch consolidated segments for main display
    const meeting = await fetchJson(`/api/meetings/${state.meetingId}`);
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:refreshMeeting',message:'meeting fetched',data:{attendeesCount:(meeting.attendees||[]).length,attendeeIds:(meeting.attendees||[]).map(a=>a.id).slice(0,5),segmentsCount:(meeting.transcript?.segments||[]).length},timestamp:Date.now(),runId:'attendee-debug',hypothesisId:'H5'})}).catch(()=>{});
    // #endregion
    state.meeting = meeting;
    setMeetingTitle(meeting.title || "");
    setAttendeeEditor(meeting.attendees || []);
    updateFinalizationStatusFromMeeting(meeting);
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
    if (meeting.summary?.text) {
      const summaryUpdated = meeting.summary?.updated_at
        ? `Last updated ${meeting.summary.updated_at}`
        : "Summary ready";
      setSummaryStatus(`${meetingStatus} • ${summaryUpdated}`);
      setSummaryOutput(meeting.summary.text);
      updateSummaryDebugPanel(meeting);
    } else {
      setSummaryStatus(`${meetingStatus} • No summary yet.`);
      setSummaryOutput("No summary yet.");
      updateSummaryDebugPanel(meeting);
    }

    // Only start live transcript when this meeting is actually actively transcribing.
    // If a meeting is "in_progress" but not currently active (paused/stopped), starting
    // `/api/transcribe/live` causes an SSE error ("Not recording") and can lead to a tight loop.
    const active = await getActiveTranscription();
    const isThisMeetingActive = active.active && active.meeting_id === state.meetingId;
    if (isThisMeetingActive && meeting.status === "in_progress" && !meeting.simulated) {
      startLiveTranscript();
    } else {
      stopLiveTranscript();
    }
    
    // Update transcription controls (stop/resume buttons)
    fetch("/api/logs/client", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ level: "info", message: "[refreshMeeting] about to call updateTranscriptionControls" }),
    }).catch(() => {});
    await updateTranscriptionControls();
    
    // SSE subscription handles all real-time updates
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
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app/static/meeting.js:startLiveTranscript',message:'startLiveTranscript enter',data:{meetingId:state.meetingId,hasController:!!state.liveController,meetingStatus:state.meeting?.status||null},timestamp:Date.now(),runId:'pre-fix',hypothesisId:'LOOP1'})}).catch(()=>{});
  // #endregion
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

  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app/static/meeting.js:streamLiveTranscript',message:'fetch live start',data:{meetingId:state.meetingId,segmentsSeeded:segments.length},timestamp:Date.now(),runId:'pre-fix',hypothesisId:'LOOP1'})}).catch(()=>{});
  // #endregion
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
        // #region agent log
        fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:streamLiveTranscript',message:'segment_received',data:{meetingId:state.meetingId,segIdx:segments.length,start:event.start,end:event.end,textLen:(event.text||'').length,textPreview:(event.text||'').slice(0,50)},timestamp:Date.now(),runId:'bugs-debug',hypothesisId:'H3b'})}).catch(()=>{});
        // #endregion
        segments.push(event);
        state.lastTranscriptSegments = segments;
        setTranscriptOutput(segments);
        // #region agent log
        fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:streamLiveTranscript',message:'setTranscriptOutput_called',data:{meetingId:state.meetingId,segmentsCount:segments.length},timestamp:Date.now(),runId:'bugs-debug',hypothesisId:'H3b'})}).catch(()=>{});
        // #endregion
        setManualTranscriptionBuffer(buildTranscriptText(segments));
      } else if (event.type === "done") {
        done = true;
      } else if (event.type === "error") {
        // Handle "Not recording" as a graceful stop, not an error
        // This happens when the recording was stopped before we connected
        if (event.message === "Not recording") {
          // #region agent log
          fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app/static/meeting.js:streamLiveTranscript',message:'live got Not recording error event',data:{meetingId:state.meetingId,meetingStatus:state.meeting?.status||null},timestamp:Date.now(),runId:'pre-fix',hypothesisId:'LOOP1'})}).catch(()=>{});
          // #endregion
          debugLog("Live transcript: recording already stopped");
          done = true;
          // Refresh meeting to get the updated status
          refreshMeeting().catch(() => {});
        } else {
          throw new Error(event.message || "Live transcription failed");
        }
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

// Attendee saving is now done via inline rename - see saveAttendeeName()

async function updateSummaryDebugPanel(meeting) {
  const panel = document.getElementById("summary-debug-panel");
  if (!panel || panel.style.display === "none") {
    return;
  }
  
  // If showing raw segments, fetch them separately for the debug panel
  if (state.showRawSegments && state.meetingId) {
    try {
      const rawMeeting = await fetchJson(`/api/meetings/${state.meetingId}?raw=true`);
      setManualTranscriptionBuffer(buildTranscriptTextSafe(rawMeeting));
    } catch (e) {
      // Fall back to consolidated if raw fetch fails
      setManualTranscriptionBuffer(buildTranscriptTextSafe(meeting));
    }
  } else {
    setManualTranscriptionBuffer(buildTranscriptTextSafe(meeting));
  }

  const notesEl = document.getElementById("manual-notes");
  if (notesEl && notesEl.value !== (meeting?.manual_notes || "")) {
    notesEl.value = meeting?.manual_notes || "";
  }
  const summaryEl = document.getElementById("manual-summary");
  // Use manual_summary if present, otherwise fall back to the auto-generated summary
  const summaryText = meeting?.manual_summary || meeting?.summary?.text || "";
  if (summaryEl && summaryEl.value !== summaryText) {
    summaryEl.value = summaryText;
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
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app/static/meeting.js:updateTranscriptionControls',message:'BUG: showing Paused state',data:{meetingId:state.meetingId,meetingStatus,isThisMeetingActive,isAnyActive,active,audioPath:meeting.audio_path},timestamp:Date.now(),runId:'pre-fix',hypothesisId:'H3-UI-PAUSED'})}).catch(()=>{});
    // #endregion
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
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app/static/meeting.js:stopTranscription',message:'stop click',data:{meetingId:state.meetingId},timestamp:Date.now(),runId:'pre-fix',hypothesisId:'STOP500'})}).catch(()=>{});
  // #endregion
  // #region agent log
  try {
    localStorage.setItem("lastStoppedMeetingId", state.meetingId);
  } catch (_) {}
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app/static/meeting.js:stopTranscription',message:'lastStoppedMeetingId set',data:{meetingId:state.meetingId},timestamp:Date.now(),runId:'pre-fix',hypothesisId:'H5'})}).catch(()=>{});
  // #endregion
  
  // Disable the stop button immediately to prevent multiple clicks
  const stopBtn = document.getElementById("stop-transcription");
  if (stopBtn) {
    stopBtn.disabled = true;
    stopBtn.textContent = "Stopping...";
  }
  
  setGlobalBusy("Stopping audio capture...");
  setTranscriptStatus("Stopped capturing audio. Finishing transcription of captured audio...");
  
  try {
    const result = await fetchJson(`/api/transcribe/stop/${state.meetingId}`, { method: "POST" });
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app/static/meeting.js:stopTranscription',message:'stop ok',data:{meetingId:state.meetingId,result},timestamp:Date.now(),runId:'pre-fix',hypothesisId:'STOP500'})}).catch(()=>{});
    // #endregion
    debugLog("Transcription stop requested", { meetingId: state.meetingId, result });
    
    // The stop request returns immediately. Audio capture has stopped.
    // Transcription of already-captured audio continues in background.
    setGlobalBusy("Audio capture stopped. Finishing transcription...");
    setTranscriptStatus("Audio capture stopped. Processing remaining audio...");
    
    // Poll for completion since transcription continues in background
    let attempts = 0;
    const maxAttempts = 120; // 2 minutes max wait (for the final 30s chunk)
    
    while (attempts < maxAttempts) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      attempts++;
      
      const active = await getActiveTranscription();
      if (!active.active || active.meeting_id !== state.meetingId) {
        debugLog("Transcription fully stopped", { attempts });
        break;
      }
      
      // Show progress message
      if (attempts <= 5) {
        setGlobalBusy("Processing remaining captured audio...");
      } else if (attempts <= 30) {
        setGlobalBusy(`Finishing transcription... (${attempts}s)`);
      } else {
        setGlobalBusy(`Still processing... (${attempts}s, Whisper uses 30s chunks)`);
      }
    }
    
    setTranscriptStatus("Transcription complete.");
    await refreshMeeting();
  } catch (error) {
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'app/static/meeting.js:stopTranscription',message:'stop error',data:{meetingId:state.meetingId,errorMessage:error?.message||String(error)},timestamp:Date.now(),runId:'pre-fix',hypothesisId:'STOP500'})}).catch(()=>{});
    // #endregion
    setGlobalError(`Failed to stop transcription: ${error.message}`);
    debugError("Stop transcription failed", error);
  } finally {
    setGlobalBusy("");
    if (stopBtn) {
      stopBtn.disabled = false;
      stopBtn.textContent = "Stop transcription";
    }
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

  // Attendee rename controls are now inline - event handlers added in renderAttendeesList()

  document
    .getElementById("delete-meeting")
    .addEventListener("click", deleteMeeting);
  document
    .getElementById("export-meeting")
    .addEventListener("click", exportMeeting);
  
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
        updateSummaryDebugPanel(state.meeting || null);
      }
    });

  const manualSummarizeBtn = document.getElementById("manual-summarize");
  if (manualSummarizeBtn) {
    manualSummarizeBtn.addEventListener("click", manualSummarize);
  }

  const manualNotesEl = document.getElementById("manual-notes");
  if (manualNotesEl) {
    manualNotesEl.addEventListener("input", scheduleManualBuffersSave);
  }
  const manualSummaryEl = document.getElementById("manual-summary");
  if (manualSummaryEl) {
    manualSummaryEl.addEventListener("input", scheduleManualBuffersSave);
  }
  
  // Raw segments toggle in debug panel - only affects the debug panel's transcript
  const showRawToggle = document.getElementById("show-raw-segments");
  if (showRawToggle) {
    showRawToggle.addEventListener("change", async (e) => {
      state.showRawSegments = e.target.checked;
      // Only update the debug panel, not the whole page
      await updateSummaryDebugPanel(state.meeting);
    });
  }
  
  window.addEventListener("beforeunload", () => {
    stopLiveTranscript();
    unsubscribeFromMeetingEvents();
  });

  // Subscribe to SSE for real-time events (streaming summary, etc.)
  subscribeToMeetingEvents();

  await refreshVersion();
  await refreshMeeting();
  // Polling is now started/stopped automatically by refreshMeeting based on meeting state
});
