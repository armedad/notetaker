/**
 * ChatUI — A reusable streaming chat component.
 *
 * Renders a chat interface with message bubbles, an input field, and optional
 * search. Streams responses from a server endpoint via Server-Sent Events (SSE)
 * and optionally persists chat history to a REST endpoint.
 *
 * Three layout variants are available:
 *   - **fullscreen** — no header, fills its container, top bar with search toggle
 *   - **minimal** — no header or chrome, designed for embedding in panels
 *   - **standard** — collapsible header with title, clear, and collapse buttons
 *
 * @example
 * const chat = new ChatUI({
 *   container: document.getElementById('chat'),
 *   endpoint: '/api/chat',
 * });
 *
 * @see README.md for full documentation.
 */
class ChatUI {
  /**
   * Create a new ChatUI instance.
   *
   * @param {Object} options
   * @param {HTMLElement} options.container - DOM element to render into (required).
   * @param {string} options.endpoint - URL for POST chat requests; must return an SSE stream (required).
   * @param {Function} [options.buildPayload] - Builds the JSON body from the user's question string. Default: `(q) => ({ question: q })`.
   * @param {string} [options.placeholder="Ask a question..."] - Input placeholder text.
   * @param {string} [options.title="Chat"] - Header title (standard variant only).
   * @param {string} [options.emptyText="Ask a question..."] - Text shown when the message list is empty.
   * @param {boolean} [options.fullscreen=false] - Use the fullscreen layout variant.
   * @param {boolean} [options.minimal=false] - Use the minimal layout variant.
   * @param {boolean} [options.enableSearch=true] - Show search UI. Set `false` to hide search entirely.
   * @param {string} [options.searchPlaceholder="Search..."] - Placeholder text for the search input.
   * @param {Object} [options.roleLabels] - Display labels for message roles.
   * @param {string} [options.roleLabels.user="You"] - Label for user messages.
   * @param {string} [options.roleLabels.assistant="Assistant"] - Label for assistant messages.
   * @param {Object} [options.statusMessages] - Status text shown at various stages.
   * @param {string} [options.statusMessages.sending="Sending..."] - While waiting for a response.
   * @param {string} [options.statusMessages.generating="Generating response..."] - While tokens stream in.
   * @param {string} [options.statusMessages.cancelled="Cancelled"] - When the request is aborted.
   * @param {string|null} [options.historyEndpoint=null] - URL for GET/PUT history persistence. `null` disables persistence.
   * @param {HTMLElement|null} [options.searchContainer=null] - External DOM element containing search bar markup. Used when search lives outside the ChatUI container (e.g. in a panel header).
   * @param {HTMLElement|null} [options.searchToggle=null] - External button element that toggles search visibility.
   * @param {Function|null} [options.onSendMessage=null] - Hook called with `(payload)` just before the fetch. Lets consumers mutate the payload (e.g. add debug flags).
   */
  constructor(options) {
    // Required
    this.container = options.container;
    this.endpoint = options.endpoint;

    // Payload & input
    this.buildPayload = options.buildPayload || ((q) => ({ question: q }));
    this.placeholder = options.placeholder || 'Ask a question...';
    this.title = options.title || 'Chat';
    this.emptyText = options.emptyText || 'Ask a question...';

    // Layout variants
    this.fullscreen = options.fullscreen || false;
    this.minimal = options.minimal || false;

    // Search
    this.enableSearch = options.enableSearch !== false;
    this.searchPlaceholder = options.searchPlaceholder || 'Search...';

    // Labels
    this.roleLabels = Object.assign(
      { user: 'You', assistant: 'Assistant' },
      options.roleLabels || {}
    );
    this.statusMessages = Object.assign(
      { sending: 'Sending...', generating: 'Generating response...', cancelled: 'Cancelled' },
      options.statusMessages || {}
    );

    // Persistence
    this.historyEndpoint = options.historyEndpoint || null;

    // External search elements
    this.externalSearchContainer = options.searchContainer || null;
    this.externalSearchToggle = options.searchToggle || null;

    // Hooks
    this.onSendMessage = options.onSendMessage || null;

    // Internal state
    this.messages = [];
    this.isLoading = false;
    this.abortController = null;
    this._searchMatches = [];
    this._searchIndex = -1;
    this._uid = Math.random().toString(36).slice(2, 8);

    // Build the DOM
    this._render();
    this._attachEventListeners();

    // Load persisted history
    if (this.historyEndpoint) {
      this.loadHistory();
    }
  }

  // ---------------------------------------------------------------------------
  //  Rendering
  // ---------------------------------------------------------------------------

