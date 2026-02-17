// #region agent log - parse test (fires synchronously during script load, before DOMContentLoaded)
fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:TOP_OF_FILE',message:'meeting.js script body executing (no parse error)',data:{},timestamp:Date.now(),runId:'parse-test',hypothesisId:'PARSE'})}).catch(function(){});
// #endregion
const state = {
  meetingId: null,
  meeting: null,
  lastTranscriptSegments: null,
  titleSaveTimer: null,
  selectedAttendeeId: null,
  renameMode: false,
  pollIntervalId: null,
  showRawSegments: false,
  eventsSource: null,  // SSE connection for meeting events (handles both mic and file transcription)
  meetingChat: null,   // ChatUI instance for meeting-specific chat
  // User notes state
  userNotes: [],           // Array of submitted notes
  userNotesDraft: null,    // Current draft {text, timestamp}
  noteTimestamp: null,     // When current note typing started (seconds from recording start)
  noteDraftSaveTimer: null, // Debounce timer for draft auto-save
  transcriptStartTime: null, // Client-side timestamp when we first saw this as an active meeting
  // Panel search state
  panelSearch: {},         // Per-panel search state: { panelId: { matches: [], index: -1 } }
};

// =============================================================================
// Panel Search Utility
// =============================================================================

/**
 * Initialize search for a panel by wiring up event listeners.
 * @param {string} panelId - ID prefix for the panel (e.g., 'transcript', 'summary', 'notes')
 * @param {string} contentSelector - CSS selector for the content element to search within
 */
function initPanelSearch(panelId, contentSelector) {
  const searchBar = document.getElementById(`${panelId}-search-bar`);
  const searchToggle = document.getElementById(`${panelId}-search-toggle`);
  const contentEl = document.querySelector(contentSelector);
  
  if (!searchBar || !searchToggle || !contentEl) {
    console.warn(`Panel search init failed for ${panelId}: missing elements`);
    return;
  }
  
  const input = searchBar.querySelector('.chat-search-input');
  const countEl = searchBar.querySelector('.chat-search-count');
  const prevBtn = searchBar.querySelector('.chat-search-prev');
  const nextBtn = searchBar.querySelector('.chat-search-next');
  
  if (!input || !countEl || !prevBtn || !nextBtn) {
    console.warn(`Panel search init failed for ${panelId}: missing search bar elements`);
    return;
  }
  
  // Initialize state for this panel
  state.panelSearch[panelId] = { matches: [], index: -1 };
  
  // Toggle button
  searchToggle.addEventListener('click', () => {
    if (searchBar.style.display !== 'none') {
      closePanelSearch(panelId);
    } else {
      openPanelSearch(panelId);
    }
  });
  
  // Input events
  input.addEventListener('input', () => {
    performPanelSearch(panelId, input.value, contentEl);
  });
  
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      navigatePanelSearch(panelId, e.shiftKey ? -1 : 1);
    } else if (e.key === 'Escape') {
      closePanelSearch(panelId);
    }
  });
  
  // Nav buttons
  prevBtn.addEventListener('click', () => navigatePanelSearch(panelId, -1));
  nextBtn.addEventListener('click', () => navigatePanelSearch(panelId, 1));
}

/**
 * Open the search bar for a panel and focus the input.
 * @param {string} panelId
 */
function openPanelSearch(panelId) {
  const searchBar = document.getElementById(`${panelId}-search-bar`);
  const input = searchBar?.querySelector('.chat-search-input');
  if (!searchBar || !input) return;
  
  searchBar.style.display = 'flex';
  input.focus();
  
  // Re-run search if there's existing text
  if (input.value) {
    const contentSelector = getPanelContentSelector(panelId);
    const contentEl = document.querySelector(contentSelector);
    if (contentEl) {
      performPanelSearch(panelId, input.value, contentEl);
    }
  }
}

/**
 * Close the search bar for a panel and clear highlights.
 * @param {string} panelId
 */
function closePanelSearch(panelId) {
  const searchBar = document.getElementById(`${panelId}-search-bar`);
  const input = searchBar?.querySelector('.chat-search-input');
  const countEl = searchBar?.querySelector('.chat-search-count');
  
  if (!searchBar) return;
  
  searchBar.style.display = 'none';
  if (input) input.value = '';
  if (countEl) countEl.textContent = '0/0';
  
  // Clear highlights
  const contentSelector = getPanelContentSelector(panelId);
  const contentEl = document.querySelector(contentSelector);
  if (contentEl) {
    clearPanelSearchHighlights(contentEl);
  }
  
  // Reset state
  if (state.panelSearch[panelId]) {
    state.panelSearch[panelId].matches = [];
    state.panelSearch[panelId].index = -1;
  }
}

/**
 * Get the content selector for a panel.
 * @param {string} panelId
 * @returns {string}
 */
function getPanelContentSelector(panelId) {
  switch (panelId) {
    case 'transcript': return '#transcript-output';
    case 'summary': return '#summary-output';
    case 'notes': return '#notes-log';
    default: return null;
  }
}

/**
 * Perform a case-insensitive search and highlight matches.
 * @param {string} panelId
 * @param {string} query
 * @param {HTMLElement} contentEl
 */
