/**
 * Shared Chat UI Component
 * 
 * A reusable chat component for AI-powered meeting queries.
 * Used by both meeting-specific chat and overall chat.
 */

class ChatUI {
  /**
   * Create a new ChatUI instance.
   * 
   * @param {Object} options
   * @param {HTMLElement} options.container - Container element to render chat into
   * @param {string} options.endpoint - API endpoint for chat requests
   * @param {Function} options.buildPayload - Function to build request payload from question
   * @param {string} options.placeholder - Placeholder text for input
   * @param {string} options.title - Title for the chat panel
   * @param {boolean} options.showSearch - Whether to show "Searching..." during requests
   * @param {boolean} options.fullscreen - If true, render a fullscreen chat without header
   * @param {boolean} options.minimal - If true, hide clear/collapse buttons
   */
  constructor(options) {
    this.container = options.container;
    this.endpoint = options.endpoint;
    this.buildPayload = options.buildPayload || ((q) => ({ question: q }));
    this.placeholder = options.placeholder || "Ask a question...";
    this.title = options.title || "Chat";
    this.showSearch = options.showSearch !== false; // Default true
    this.fullscreen = options.fullscreen || false;
    this.minimal = options.minimal || false;
    this.historyEndpoint = options.historyEndpoint || null;
    // External search: pass a container element that already has
    // .chat-search-bar, .chat-search-input, etc. and a toggle button
    this.externalSearchContainer = options.searchContainer || null;
    this.externalSearchToggle = options.searchToggle || null;
    
    this.messages = [];
    this.isLoading = false;
    this.abortController = null;
    
    // Search state
    this._searchMatches = [];
    this._searchIndex = -1;
    
    this.render();
    this.attachEventListeners();
    
    // Load persisted history if endpoint provided
    if (this.historyEndpoint) {
      this.loadHistory();
    }
  }
  
  /**
   * Return the search bar HTML snippet.
   */
  _searchBarHtml() {
    return `<div class="chat-search-bar" style="display:none">
      <input class="chat-search-input" placeholder="Search chat..." />
      <span class="chat-search-count">0/0</span>
      <button class="chat-search-prev" title="Previous">&#9650;</button>
      <button class="chat-search-next" title="Next">&#9660;</button>
    </div>`;
  }