  /**
   * Build and inject the chat DOM structure into the container.
   * @private
   */
  _render() {
    const clearBtn =
      this.minimal || this.fullscreen
        ? ''
        : '<button class="chat-clear secondary" type="button" title="Clear chat history">Clear</button>';

    const searchBarHtml = this.enableSearch
      ? `<div class="chat-search-bar chat-search-bar-inline" style="display:none">
           <input class="chat-search-input" placeholder="${this._esc(this.searchPlaceholder)}" />
           <span class="chat-search-count">0/0</span>
           <button class="chat-search-prev" title="Previous">&#9650;</button>
           <button class="chat-search-next" title="Next">&#9660;</button>
         </div>`
      : '';

    const searchToggleHtml = this.enableSearch
      ? '<button class="chat-search-toggle icon-btn" type="button" title="Search chat (Cmd+F)">&#128269;</button>'
      : '';

    if (this.fullscreen) {
      this.container.innerHTML = `
        <div class="chat-panel chat-panel-fullscreen">
          <div class="chat-top-bar">
            ${searchBarHtml}
            ${searchToggleHtml}
          </div>
          <div class="chat-body chat-body-fullscreen">
            <div class="chat-messages chat-messages-fullscreen">
              <div class="chat-empty">${this._esc(this.emptyText)}</div>
            </div>
            <div class="chat-input-area">
              <div class="chat-input-row">
                <input type="text" class="chat-input" placeholder="${this._esc(this.placeholder)}" />
                <button class="chat-send" type="button">Send</button>
                ${clearBtn}
              </div>
            </div>
          </div>
        </div>`;
    } else if (this.minimal) {
      this.container.innerHTML = `
        <div class="chat-panel chat-panel-minimal">
          <div class="chat-body chat-body-minimal">
            <div class="chat-messages chat-messages-minimal">
              <div class="chat-empty">${this._esc(this.emptyText)}</div>
            </div>
            <div class="chat-input-row">
              <input type="text" class="chat-input" placeholder="${this._esc(this.placeholder)}" />
              <button class="chat-send" type="button">Send</button>
            </div>
          </div>
        </div>`;
    } else {
      const standardSearchBar = this.enableSearch
        ? `<div class="chat-search-bar" style="display:none">
             <input class="chat-search-input" placeholder="${this._esc(this.searchPlaceholder)}" />
             <span class="chat-search-count">0/0</span>
             <button class="chat-search-prev" title="Previous">&#9650;</button>
             <button class="chat-search-next" title="Next">&#9660;</button>
           </div>`
        : '';

      this.container.innerHTML = `
        <div class="chat-panel">
          <div class="chat-header">
            <h3 class="chat-title">${this._esc(this.title)}</h3>
            <div class="chat-header-actions">
              ${searchToggleHtml}
              <button class="chat-clear secondary small" type="button" title="Clear chat history">Clear</button>
              <button class="chat-toggle secondary small" type="button">Collapse</button>
            </div>
          </div>
          ${standardSearchBar}
          <div class="chat-body">
            <div class="chat-messages">
              <div class="chat-empty">${this._esc(this.emptyText)}</div>
            </div>
            <div class="chat-input-row">
              <input type="text" class="chat-input" placeholder="${this._esc(this.placeholder)}" />
              <button class="chat-send" type="button">Send</button>
            </div>
          </div>
        </div>`;
    }

    // Cache element references
    this.messagesEl = this.container.querySelector('.chat-messages');
    this.inputEl = this.container.querySelector('.chat-input');
    this.sendBtn = this.container.querySelector('.chat-send');
    this.toggleBtn = this.container.querySelector('.chat-toggle');
    this.clearBtn = this.container.querySelector('.chat-clear');
    this.bodyEl = this.container.querySelector('.chat-body');

    // Search bar — use external elements when provided, else find within rendered HTML
    const searchRoot = this.externalSearchContainer || this.container;
    this.searchBarEl = searchRoot.querySelector('.chat-search-bar');
    this.searchInputEl = searchRoot.querySelector('.chat-search-input');
    this.searchCountEl = searchRoot.querySelector('.chat-search-count');
    this.searchPrevBtn = searchRoot.querySelector('.chat-search-prev');
    this.searchNextBtn = searchRoot.querySelector('.chat-search-next');
    this.searchToggleBtn =
      this.externalSearchToggle || this.container.querySelector('.chat-search-toggle');
  }