function performPanelSearch(panelId, query, contentEl) {
  const searchBar = document.getElementById(`${panelId}-search-bar`);
  const countEl = searchBar?.querySelector('.chat-search-count');
  
  // Clear previous highlights
  clearPanelSearchHighlights(contentEl);
  
  // Reset state
  const searchState = state.panelSearch[panelId] || { matches: [], index: -1 };
  searchState.matches = [];
  searchState.index = -1;
  state.panelSearch[panelId] = searchState;
  
  if (!query) {
    if (countEl) countEl.textContent = '0/0';
    return;
  }
  
  const lowerQuery = query.toLowerCase();
  
  // Walk text nodes and highlight matches
  const walker = document.createTreeWalker(contentEl, NodeFilter.SHOW_TEXT, null, false);
  const nodesToProcess = [];
  
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const text = node.textContent;
    if (text.toLowerCase().includes(lowerQuery)) {
      nodesToProcess.push(node);
    }
  }
  
  for (const node of nodesToProcess) {
    const text = node.textContent;
    const parent = node.parentNode;
    const frag = document.createDocumentFragment();
    let lastEnd = 0;
    let idx = 0;
    const lowerText = text.toLowerCase();
    
    while ((idx = lowerText.indexOf(lowerQuery, lastEnd)) !== -1) {
      // Text before match
      if (idx > lastEnd) {
        frag.appendChild(document.createTextNode(text.slice(lastEnd, idx)));
      }
      // Highlighted match
      const mark = document.createElement('mark');
      mark.textContent = text.slice(idx, idx + query.length);
      frag.appendChild(mark);
      searchState.matches.push(mark);
      lastEnd = idx + query.length;
    }
    
    // Remaining text
    if (lastEnd < text.length) {
      frag.appendChild(document.createTextNode(text.slice(lastEnd)));
    }
    
    parent.replaceChild(frag, node);
  }
  
  // Highlight first match
  if (searchState.matches.length > 0) {
    searchState.index = 0;
    highlightCurrentPanelMatch(panelId);
  }
  
  updatePanelSearchCount(panelId);
}

/**
 * Navigate to the next or previous match.
 * @param {string} panelId
 * @param {number} direction - +1 for next, -1 for previous
 */
function navigatePanelSearch(panelId, direction) {
  const searchState = state.panelSearch[panelId];
  if (!searchState || searchState.matches.length === 0) return;
  
  // Remove current highlight
  const prev = searchState.matches[searchState.index];
  if (prev) prev.classList.remove('current');
  
  // Calculate new index
  searchState.index = (searchState.index + direction + searchState.matches.length) % searchState.matches.length;
  
  highlightCurrentPanelMatch(panelId);
  updatePanelSearchCount(panelId);
}

/**
 * Highlight the current match and scroll into view.
 * @param {string} panelId
 */