  /**
   * Render the chat UI structure.
   */
  render() {
    const clearBtn = (this.minimal || this.fullscreen) ? '' : '<button class="chat-clear secondary" type="button" title="Clear chat history">Clear</button>';
    const searchBar = this._searchBarHtml();
    
    if (this.fullscreen) {
      // Fullscreen variant - no header, fills container
      // Search controls sit inline on the top bar, same row as the toggle icon
      this.container.innerHTML = `
        <div class="chat-panel chat-panel-fullscreen">
          <div class="chat-top-bar">
            <div class="chat-search-bar chat-search-bar-inline" style="display:none">
              <input class="chat-search-input" placeholder="Search..." />
              <span class="chat-search-count">0/0</span>
              <button class="chat-search-prev" title="Previous">&#9650;</button>
              <button class="chat-search-next" title="Next">&#9660;</button>
            </div>
            <button class="chat-search-toggle icon-btn" type="button" title="Search chat (Cmd+F)">&#128269;</button>
          </div>
          <div class="chat-body chat-body-fullscreen">
            <div class="chat-messages chat-messages-fullscreen" id="chat-messages-${this.container.id}">
              <div class="chat-empty">Ask a question about your meetings.</div>
            </div>
            <div class="chat-input-area">
              <div class="chat-input-row">
                <input 
                  type="text" 
                  class="chat-input" 
                  placeholder="${this.escapeHtml(this.placeholder)}"
                  id="chat-input-${this.container.id}"
                />
                <button class="chat-send" type="button" id="chat-send-${this.container.id}">Send</button>
                ${clearBtn}
              </div>
            </div>
          </div>
        </div>
      `;
    } else if (this.minimal) {
      // Minimal variant - no header, no clear/collapse, just chat
      // Search bar/button are provided externally via searchContainer/searchToggle options
      this.container.innerHTML = `
        <div class="chat-panel chat-panel-minimal">
          <div class="chat-body chat-body-minimal">
            <div class="chat-messages chat-messages-minimal" id="chat-messages-${this.container.id}">
              <div class="chat-empty">Ask a question about this meeting.</div>
            </div>
            <div class="chat-input-row">
              <input 
                type="text" 
                class="chat-input" 
                placeholder="${this.escapeHtml(this.placeholder)}"
                id="chat-input-${this.container.id}"
              />
              <button class="chat-send" type="button" id="chat-send-${this.container.id}">Send</button>
            </div>
          </div>
        </div>
      `;
    } else {
      // Standard collapsible variant
      this.container.innerHTML = `
        <div class="chat-panel">
          <div class="chat-header">
            <h3 class="chat-title">${this.escapeHtml(this.title)}</h3>
            <div class="chat-header-actions">
              <button class="chat-search-toggle secondary small" type="button" title="Search chat (Cmd+F)">&#128269;</button>
              <button class="chat-clear secondary small" type="button" title="Clear chat history">Clear</button>
              <button class="chat-toggle secondary small" type="button">Collapse</button>
            </div>
          </div>
          ${searchBar}
          <div class="chat-body">
            <div class="chat-messages" id="chat-messages-${this.container.id}">
              <div class="chat-empty">Ask a question about your meetings.</div>
            </div>
            <div class="chat-input-row">
              <input 
                type="text" 
                class="chat-input" 
                placeholder="${this.escapeHtml(this.placeholder)}"
                id="chat-input-${this.container.id}"
              />
              <button class="chat-send" type="button" id="chat-send-${this.container.id}">Send</button>
            </div>
          </div>
        </div>
      `;
    }
    
    // Cache element references
    this.messagesEl = this.container.querySelector('.chat-messages');
    this.inputEl = this.container.querySelector('.chat-input');
    this.sendBtn = this.container.querySelector('.chat-send');
    this.toggleBtn = this.container.querySelector('.chat-toggle');
    this.clearBtn = this.container.querySelector('.chat-clear');
    this.bodyEl = this.container.querySelector('.chat-body');
    
    // Search bar references — use external container if provided, else look inside rendered HTML
    const searchRoot = this.externalSearchContainer || this.container;
    this.searchBarEl = searchRoot.querySelector('.chat-search-bar');
    this.searchInputEl = searchRoot.querySelector('.chat-search-input');
    this.searchCountEl = searchRoot.querySelector('.chat-search-count');
    this.searchPrevBtn = searchRoot.querySelector('.chat-search-prev');
    this.searchNextBtn = searchRoot.querySelector('.chat-search-next');
    this.searchToggleBtn = this.externalSearchToggle || this.container.querySelector('.chat-search-toggle');
  }
  