  /**
   * Wire up all DOM event listeners.
   * @private
   */
  _attachEventListeners() {
    // Send on button click
    this.sendBtn.addEventListener('click', () => this.sendMessage());

    // Send on Enter
    this.inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
    });

    // Collapse toggle (standard variant only)
    if (this.toggleBtn) {
      this.toggleBtn.addEventListener('click', () => this.toggleCollapse());
    }

    // Clear button
    if (this.clearBtn) {
      this.clearBtn.addEventListener('click', () => this.clearMessages());
    }

    // Search bar events
    if (this.searchInputEl) {
      this.searchInputEl.addEventListener('input', () =>
        this.performSearch(this.searchInputEl.value)
      );
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

    // Cmd+F / Ctrl+F shortcut when input is focused
    this.inputEl.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
        e.preventDefault();
        this.openSearch();
      }
    });
  }

  // ---------------------------------------------------------------------------
  //  Messaging
  // ---------------------------------------------------------------------------

  /**
   * Send the current input as a message and stream the assistant's response.
   *
   * Reads the input field, posts to `this.endpoint` with the payload from
   * `buildPayload`, then processes the SSE stream to render tokens incrementally.
   *
   * @returns {Promise<void>}
   */
  async sendMessage() {
    const question = this.inputEl.value.trim();
    if (!question || this.isLoading) return;

    this.inputEl.value = '';
    this.addMessage('user', question);
    this.setLoading(true);
    this.setStatus(this.statusMessages.sending);

    this.abortController = new AbortController();

    try {
      const payload = this.buildPayload(question);

      // Consumer hook — allows mutating the payload (e.g. adding debug flags)
      if (this.onSendMessage) {
        this.onSendMessage(payload);
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

      this.setStatus(this.statusMessages.generating);
      await this._handleStream(response);
    } catch (error) {
      if (error.name === 'AbortError') {
        this.setStatus(this.statusMessages.cancelled);
        setTimeout(() => this.setStatus(''), 2000);
      } else {
        console.error('[ChatUI] error:', error);
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
   * Process an SSE streaming response and render tokens incrementally.
   *
   * Expected SSE format:
   * - `data: {"token": "..."}` — a text chunk to append
   * - `data: {"error": "..."}` — an error message from the server
   * - `data: [DONE]` — signals the end of the stream
   *
   * @param {Response} response - The fetch Response object.
   * @returns {Promise<void>}
   * @private
   */
  async _handleStream(response) {
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
          const data = line.slice(6);

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

              if (!messageEl) {
                messageEl = this.addMessage('assistant', assistantMessage, true);
              } else {
                messageEl.querySelector('.chat-message-content').textContent = assistantMessage;
                const lastMsg = this.messages[this.messages.length - 1];
                if (lastMsg && lastMsg.role === 'assistant') {
                  lastMsg.content = assistantMessage;
                }
              }
              this.scrollToBottom();
            }
          } catch {
            // Ignore parse errors for partial SSE chunks
          }
        }
      }
    } finally {
      this.setStatus('');
    }
  }

  /**
   * Add a message to the chat.
   *
   * @param {'user'|'assistant'} role - The message author.
   * @param {string} content - Plain-text message content (HTML is escaped).
   * @param {boolean} [streaming=false] - If `true`, returns the DOM element for incremental updates.
   * @param {string|null} [timestamp=null] - ISO 8601 timestamp; defaults to the current time.
   * @returns {HTMLElement|undefined} The message element when `streaming` is `true`.
   */
  addMessage(role, content, streaming = false, timestamp = null) {
    const emptyState = this.messagesEl.querySelector('.chat-empty');
    if (emptyState) emptyState.remove();

    const ts = timestamp || new Date().toISOString();
    const label = role === 'user' ? this.roleLabels.user : this.roleLabels.assistant;

    const el = document.createElement('div');
    el.className = `chat-message chat-message-${role}`;
    el.innerHTML = `
      <div class="chat-message-meta">
        <span class="chat-message-role">${this._esc(label)}</span>
        <span class="chat-message-time">${this.formatTimestamp(ts)}</span>
      </div>
      <div class="chat-message-content">${this._esc(content)}</div>`;

    this.messagesEl.appendChild(el);
    this.messages.push({ role, content, timestamp: ts });
    this.scrollToBottom();

    if (streaming) return el;
  }

  /**
   * Remove all messages and reset the chat to its empty state.
   */
  clearMessages() {
    this.messages = [];
    this.messagesEl.innerHTML = `<div class="chat-empty">${this._esc(this.emptyText)}</div>`;
    this.saveHistory();
  }

  /**
   * Cancel an in-flight request.
   */
  cancel() {
    if (this.abortController) {
      this.abortController.abort();
    }
  }

  // ---------------------------------------------------------------------------
  //  UI state
  // ---------------------------------------------------------------------------

  /**
   * Toggle the loading state of the input and send button.
   * @param {boolean} loading
   */
  setLoading(loading) {
    this.isLoading = loading;
    this.sendBtn.disabled = loading;
    this.inputEl.disabled = loading;
    this.sendBtn.textContent = loading ? '...' : 'Send';
  }

  /**
   * Show or hide a temporary status bubble in the messages area.
   *
   * Pass an empty string to remove the status bubble.
   *
   * @param {string} message
   */
  setStatus(message) {
    const existing = this.messagesEl.querySelector('.chat-status-bubble');
    if (existing) existing.remove();

    if (message) {
      const bubble = document.createElement('div');
      bubble.className = 'chat-message chat-message-assistant chat-status-bubble';
      bubble.innerHTML = `<div class="chat-message-content chat-status-text">${this._esc(message)}</div>`;
      this.messagesEl.appendChild(bubble);
      this.scrollToBottom();
    }
  }

  /**
   * Scroll the messages container to the bottom.
   */
  scrollToBottom() {
    this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
  }

  /**
   * Toggle chat body visibility (standard variant only).
   */
  toggleCollapse() {
    const collapsed = this.bodyEl.style.display === 'none';
    this.bodyEl.style.display = collapsed ? 'block' : 'none';
    this.toggleBtn.textContent = collapsed ? 'Collapse' : 'Expand';
  }

  // ---------------------------------------------------------------------------
  //  History persistence
  // ---------------------------------------------------------------------------

  /**
   * Load chat history from the server and render saved messages.
   *
   * Expects `GET historyEndpoint` to return `{ messages: [{ role, content, timestamp? }] }`.
   *
   * @returns {Promise<void>}
   */
  async loadHistory() {
    if (!this.historyEndpoint) return;
    try {
      const res = await fetch(this.historyEndpoint);
      if (!res.ok) return;
      const data = await res.json();
      const msgs = data.messages || [];
      if (msgs.length === 0) return;
      for (const msg of msgs) {
        this.addMessage(msg.role, msg.content, false, msg.timestamp || null);
      }
    } catch (err) {
      console.warn('[ChatUI] Failed to load history:', err);
    }
  }

  /**
   * Persist current messages to the server.
   *
   * Sends `PUT historyEndpoint` with `{ messages: [...] }`. No-op if
   * `historyEndpoint` is `null`.
   *
   * @returns {Promise<void>}
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

  // ---------------------------------------------------------------------------
  //  Search
  // ---------------------------------------------------------------------------

  /**
   * Show the search bar and focus its input.
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
   * Hide the search bar and clear all highlights.
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
   * Run a case-insensitive search across all message content and highlight matches.
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
        if (idx > lastEnd) parts.push(document.createTextNode(text.slice(lastEnd, idx)));
        const mark = document.createElement('mark');
        mark.textContent = text.slice(idx, idx + query.length);
        parts.push(mark);
        this._searchMatches.push(mark);
        lastEnd = idx + query.length;
        idx = lastEnd;
      }

      if (parts.length > 0) {
        if (lastEnd < text.length) parts.push(document.createTextNode(text.slice(lastEnd)));
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
   * Navigate to the next or previous search match.
   * @param {number} direction - `+1` for next, `-1` for previous.
   */
  navigateSearch(direction) {
    if (this._searchMatches.length === 0) return;
    const prev = this._searchMatches[this._searchIndex];
    if (prev) prev.classList.remove('current');
    this._searchIndex =
      (this._searchIndex + direction + this._searchMatches.length) % this._searchMatches.length;
    this._highlightCurrentMatch();
    this._updateSearchCount();
  }

  /** @private */
  _highlightCurrentMatch() {
    const el = this._searchMatches[this._searchIndex];
    if (!el) return;
    el.classList.add('current');
    el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  /** @private */
  _updateSearchCount() {
    const total = this._searchMatches.length;
    const current = total > 0 ? this._searchIndex + 1 : 0;
    this.searchCountEl.textContent = `${current}/${total}`;
  }

  /** @private */
  _clearSearchHighlights() {
    const marks = this.messagesEl.querySelectorAll('mark');
    marks.forEach((mark) => {
      const parent = mark.parentNode;
      parent.replaceChild(document.createTextNode(mark.textContent), mark);
      parent.normalize();
    });
  }

  // ---------------------------------------------------------------------------
  //  Utilities
  // ---------------------------------------------------------------------------

  /**
   * Format an ISO timestamp for display.
   * @param {string} isoString
   * @returns {string}
   */
  formatTimestamp(isoString) {
    try {
      const d = new Date(isoString);
      return (
        d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) +
        ', ' +
        d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
      );
    } catch {
      return '';
    }
  }

  /**
   * Escape a string for safe insertion into HTML.
   * @param {string} text
   * @returns {string}
   */
  escapeHtml(text) {
    return this._esc(text);
  }

  /** @private */
  _esc(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
  }

  /**
   * Tear down the chat UI and cancel any pending requests.
   */
  destroy() {
    this.cancel();
    this.container.innerHTML = '';
  }
}

// Export — works as a global script or as an ES module
if (typeof window !== 'undefined') {
  window.ChatUI = ChatUI;
}
if (typeof module !== 'undefined' && module.exports) {
  module.exports = ChatUI;
}