function highlightCurrentPanelMatch(panelId) {
  const searchState = state.panelSearch[panelId];
  if (!searchState) return;
  
  const el = searchState.matches[searchState.index];
  if (!el) return;
  
  el.classList.add('current');
  el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

/**
 * Update the search count display.
 * @param {string} panelId
 */
function updatePanelSearchCount(panelId) {
  const searchBar = document.getElementById(`${panelId}-search-bar`);
  const countEl = searchBar?.querySelector('.chat-search-count');
  const searchState = state.panelSearch[panelId];
  
  if (!countEl || !searchState) return;
  
  const total = searchState.matches.length;
  const current = total > 0 ? searchState.index + 1 : 0;
  countEl.textContent = `${current}/${total}`;
}

/**
 * Clear all search highlights from a content element.
 * @param {HTMLElement} contentEl
 */
function clearPanelSearchHighlights(contentEl) {
  const marks = contentEl.querySelectorAll('mark');
  marks.forEach((mark) => {
    const parent = mark.parentNode;
    parent.replaceChild(document.createTextNode(mark.textContent), mark);
    parent.normalize();
  });
}

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

/**
 * Attach debug right-click "Submit and Log" to a ChatUI send button.
 * Notetaker-specific debug tooling, not part of the reusable component.
 */
function _attachMeetingDebugContextMenu(chatInstance) {
  if (!chatInstance || !chatInstance.sendBtn) return;

  chatInstance.sendBtn.addEventListener('contextmenu', (e) => {
    e.preventDefault();
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
    option.addEventListener('click', async () => {
      menu.remove();
      chatInstance.onSendMessage = (payload) => {
        payload.test_log_this = true;
        chatInstance.onSendMessage = null;
      };
      await chatInstance.sendMessage();
      _fetchLatestSubmitLog();
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
 * Fetch the most recent submit-and-log file and populate the debug panel.
 */
async function _fetchLatestSubmitLog() {
  try {
    const res = await fetch('/api/test/latest-submit-log');
    if (!res.ok) return;
    const data = await res.json();

    const pathEl = document.getElementById('debug-prompt-path');
    if (pathEl) {
      pathEl.innerHTML = '';
      const link = document.createElement('a');
      link.href = 'file://' + data.path;
      link.textContent = data.path;
      link.title = 'Open log file';
      pathEl.appendChild(link);

      const copyBtn = document.createElement('button');
      copyBtn.className = 'icon-btn debug-copy-path-btn';
      copyBtn.title = 'Copy path to clipboard';
      copyBtn.innerHTML = '&#128203;';
      copyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(data.path).then(() => {
          copyBtn.innerHTML = '&#10003;';
          setTimeout(() => { copyBtn.innerHTML = '&#128203;'; }, 1500);
        });
      });
      pathEl.appendChild(copyBtn);
      pathEl.classList.add('has-path');
    }

    const logEl = document.getElementById('debug-prompt-log');
    if (logEl) logEl.value = data.content || '';

    // Open the debug panel if it is closed so the user sees the result
    const sidebar = document.getElementById('debug-sidebar');
    if (sidebar && sidebar.style.display === 'none') {
      sidebar.style.display = '';
    }
  } catch (e) {
    console.warn('Failed to fetch latest submit log', e);
  }
}

/**
 * Wire up maximize buttons on each debug-section.
 * Clicking toggles the section to a full-page overlay and back.
 */
function initDebugMaximize() {
  document.querySelectorAll('.debug-maximize-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const section = btn.closest('.debug-section');
      if (!section) return;

      const isMaximized = section.classList.contains('debug-maximized');
      if (isMaximized) {
        section.classList.remove('debug-maximized');
        btn.title = 'Maximize';
      } else {
        // Restore any other maximized debug section first
        document.querySelectorAll('.debug-section.debug-maximized').forEach((s) => {
          s.classList.remove('debug-maximized');
          const b = s.querySelector('.debug-maximize-btn');
          if (b) b.title = 'Maximize';
        });
        section.classList.add('debug-maximized');
        btn.title = 'Restore';
      }
    });
  });
}

/**
 * Initialize the meeting chat UI component.
 */
function initMeetingChat() {
  const container = document.getElementById("meeting-chat-container");
  if (!container || typeof ChatUI === "undefined") {
    console.warn("Chat container or ChatUI not available");
    return;
  }
  
  // Don't initialize until we have a meeting ID
  if (!state.meetingId) {
    console.debug("Waiting for meeting ID before initializing chat");
    return;
  }
  
  try {
    // Get external search elements from the grid-panel-header
    const searchContainer = document.getElementById("meeting-chat-search-bar")?.parentElement || null;
    const searchToggle = document.getElementById("meeting-chat-search-toggle") || null;
    
    state.meetingChat = new ChatUI({
      container: container,
      endpoint: `/api/chat/meeting/${state.meetingId}`,
      historyEndpoint: `/api/chat/meeting/${state.meetingId}/history`,
      buildPayload: (question) => ({
        question: question,
        include_related: false,
      }),
      placeholder: "Ask a question about this meeting...",
      emptyText: "Ask a question about this meeting.",
      minimal: true,
      searchContainer: searchContainer,
      searchToggle: searchToggle,
    });

    // Debug: right-click send button → "Submit and Log"
    _attachMeetingDebugContextMenu(state.meetingChat);
  } catch (err) {
    console.error("ChatUI initialization failed:", err);
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:initMeetingChat:ERROR',message:'ChatUI constructor threw',data:{error:err.message,stack:err.stack?.substring(0,300)},timestamp:Date.now(),runId:'post-fix',hypothesisId:'CHAT'})}).catch(()=>{});
    // #endregion
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
      fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:SSE:attendees_updated',message:'attendees_updated event received',data:{hasAttendees:!!(event.data?.attendees),count:event.data?.attendees?.length||0,ids:(event.data?.attendees||[]).map(a=>a.id),names:(event.data?.attendees||[]).map(a=>a.name)},timestamp:Date.now(),runId:'rt-attendee-debug',hypothesisId:'H_SSE'})}).catch(()=>{});
      // #endregion
      if (event.data?.attendees) {
        if (state.meeting) {
          state.meeting.attendees = event.data.attendees;
        }
        setAttendeeEditor(event.data.attendees);
      }
      break;
    
    case "transcript_segment":
      // Single new transcript segment added (unified for both mic and file modes)
      if (event.data?.segment && state.meeting) {
        if (!state.meeting.transcript) {
          state.meeting.transcript = { segments: [] };
        }
        state.meeting.transcript.segments.push(event.data.segment);
        state.lastTranscriptSegments = state.meeting.transcript.segments;
        // Always update display - unified SSE for both mic and file modes
        setTranscriptOutput(state.meeting.transcript.segments);
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
        // Always update display
        setTranscriptOutput(event.data.segments);
        const meetingStatus = state.meeting.status === "in_progress" ? "In progress" : "Completed";
        setTranscriptStatus(`${meetingStatus} • Transcript (${event.data.segments.length} segments)`);
      }
      break;
    
    case "finalization_status":
      // Finalization progress update — persist on state so controls badge can read it
      if (state.meeting) {
        state.meeting.finalization_status = {
          status_text: event.status_text,
          progress: event.progress,
        };
      }
      showFinalizationStatus(event.status_text, event.progress);
      // Also update the transcription controls badge to show current step
      updateTranscriptionControls();
      break;
    
    case "transcription_error":
      // Transcription error - unified for both mic and file modes
      debugError("Transcription error event", event.data);
      if (event.data?.message) {
        setTranscriptStatus(`Error: ${event.data.message}`);
        // Show a non-blocking error notification
        setGlobalError(`Transcription error: ${event.data.message}`);
      }
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
      selectAttendee(item.dataset.attendeeId, item);
    });
  });
  
  // #region agent log
  listEl.querySelectorAll(".attendee-item").forEach((item) => {
    item.addEventListener("mouseenter", () => {
      const actions = item.querySelector(".attendee-item-actions");
      const actionsStyle = actions ? window.getComputedStyle(actions) : null;
      const itemRect = item.getBoundingClientRect();
      fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:hover',message:'mouseenter attendee-item',data:{attendeeId:item.dataset.attendeeId,itemW:itemRect.width,itemH:itemRect.height,actionsDisplay:actionsStyle?actionsStyle.display:'N/A',actionsOpacity:actionsStyle?actionsStyle.opacity:'N/A',actionsW:actions?actions.getBoundingClientRect().width:0,actionsH:actions?actions.getBoundingClientRect().height:0,actionsVisible:actionsStyle?actionsStyle.visibility:'N/A'},timestamp:Date.now(),runId:'hover-debug',hypothesisId:'H1-H2'})}).catch(()=>{});
    });
    item.addEventListener("mouseleave", () => {
      const actions = item.querySelector(".attendee-item-actions");
      const actionsStyle = actions ? window.getComputedStyle(actions) : null;
      const itemRect = item.getBoundingClientRect();
      fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:hover',message:'mouseleave attendee-item',data:{attendeeId:item.dataset.attendeeId,itemW:itemRect.width,itemH:itemRect.height,actionsDisplay:actionsStyle?actionsStyle.display:'N/A',actionsOpacity:actionsStyle?actionsStyle.opacity:'N/A',actionsW:actions?actions.getBoundingClientRect().width:0,actionsH:actions?actions.getBoundingClientRect().height:0},timestamp:Date.now(),runId:'hover-debug',hypothesisId:'H1-H2'})}).catch(()=>{});
    });
  });
  // #endregion

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