  /**
   * Attach event listeners.
   */
  attachEventListeners() {
    // Send on button click
    this.sendBtn.addEventListener('click', () => this.sendMessage());
    
    // Send on Enter key
    this.inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
    });
    
    // Right-click context menu on send button for "Submit and Log" (debug feature)
    this.sendBtn.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      this.testShowContextMenu(e);
    });
    
    // Toggle collapse (only exists in standard mode)
    if (this.toggleBtn) {
      this.toggleBtn.addEventListener('click', () => this.toggleCollapse());
    }
    
    // Clear chat (only exists in non-minimal modes)
    if (this.clearBtn) {
      this.clearBtn.addEventListener('click', () => this.clearMessages());
    }
    
    // Search bar events
    if (this.searchInputEl) {
      this.searchInputEl.addEventListener('input', () => this.performSearch(this.searchInputEl.value));
      this.searchInputEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          this.navigateSearch(e.shiftKey ? -1 : 1);
        } else if (e.key === 'Escape') {
          this.closeSearch();
        }
      });
      this.searchPrevBtn.addEventListener('click', () => this.navigateSearch(-1));
      this.searchNextBtn.addEventListener('click', () => this.navigateSearch(1));
    }
    
    // Search toggle button
    if (this.searchToggleBtn) {
      this.searchToggleBtn.addEventListener('click', () => {
        if (this.searchBarEl && this.searchBarEl.style.display !== 'none') {
          this.closeSearch();
        } else {
          this.openSearch();
        }
      });
    }
    
    // Ctrl+F / Cmd+F to open search when typing in the chat input
    this.inputEl.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
        e.preventDefault();
        this.openSearch();
      }
    });
  }
  
  /**
   * Show context menu for debug options (test/debug feature).
   * @param {MouseEvent} e
   */
  testShowContextMenu(e) {
    // Remove any existing context menu
    const existing = document.querySelector('.test-chat-context-menu');
    if (existing) existing.remove();
    
    // Create context menu
    const menu = document.createElement('div');
    menu.className = 'test-chat-context-menu';
    menu.style.cssText = `
      position: fixed;
      left: ${e.clientX}px;
      top: ${e.clientY}px;
      background: var(--bg-color, #fff);
      border: 1px solid var(--border-color, #ddd);
      border-radius: 4px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.15);
      z-index: 10000;
      padding: 4px 0;
      min-width: 150px;
    `;
    
    const option = document.createElement('div');
    option.textContent = 'Submit and Log';
    option.style.cssText = `
      padding: 8px 16px;
      cursor: pointer;
      font-size: 14px;
    `;
    option.addEventListener('mouseenter', () => {
      option.style.background = 'var(--hover-bg, #f0f0f0)';
    });
    option.addEventListener('mouseleave', () => {
      option.style.background = 'transparent';
    });
    option.addEventListener('click', () => {
      menu.remove();
      this.sendMessage(true); // Pass testLogThis=true
    });
    
    menu.appendChild(option);
    document.body.appendChild(menu);
    
    // Close menu on click outside
    const closeMenu = (event) => {
      if (!menu.contains(event.target)) {
        menu.remove();
        document.removeEventListener('click', closeMenu);
      }
    };
    // Delay adding listener to avoid immediate close
    setTimeout(() => document.addEventListener('click', closeMenu), 10);
  }
  
  /**
   * Toggle chat panel collapse state.
   */
  toggleCollapse() {
    const isCollapsed = this.bodyEl.style.display === 'none';
    this.bodyEl.style.display = isCollapsed ? 'block' : 'none';
    this.toggleBtn.textContent = isCollapsed ? 'Collapse' : 'Expand';
  }
  
  /**
   * Send a message to the chat.
   * @param {boolean} testLogThis - Debug flag to log full LLM input/output
   */
  async sendMessage(testLogThis = false) {
    const question = this.inputEl.value.trim();
    if (!question || this.isLoading) return;
    
    // Clear input
    this.inputEl.value = '';
    
    // Add user message
    this.addMessage('user', question);
    
    // Start loading
    this.setLoading(true);
    const statusText = testLogThis 
      ? 'Logging and sending...' 
      : (this.showSearch ? 'Searching meetings...' : 'Thinking...');
    this.setStatus(statusText);
    
    // Create abort controller for this request
    this.abortController = new AbortController();
    
    try {
      const payload = this.buildPayload(question);
      
      // Add test_log_this flag if requested (debug feature)
      if (testLogThis) {
        payload.test_log_this = true;
      }
      
      const response = await fetch(this.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: this.abortController.signal,
      });
      
      if (!response.ok) {
        let errorText;
        try {
          const errorJson = await response.json();
          errorText = errorJson.detail || errorJson.error || errorJson.message;
        } catch {
          errorText = await response.text();
        }
        throw new Error(errorText || `Request failed: ${response.status}`);
      }
      
      // Update status to show we're receiving response
      this.setStatus(testLogThis ? 'Generating response (logging)...' : 'Generating response...');
      
      // Handle SSE streaming response
      await this.handleStreamingResponse(response);
      
      // Show confirmation if logging was enabled
      if (testLogThis) {
        console.log('[ChatUI] Request logged to logs/llm/');
      }
      
    } catch (error) {
      if (error.name === 'AbortError') {
        this.setStatus('Cancelled');
        // Clear status after a short delay
        setTimeout(() => this.setStatus(''), 2000);
      } else {
        console.error('Chat error:', error);
        this.addMessage('assistant', `Sorry, something went wrong: ${error.message}`);
        this.setStatus('');
      }
    } finally {
      this.setLoading(false);
      this.abortController = null;
      this.saveHistory();
    }
  }
  
  /**
   * Handle SSE streaming response.
   * @param {Response} response
   */
  async handleStreamingResponse(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let assistantMessage = '';
    let messageEl = null;
    
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        const text = decoder.decode(value, { stream: true });
        const lines = text.split('\n');
        
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          
          const data = line.slice(6); // Remove 'data: ' prefix
          
          if (data === '[DONE]') {
            this.setStatus('');
            return;
          }
          
          try {
            const parsed = JSON.parse(data);
            
            if (parsed.error) {
              this.addMessage('assistant', `Error: ${parsed.error}`);
              this.setStatus('');
              return;
            }
            
            if (parsed.token) {
              assistantMessage += parsed.token;
              
              // Create or update message element
              if (!messageEl) {
                messageEl = this.addMessage('assistant', assistantMessage, true);
              } else {
                messageEl.querySelector('.chat-message-content').textContent = assistantMessage;
                // Keep the in-memory message content in sync for persistence
                const lastMsg = this.messages[this.messages.length - 1];
                if (lastMsg && lastMsg.role === 'assistant') {
                  lastMsg.content = assistantMessage;
                }
              }
              
              // Auto-scroll to bottom
              this.scrollToBottom();
            }
          } catch (parseError) {
            // Ignore parse errors for partial data
          }
        }
      }
    } finally {
      // Ensure status is cleared
      this.setStatus('');
    }
  }
  
  /**
   * Add a message to the chat.
   * @param {'user'|'assistant'} role
   * @param {string} content
   * @param {boolean} streaming - If true, returns the element for streaming updates
   * @param {string|null} timestamp - ISO timestamp; defaults to now
   * @returns {HTMLElement|undefined}
   */
  addMessage(role, content, streaming = false, timestamp = null) {
    // Remove empty state if present
    const emptyState = this.messagesEl.querySelector('.chat-empty');
    if (emptyState) {
      emptyState.remove();
    }
    
    const ts = timestamp || new Date().toISOString();
    const messageEl = document.createElement('div');
    messageEl.className = `chat-message chat-message-${role}`;
    messageEl.innerHTML = `
      <div class="chat-message-meta">
        <span class="chat-message-role">${role === 'user' ? 'You' : 'Assistant'}</span>
        <span class="chat-message-time">${this.formatTimestamp(ts)}</span>
      </div>
      <div class="chat-message-content">${this.escapeHtml(content)}</div>
    `;
    
    this.messagesEl.appendChild(messageEl);
    
    // Store message with timestamp
    this.messages.push({ role, content, timestamp: ts });
    
    // Scroll to bottom
    this.scrollToBottom();
    
    if (streaming) {
      return messageEl;
    }
  }
  
  /**
   * Format an ISO timestamp as a datetime string.
   * @param {string} isoString
   * @returns {string}
   */
  formatTimestamp(isoString) {
    try {
      const date = new Date(isoString);
      return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
        + ', ' + date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    } catch {
      return '';
    }
  }
  
  /**
   * Set loading state.
   * @param {boolean} loading
   */
  setLoading(loading) {
    this.isLoading = loading;
    this.sendBtn.disabled = loading;
    this.inputEl.disabled = loading;
    this.sendBtn.textContent = loading ? '...' : 'Send';
  }
  
  /**
   * Set status message — shown as a temporary bubble in the messages area.
   * @param {string} message
   */
  setStatus(message) {
    // Remove any existing status bubble
    const existing = this.messagesEl.querySelector('.chat-status-bubble');
    if (existing) existing.remove();
    
    if (message) {
      const bubble = document.createElement('div');
      bubble.className = 'chat-message chat-message-assistant chat-status-bubble';
      bubble.innerHTML = `<div class="chat-message-content chat-status-text">${this.escapeHtml(message)}</div>`;
      this.messagesEl.appendChild(bubble);
      this.scrollToBottom();
    }
  }
  
  /**
   * Scroll messages to bottom.
   */
  scrollToBottom() {
    this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
  }
  
  /**
   * Clear all messages.
   */
  clearMessages() {
    this.messages = [];
    this.messagesEl.innerHTML = '<div class="chat-empty">Ask a question about your meetings.</div>';
    this.saveHistory();
  }
  
  /**
   * Cancel ongoing request.
   */
  cancel() {
    if (this.abortController) {
      this.abortController.abort();
    }
  }
  
  /**
   * Escape HTML special characters.
   * @param {string} text
   * @returns {string}
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
  
  // ---- History persistence ----
  
  /**
   * Load chat history from the server and render existing messages.
   */
  async loadHistory() {
    if (!this.historyEndpoint) return;
    try {
      const res = await fetch(this.historyEndpoint);
      if (!res.ok) return;
      const data = await res.json();
      const msgs = data.messages || [];
      if (msgs.length === 0) return;
      // Render each saved message (without re-saving)
      for (const msg of msgs) {
        this.addMessage(msg.role, msg.content, false, msg.timestamp || null);
      }
    } catch (err) {
      console.warn('[ChatUI] Failed to load history:', err);
    }
  }
  
  /**
   * Persist current messages to the server. No-op if historyEndpoint is null.
   */
  async saveHistory() {
    if (!this.historyEndpoint) return;
    try {
      await fetch(this.historyEndpoint, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: this.messages }),
      });
    } catch (err) {
      console.warn('[ChatUI] Failed to save history:', err);
    }
  }
  
  // ---- Search functionality ----
  
  /**
   * Show the search bar and focus the input.
   */
  openSearch() {
    if (!this.searchBarEl) return;
    this.searchBarEl.style.display = 'flex';
    this.searchInputEl.focus();
    if (this.searchInputEl.value) {
      this.performSearch(this.searchInputEl.value);
    }
  }
  
  /**
   * Hide the search bar and clear highlights.
   */
  closeSearch() {
    if (!this.searchBarEl) return;
    this.searchBarEl.style.display = 'none';
    this.searchInputEl.value = '';
    this._clearSearchHighlights();
    this._searchMatches = [];
    this._searchIndex = -1;
    this.searchCountEl.textContent = '0/0';
  }
  
  /**
   * Perform a case-insensitive search across all chat message content elements.
   * @param {string} query
   */
  performSearch(query) {
    this._clearSearchHighlights();
    this._searchMatches = [];
    this._searchIndex = -1;
    
    if (!query) {
      this.searchCountEl.textContent = '0/0';
      return;
    }
    
    const lowerQuery = query.toLowerCase();
    const contentEls = this.messagesEl.querySelectorAll('.chat-message-content');
    
    contentEls.forEach((el) => {
      const text = el.textContent;
      const lowerText = text.toLowerCase();
      let idx = 0;
      const parts = [];
      let lastEnd = 0;
      
      while ((idx = lowerText.indexOf(lowerQuery, idx)) !== -1) {
        // Text before the match
        if (idx > lastEnd) {
          parts.push(document.createTextNode(text.slice(lastEnd, idx)));
        }
        // The match itself
        const mark = document.createElement('mark');
        mark.textContent = text.slice(idx, idx + query.length);
        parts.push(mark);
        this._searchMatches.push(mark);
        lastEnd = idx + query.length;
        idx = lastEnd;
      }
      
      if (parts.length > 0) {
        // Remaining text after last match
        if (lastEnd < text.length) {
          parts.push(document.createTextNode(text.slice(lastEnd)));
        }
        el.textContent = '';
        parts.forEach((node) => el.appendChild(node));
      }
    });
    
    if (this._searchMatches.length > 0) {
      this._searchIndex = 0;
      this._highlightCurrentMatch();
    }
    this._updateSearchCount();
  }
  
  /**
   * Navigate to the next (+1) or previous (-1) search match.
   * @param {number} direction - +1 for next, -1 for previous
   */
  navigateSearch(direction) {
    if (this._searchMatches.length === 0) return;
    
    // Remove current highlight
    const prev = this._searchMatches[this._searchIndex];
    if (prev) prev.classList.remove('current');
    
    // Move index with wrapping
    this._searchIndex = (this._searchIndex + direction + this._searchMatches.length) % this._searchMatches.length;
    this._highlightCurrentMatch();
    this._updateSearchCount();
  }
  
  /**
   * @private Highlight the current match and scroll it into view.
   */
  _highlightCurrentMatch() {
    const el = this._searchMatches[this._searchIndex];
    if (!el) return;
    el.classList.add('current');
    el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  
  /**
   * @private Update the "N/M" count display.
   */
  _updateSearchCount() {
    const total = this._searchMatches.length;
    const current = total > 0 ? this._searchIndex + 1 : 0;
    this.searchCountEl.textContent = `${current}/${total}`;
  }
  
  /**
   * @private Remove all <mark> highlights, restoring original text content.
   */
  _clearSearchHighlights() {
    const marks = this.messagesEl.querySelectorAll('mark');
    marks.forEach((mark) => {
      const parent = mark.parentNode;
      parent.replaceChild(document.createTextNode(mark.textContent), mark);
      parent.normalize(); // merge adjacent text nodes
    });
  }
  
  /**
   * Destroy the chat UI and clean up.
   */
  destroy() {
    this.cancel();
    this.container.innerHTML = '';
  }
}

// Export for use in other files
if (typeof window !== 'undefined') {
  window.ChatUI = ChatUI;
}