function selectAttendee(attendeeId, clickedElement) {
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
    closeAttendeeDetailPopup();
    return;
  }

  // Clear status
  setAutoRenameStatus("");

  // Show the popup with attendee details, positioned near the clicked element
  const element = clickedElement || document.querySelector(`.attendee-item[data-attendee-id="${attendeeId}"]`);
  showAttendeeDetailPopup(attendee, element);
}

function showAttendeeDetailPopup(attendee, clickedElement) {
  const popup = document.getElementById("attendee-detail-popup");
  const nameEl = document.getElementById("attendee-detail-name");
  const segmentsEl = document.getElementById("attendee-segments");
  
  if (!popup) return;
  
  // Set attendee name
  const name = attendee.name || attendee.label || attendee.id || "Unknown";
  if (nameEl) {
    nameEl.textContent = name;
  }
  
  // Render segments
  const segments = getSegmentsForAttendee(attendee.id);
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
    }
  }
  
  // Position popup next to the clicked attendee item
  if (clickedElement) {
    const rect = clickedElement.getBoundingClientRect();
    const sidebar = document.querySelector(".meeting-sidebar");
    const sidebarRect = sidebar ? sidebar.getBoundingClientRect() : { right: 200 };
    
    // Position to the right of the sidebar
    popup.style.left = `${sidebarRect.right + 8}px`;
    popup.style.top = `${Math.max(rect.top - 20, 60)}px`;
    popup.style.transform = "none";
  }
  
  popup.style.display = "flex";
  
  // Add click-outside listener to dismiss
  setTimeout(() => {
    document.addEventListener("click", handleClickOutsidePopup);
  }, 0);
}

function handleClickOutsidePopup(e) {
  const popup = document.getElementById("attendee-detail-popup");
  const sidebar = document.querySelector(".meeting-sidebar");
  
  // If click is outside popup and not on an attendee item, close it
  if (popup && !popup.contains(e.target) && (!sidebar || !sidebar.contains(e.target))) {
    closeAttendeeDetailPopup();
  }
}

function closeAttendeeDetailPopup() {
  const popup = document.getElementById("attendee-detail-popup");
  if (popup) {
    popup.style.display = "none";
  }
  document.removeEventListener("click", handleClickOutsidePopup);
  state.selectedAttendeeId = null;
  document.querySelectorAll(".attendee-item").forEach((item) => {
    item.classList.remove("selected");
  });
}

/**
 * Initialize panel maximize/restore functionality.
 */
function initPanelMaximize() {
  const grid = document.getElementById("meeting-grid");
  if (!grid) return;
  
  const maximizeBtns = grid.querySelectorAll(".panel-maximize-btn");
  maximizeBtns.forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const panel = btn.closest(".grid-panel");
      if (!panel) return;
      
      const isMaximized = panel.classList.contains("maximized");
      
      if (isMaximized) {
        // Restore
        panel.classList.remove("maximized");
        grid.classList.remove("has-maximized");
        btn.title = "Maximize";
      } else {
        // Maximize - first restore any other maximized panel
        grid.querySelectorAll(".grid-panel.maximized").forEach((p) => {
          p.classList.remove("maximized");
          const otherBtn = p.querySelector(".panel-maximize-btn");
          if (otherBtn) otherBtn.title = "Maximize";
        });
        
        panel.classList.add("maximized");
        grid.classList.add("has-maximized");
        btn.title = "Restore";
      }
    });
  });
}

function clearAttendeeDetail() {
  closeAttendeeDetailPopup();
  hideRenameMode();
  setAutoRenameStatus("");
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
      const speakerId = segment.speaker_id || segment.speaker || "unknown";
      const speakerName = attendeeMap.get(speakerId)?.name || speakerId;
      return `[${start}-${end}] [${speakerName}] ${segment.text}`;
    })
    .join("\n");
}

function setTranscriptOutput(segments) {
  const output = document.getElementById("transcript-output");
  if (!output) {
    return;
  }
  if (!segments || !segments.length) {
    output.textContent = "No transcript yet.";
    return;
  }
  const text = buildTranscriptText(segments);
  output.textContent = text;
}

function setTranscriptStatus(message) {
  const status = document.getElementById("transcript-status");
  if (status) {
    status.textContent = message;
  }
}

function setSummaryStatus(message) {
  const status = document.getElementById("summary-status");
  if (status) {
    status.textContent = message;
  }
}

function setSummaryOutput(message) {
  const output = document.getElementById("summary-output");
  if (!output) {
    return;
  }
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
    while (true) {
      const { done, value } = await reader.read();      if (done) break;

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
            accumulatedText += data.token;            // Update both textareas progressively
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
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:refreshMeeting:enter',message:'refreshMeeting called',data:{meetingId:state.meetingId},timestamp:Date.now(),runId:'post-fix',hypothesisId:'REFRESH'})}).catch(()=>{});
  // #endregion
  if (!state.meetingId) {
    return;
  }
  setGlobalBusy("Loading meeting...");
  try {
    const meeting = await fetchJson(`/api/meetings/${state.meetingId}`);
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:refreshMeeting:loaded',message:'meeting data loaded',data:{meetingId:state.meetingId,status:meeting.status,hasTranscript:!!(meeting.transcript?.segments?.length),segmentCount:meeting.transcript?.segments?.length||0,hasSummary:!!meeting.summary?.text,title:meeting.title},timestamp:Date.now(),runId:'post-fix',hypothesisId:'REFRESH'})}).catch(()=>{});
    // #endregion
    state.meeting = meeting;
    
    // Set transcriptStartTime for active meetings (only on first load, not every refresh)
    const isActiveMeeting = meeting.status === "in_progress" || meeting.status === "processing";
    if (isActiveMeeting && !state.transcriptStartTime) {
      state.transcriptStartTime = Date.now();
    }
    
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
    } else {
      setSummaryStatus(`${meetingStatus} • No summary yet.`);
      setSummaryOutput("No summary yet.");
    }
    
    // Load manual notes
    const notesEl = document.getElementById("manual-notes");
    if (notesEl && notesEl.value !== (meeting?.manual_notes || "")) {
      notesEl.value = meeting?.manual_notes || "";
    }
    
    // Update debug panel if visible
    updateSummaryDebugPanel(meeting);
  } catch (error) {
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:refreshMeeting:ERROR',message:'refreshMeeting failed',data:{error:error.message,stack:error.stack?.substring(0,300)},timestamp:Date.now(),runId:'post-fix',hypothesisId:'REFRESH'})}).catch(()=>{});
    // #endregion
    setGlobalError(`Failed to load meeting: ${error.message}`);
  } finally {
    setGlobalBusy("");
  }

  // Start backend transcription (separate try/catch so meeting load errors don't block this)
  try {
    const response = await fetch("/api/transcribe/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        meeting_id: state.meetingId,
      }),
    });
    
    const result = await response.json();    
    // Handle various status responses gracefully
    if (result.status === "already_running") {
      debugLog("Backend transcription already running");
    } else if (result.status === "not_applicable") {
      // File transcription or no active recording - this is fine
      debugLog("Backend transcription not applicable", result.reason);
    } else if (!response.ok) {
      throw new Error(result.detail || `Failed to start transcription: ${response.status}`);
    } else {
      debugLog("Backend transcription started", result);
      setTranscriptStatus("In progress • Live transcript");
    }
    
    // Transcript segments will arrive via meeting events SSE
    // No need to maintain a separate SSE connection
    
  } catch (error) {
    debugError("Failed to start backend transcription", error);
    // Don't show error to user - meeting events will still work
    // and transcription may already be running
  }

  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:refreshMeeting:end',message:'refreshMeeting completed, calling updateTranscriptionControls',data:{meetingId:state.meetingId,meetingStatus:state.meeting?.status,hasAudioPath:!!state.meeting?.audio_path},timestamp:Date.now(),runId:'meeting-controls-fix',hypothesisId:'H1-H2'})}).catch(()=>{});
  // #endregion

  // Update transcription controls on initial load (not just on SSE events)
  await updateTranscriptionControls();
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
  // Check for either the new debug-sidebar or legacy summary-debug-panel
  const panel = document.getElementById("debug-sidebar") || document.getElementById("summary-debug-panel");
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

// ---- User Notes Functions ----

/**
 * Get current elapsed time in seconds from transcription start.
 * Uses client-side transcriptStartTime (captured when meeting page loads for active meeting).
 * For completed meetings, returns null (post-meeting note).
 */
function getCurrentRecordingTime() {
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:getCurrentRecordingTime',message:'getCurrentRecordingTime called',data:{hasMeeting:!!state.meeting,meetingStatus:state.meeting?.status,transcriptStartTime:state.transcriptStartTime},timestamp:Date.now(),runId:'ts-fix',hypothesisId:'H_TIME'})}).catch(()=>{});
  // #endregion
  if (!state.meeting) return null;
  
  // If meeting is completed, notes are post-meeting
  if (state.meeting.status === "completed") {
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:getCurrentRecordingTime:completed',message:'Meeting completed - returning null',data:{status:state.meeting.status},timestamp:Date.now(),runId:'ts-fix',hypothesisId:'H_COMPLETED'})}).catch(()=>{});
    // #endregion
    return null;
  }
  
  // Use client-side start time (no timezone issues)
  if (!state.transcriptStartTime) {
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:getCurrentRecordingTime:noStartTime',message:'No transcriptStartTime - returning null',data:{},timestamp:Date.now(),runId:'ts-fix',hypothesisId:'H_NOSTART'})}).catch(()=>{});
    // #endregion
    return null;
  }
  
  const now = Date.now();
  const elapsedSeconds = (now - state.transcriptStartTime) / 1000;
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:getCurrentRecordingTime:calculated',message:'Calculated elapsed time',data:{transcriptStartTime:state.transcriptStartTime,now,elapsedSeconds},timestamp:Date.now(),runId:'ts-fix',hypothesisId:'H_CALC'})}).catch(()=>{});
  // #endregion
  return elapsedSeconds;
}

/**
 * Format timestamp for display (e.g., "1:23" or "12:34")
 */
function formatNoteTimestamp(seconds) {
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:formatNoteTimestamp',message:'Formatting timestamp',data:{seconds,isNull:seconds===null,isUndefined:seconds===undefined,type:typeof seconds},timestamp:Date.now(),runId:'ts-debug',hypothesisId:'H_FORMAT'})}).catch(()=>{});
  // #endregion
  if (seconds === null || seconds === undefined) {
    return "Added after meeting";
  }
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

/**
 * Update the timestamp badge display above the notes input.
 */
function updateNotesTimestampDisplay() {
  const badge = document.getElementById("notes-timestamp-badge");
  const text = document.getElementById("notes-timestamp-text");
  if (!badge || !text) return;
  
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:updateNotesTimestampDisplay',message:'Updating timestamp display',data:{noteTimestamp:state.noteTimestamp,isNull:state.noteTimestamp===null},timestamp:Date.now(),runId:'ts-debug',hypothesisId:'H_DISPLAY'})}).catch(()=>{});
  // #endregion
  
  if (state.noteTimestamp !== null) {
    text.textContent = `Note at ${formatNoteTimestamp(state.noteTimestamp)}`;
    badge.style.display = "block";
  } else {
    badge.style.display = "none";
  }
}

/**
 * Update submit button and clear button state based on input content.
 */
function updateNotesSubmitButton() {
  const input = document.getElementById("notes-input");
  const submitBtn = document.getElementById("notes-submit-btn");
  const clearBtn = document.getElementById("notes-clear-btn");
  if (!input || !submitBtn) return;
  
  const hasContent = !!input.value.trim();
  submitBtn.disabled = !hasContent;
  
  if (clearBtn) {
    clearBtn.style.display = hasContent ? "flex" : "none";
  }
}

/**
 * Called when user starts typing in the notes input.
 * Captures timestamp on first keypress.
 */
function handleNotesInput(e) {
  const input = e.target;
  
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:handleNotesInput:entry',message:'handleNotesInput called',data:{inputLength:input.value.length,currentNoteTimestamp:state.noteTimestamp,willCaptureTimestamp:state.noteTimestamp===null&&input.value.length>0},timestamp:Date.now(),runId:'ts-debug',hypothesisId:'H_INPUT'})}).catch(()=>{});
  // #endregion
  
  // Capture timestamp on first input if we don't have one
  if (state.noteTimestamp === null && input.value.length > 0) {
    const recordingTime = getCurrentRecordingTime();
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:handleNotesInput:captureTimestamp',message:'Capturing timestamp',data:{recordingTimeReturned:recordingTime,isNull:recordingTime===null},timestamp:Date.now(),runId:'ts-debug',hypothesisId:'H_INPUT'})}).catch(()=>{});
    // #endregion
    state.noteTimestamp = recordingTime;
    updateNotesTimestampDisplay();
  }
  
  updateNotesSubmitButton();
  scheduleNoteDraftSave();
}

/**
 * Schedule a debounced draft save (every 2 seconds while typing).
 */
function scheduleNoteDraftSave() {
  if (state.noteDraftSaveTimer) {
    clearTimeout(state.noteDraftSaveTimer);
  }
  state.noteDraftSaveTimer = setTimeout(() => {
    saveNoteDraft();
  }, 2000);
}

/**
 * Save the current draft to the server.
 */
async function saveNoteDraft() {
  if (!state.meetingId) return;
  
  const input = document.getElementById("notes-input");
  const text = input?.value || "";
  
  try {
    await fetchJson(`/api/meetings/${state.meetingId}/notes/draft`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: text,
        timestamp: state.noteTimestamp,
      }),
    });
  } catch (error) {
    console.warn("Failed to save note draft:", error);
  }
}

/**
 * Submit the current note.
 */
async function submitNote() {
  if (!state.meetingId) return;
  
  const input = document.getElementById("notes-input");
  const text = input?.value?.trim();
  if (!text) return;
  
  const timestamp = state.noteTimestamp;
  const isPostMeeting = state.meeting?.status === "completed";
  
  try {
    const note = await fetchJson(`/api/meetings/${state.meetingId}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: text,
        timestamp: timestamp,
        is_post_meeting: isPostMeeting,
      }),
    });
    
    // Add to local state and render
    state.userNotes.push(note);
    renderNoteCard(note);
    updateNotesEmptyState();
    
    // Clear input and timestamp for next note
    clearNoteInput();
    
  } catch (error) {
    setGlobalError(`Failed to save note: ${error.message}`);
  }
}

/**
 * Clear the notes input and timestamp (user clicked Clear button).
 */
function clearNoteInput() {
  const input = document.getElementById("notes-input");
  if (input) {
    input.value = "";
  }
  state.noteTimestamp = null;
  updateNotesTimestampDisplay();
  updateNotesSubmitButton();
  
  // Clear draft on server
  if (state.noteDraftSaveTimer) {
    clearTimeout(state.noteDraftSaveTimer);
  }
  saveNoteDraft();
}

/**
 * Render a single note card in the notes log.
 */
function renderNoteCard(note) {
  const log = document.getElementById("notes-log");
  if (!log) return;
  
  const card = document.createElement("div");
  card.className = "note-card";
  if (note.is_post_meeting) {
    card.classList.add("post-meeting");
  }
  card.dataset.noteId = note.id;
  
  const header = document.createElement("div");
  header.className = "note-card-header";
  
  const timestamp = document.createElement("span");
  timestamp.className = "note-timestamp";
  timestamp.textContent = note.is_post_meeting 
    ? "Added after meeting" 
    : formatNoteTimestamp(note.timestamp);
  
  const actions = document.createElement("div");
  actions.className = "note-actions";
  
  const editBtn = document.createElement("button");
  editBtn.className = "icon-btn small";
  editBtn.innerHTML = "&#9998;"; // Pencil icon
  editBtn.title = "Edit";
  editBtn.addEventListener("click", () => startNoteEdit(note.id));
  
  const deleteBtn = document.createElement("button");
  deleteBtn.className = "icon-btn small";
  deleteBtn.innerHTML = "&#x2715;"; // X icon
  deleteBtn.title = "Delete";
  deleteBtn.addEventListener("click", () => deleteNote(note.id));
  
  actions.appendChild(editBtn);
  actions.appendChild(deleteBtn);
  
  header.appendChild(timestamp);
  header.appendChild(actions);
  
  const textEl = document.createElement("div");
  textEl.className = "note-text";
  textEl.textContent = note.text;
  
  card.appendChild(header);
  card.appendChild(textEl);
  
  log.appendChild(card);
  
  // Scroll to bottom to show new note
  log.scrollTop = log.scrollHeight;
}

/**
 * Start inline editing of a note.
 */
function startNoteEdit(noteId) {
  const card = document.querySelector(`.note-card[data-note-id="${noteId}"]`);
  if (!card) return;
  
  const textEl = card.querySelector(".note-text");
  if (!textEl) return;
  
  const currentText = textEl.textContent;
  
  // Replace text with textarea
  const textarea = document.createElement("textarea");
  textarea.className = "note-edit-textarea";
  textarea.value = currentText;
  textarea.rows = 2;
  
  // Save on blur or Enter (without shift)
  textarea.addEventListener("blur", () => saveNoteEdit(noteId, textarea.value));
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      textarea.blur();
    } else if (e.key === "Escape") {
      textarea.value = currentText; // Revert
      textarea.blur();
    }
  });
  
  textEl.replaceWith(textarea);
  textarea.focus();
  textarea.select();
}

/**
 * Save an edited note.
 */
async function saveNoteEdit(noteId, newText) {
  const card = document.querySelector(`.note-card[data-note-id="${noteId}"]`);
  if (!card) return;
  
  const textarea = card.querySelector(".note-edit-textarea");
  const text = newText.trim();
  
  if (!text) {
    // Empty text - revert to original
    const note = state.userNotes.find(n => n.id === noteId);
    if (note) {
      const textEl = document.createElement("div");
      textEl.className = "note-text";
      textEl.textContent = note.text;
      textarea?.replaceWith(textEl);
    }
    return;
  }
  
  try {
    const updatedNote = await fetchJson(
      `/api/meetings/${state.meetingId}/notes/${noteId}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text }),
      }
    );
    
    // Update local state
    const noteIndex = state.userNotes.findIndex(n => n.id === noteId);
    if (noteIndex >= 0) {
      state.userNotes[noteIndex] = updatedNote;
    }
    
    // Replace textarea with text element
    const textEl = document.createElement("div");
    textEl.className = "note-text";
    textEl.textContent = updatedNote.text;
    textarea?.replaceWith(textEl);
    
  } catch (error) {
    setGlobalError(`Failed to update note: ${error.message}`);
    // Revert on error
    const note = state.userNotes.find(n => n.id === noteId);
    if (note) {
      const textEl = document.createElement("div");
      textEl.className = "note-text";
      textEl.textContent = note.text;
      textarea?.replaceWith(textEl);
    }
  }
}

/**
 * Delete a note with confirmation.
 */
async function deleteNote(noteId) {
  if (!confirm("Delete this note?")) return;
  
  try {
    await fetchJson(`/api/meetings/${state.meetingId}/notes/${noteId}`, {
      method: "DELETE",
    });
    
    // Remove from local state
    state.userNotes = state.userNotes.filter(n => n.id !== noteId);
    
    // Remove card from DOM
    const card = document.querySelector(`.note-card[data-note-id="${noteId}"]`);
    card?.remove();
    
    updateNotesEmptyState();
    
  } catch (error) {
    setGlobalError(`Failed to delete note: ${error.message}`);
  }
}

/**
 * Update the empty state message visibility.
 */
function updateNotesEmptyState() {
  const emptyEl = document.getElementById("notes-empty");
  if (emptyEl) {
    emptyEl.style.display = state.userNotes.length === 0 ? "block" : "none";
  }
}

/**
 * Load notes from server and render them.
 */
async function loadUserNotes() {
  if (!state.meetingId) return;
  
  try {
    const data = await fetchJson(`/api/meetings/${state.meetingId}/notes`);
    state.userNotes = data.notes || [];
    state.userNotesDraft = data.draft;
    
    // Render existing notes
    const log = document.getElementById("notes-log");
    if (log) {
      // Clear existing note cards (keep empty message)
      const cards = log.querySelectorAll(".note-card");
      cards.forEach(card => card.remove());
      
      // Render all notes
      for (const note of state.userNotes) {
        renderNoteCard(note);
      }
    }
    
    updateNotesEmptyState();
    
    // Restore draft if exists
    if (state.userNotesDraft) {
      const input = document.getElementById("notes-input");
      if (input && state.userNotesDraft.text) {
        input.value = state.userNotesDraft.text;
      }
      if (state.userNotesDraft.timestamp !== null && state.userNotesDraft.timestamp !== undefined) {
        state.noteTimestamp = state.userNotesDraft.timestamp;
        updateNotesTimestampDisplay();
      }
      updateNotesSubmitButton();
    }
    
  } catch (error) {
    console.warn("Failed to load user notes:", error);
  }
}

/**
 * Initialize the notes panel event listeners.
 */
function initNotesPanel() {
  const input = document.getElementById("notes-input");
  const submitBtn = document.getElementById("notes-submit-btn");
  const clearBtn = document.getElementById("notes-clear-btn");
  
  if (input) {
    input.addEventListener("input", handleNotesInput);
    // Also handle paste
    input.addEventListener("paste", () => {
      setTimeout(() => handleNotesInput({ target: input }), 0);
    });
    // Enter submits, Shift+Enter inserts newline
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submitNote();
      }
    });
  }
  
  if (submitBtn) {
    submitBtn.addEventListener("click", submitNote);
  }
  
  if (clearBtn) {
    clearBtn.addEventListener("click", clearNoteInput);
  }
}

// Track the first server version we see to detect updates
let initialServerVersion = null;

async function refreshVersion() {
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:refreshVersion:enter',message:'refreshVersion called',data:{},timestamp:Date.now(),runId:'post-fix',hypothesisId:'VERSION'})}).catch(()=>{});
  // #endregion
  try {
    const data = await fetchJson("/api/health");
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:refreshVersion:data',message:'health data received',data:{version:data.version,status:data.status},timestamp:Date.now(),runId:'post-fix',hypothesisId:'VERSION'})}).catch(()=>{});
    // #endregion
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
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:updateTranscriptionControls:enter',message:'updateTranscriptionControls called',data:{meetingId:state.meetingId,hasMeeting:!!state.meeting,meetingStatus:state.meeting?.status},timestamp:Date.now(),runId:'meeting-controls-fix',hypothesisId:'H1-H2'})}).catch(()=>{});
  // #endregion
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
  
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:updateTranscriptionControls:state',message:'transcription controls state',data:{meetingId:state.meetingId,meetingStatus,isThisMeetingActive,isAnyActive,activeResponse:active,audioPath:meeting.audio_path},timestamp:Date.now(),runId:'meeting-controls-fix',hypothesisId:'H1-H2-H3'})}).catch(()=>{});
  // #endregion
  
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
    // Meeting is in_progress but not the active transcription job.
    // Check if finalization is running (has finalization_status or already
    // has transcript segments) vs truly paused.
    const finStatus = meeting.finalization_status;
    const hasSegments = ((meeting.transcript?.segments) || []).length > 0;
    const isFinalizing = finStatus && finStatus.status_text;

    if (isFinalizing || hasSegments) {
      // Finalization is running in the background -- not paused
      logToServer("finalizing in background");
      stopBtn.style.display = "none";
      resumeBtn.style.display = "none";
      statusBadge.textContent = isFinalizing ? `Finalizing: ${finStatus.status_text}` : "Finalizing...";
      statusBadge.className = "status-badge in-progress";
    } else {
      logToServer("in_progress but not active, showing resume");
      stopBtn.style.display = "none";
      resumeBtn.style.display = isAnyActive ? "none" : "inline-block";
      statusBadge.textContent = isAnyActive ? "Paused (another active)" : "Paused";
      statusBadge.className = isAnyActive ? "status-badge blocked" : "status-badge in-progress";
    }
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
  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:DOMContentLoaded',message:'meeting.js DOMContentLoaded fired',data:{url:window.location.href},timestamp:Date.now(),runId:'meeting-controls-fix',hypothesisId:'H1'})}).catch(()=>{});
  // #endregion
  try {
    loadMeetingId();
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:DOMContentLoaded:loadMeetingId',message:'meetingId loaded',data:{meetingId:state.meetingId},timestamp:Date.now(),runId:'post-fix',hypothesisId:'INIT'})}).catch(()=>{});
    // #endregion
  } catch (error) {
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:DOMContentLoaded:loadMeetingId:ERROR',message:'loadMeetingId failed',data:{error:error.message},timestamp:Date.now(),runId:'post-fix',hypothesisId:'INIT'})}).catch(()=>{});
    // #endregion
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
  
  // Debug panel toggle (new floating button)
  const toggleDebugBtn = document.getElementById("toggle-debug");
  if (toggleDebugBtn) {
    toggleDebugBtn.addEventListener("click", () => {
      const panel = document.getElementById("debug-sidebar");
      if (!panel) return;
      const isHidden = panel.style.display === "none" || !panel.style.display;
      panel.style.display = isHidden ? "flex" : "none";
      if (isHidden) {
        updateSummaryDebugPanel(state.meeting || null);
      }
    });
  }
  
  // Close debug panel button
  const closeDebugBtn = document.getElementById("close-debug");
  if (closeDebugBtn) {
    closeDebugBtn.addEventListener("click", () => {
      const panel = document.getElementById("debug-sidebar");
      if (panel) {
        panel.style.display = "none";
      }
    });
  }
  
  // Close attendee detail popup button
  const closeAttendeeBtn = document.getElementById("close-attendee-detail");
  if (closeAttendeeBtn) {
    closeAttendeeBtn.addEventListener("click", closeAttendeeDetailPopup);
  }
  
  // Legacy debug toggle (for backwards compatibility if old HTML is cached)
  const legacyToggle = document.getElementById("toggle-summary-debug");
  if (legacyToggle) {
    legacyToggle.addEventListener("click", () => {
      const panel = document.getElementById("summary-debug-panel");
      if (!panel) return;
      const isHidden = panel.style.display === "none" || !panel.style.display;
      panel.style.display = isHidden ? "block" : "none";
      if (isHidden) {
        updateSummaryDebugPanel(state.meeting || null);
      }
    });
  }

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
  
  // Panel maximize/restore buttons
  initPanelMaximize();
  
  // Debug section maximize buttons
  initDebugMaximize();
  
  // Initialize user notes panel
  initNotesPanel();
  
  // Initialize panel search for Transcript, Summary, and Notes panels
  initPanelSearch('transcript', '#transcript-output');
  initPanelSearch('summary', '#summary-output');
  initPanelSearch('notes', '#notes-log');
  
  window.addEventListener("beforeunload", () => {
    stopPolling();
    unsubscribeFromMeetingEvents();
  });

  // Subscribe to SSE for real-time events (streaming summary, etc.)
  subscribeToMeetingEvents();

  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:DOMContentLoaded:pre-init',message:'about to call initMeetingChat, refreshVersion, refreshMeeting',data:{meetingId:state.meetingId},timestamp:Date.now(),runId:'post-fix',hypothesisId:'INIT'})}).catch(()=>{});
  // #endregion

  // Initialize meeting chat UI
  initMeetingChat();

  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:DOMContentLoaded:post-initChat',message:'initMeetingChat done, calling refreshVersion',data:{hasChatInstance:!!state.meetingChat},timestamp:Date.now(),runId:'post-fix',hypothesisId:'INIT'})}).catch(()=>{});
  // #endregion

  await refreshVersion();

  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:DOMContentLoaded:post-refreshVersion',message:'refreshVersion done, calling refreshMeeting',data:{versionBadge:document.getElementById("version-badge")?.textContent},timestamp:Date.now(),runId:'post-fix',hypothesisId:'INIT'})}).catch(()=>{});
  // #endregion

  await refreshMeeting();
  
  // Load user notes after meeting is loaded
  await loadUserNotes();

  // #region agent log
  fetch('http://127.0.0.1:7242/ingest/4caeca80-116f-4cf5-9fc0-b1212b4dcd92',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'meeting.js:DOMContentLoaded:complete',message:'DOMContentLoaded fully complete',data:{meetingId:state.meetingId,hasMeeting:!!state.meeting,meetingStatus:state.meeting?.status},timestamp:Date.now(),runId:'post-fix',hypothesisId:'INIT'})}).catch(()=>{});
  // #endregion
});
