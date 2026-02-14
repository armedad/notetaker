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
    
    this.messages = [];
    this.isLoading = false;
    this.abortController = null;
    
    this.render();
    this.attachEventListeners();
  }
  
  /**
   * Render the chat UI structure.
   */
  render() {
    const clearBtn = this.minimal ? '' : '<button class="chat-clear secondary" type="button" title="Clear chat history">Clear</button>';
    
    if (this.fullscreen) {
      // Fullscreen variant - no header, fills container
      this.container.innerHTML = `
        <div class="chat-panel chat-panel-fullscreen">
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
              <div class="chat-status" id="chat-status-${this.container.id}"></div>
            </div>
          </div>
        </div>
      `;
    } else if (this.minimal) {
      // Minimal variant - no header, no clear/collapse, just chat
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
            <div class="chat-status" id="chat-status-${this.container.id}"></div>
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
              <button class="chat-clear secondary small" type="button" title="Clear chat history">Clear</button>
              <button class="chat-toggle secondary small" type="button">Collapse</button>
            </div>
          </div>
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
            <div class="chat-status" id="chat-status-${this.container.id}"></div>
          </div>
        </div>
      `;
    }
    
    // Cache element references
    this.messagesEl = this.container.querySelector('.chat-messages');
    this.inputEl = this.container.querySelector('.chat-input');
    this.sendBtn = this.container.querySelector('.chat-send');
    this.statusEl = this.container.querySelector('.chat-status');
    this.toggleBtn = this.container.querySelector('.chat-toggle');
    this.clearBtn = this.container.querySelector('.chat-clear');
    this.bodyEl = this.container.querySelector('.chat-body');
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
    
    // Toggle collapse
    this.toggleBtn.addEventListener('click', () => this.toggleCollapse());
    
    // Clear chat
    this.clearBtn.addEventListener('click', () => this.clearMessages());
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
   */
  async sendMessage() {
    const question = this.inputEl.value.trim();
    if (!question || this.isLoading) return;
    
    // Clear input
    this.inputEl.value = '';
    
    // Add user message
    this.addMessage('user', question);
    
    // Start loading
    this.setLoading(true);
    this.setStatus(this.showSearch ? 'Searching meetings...' : 'Thinking...');
    
    // Create abort controller for this request
    this.abortController = new AbortController();
    
    try {
      const payload = this.buildPayload(question);
      
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
      this.setStatus('Generating response...');
      
      // Handle SSE streaming response
      await this.handleStreamingResponse(response);
      
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
   * @returns {HTMLElement|undefined}
   */
  addMessage(role, content, streaming = false) {
    // Remove empty state if present
    const emptyState = this.messagesEl.querySelector('.chat-empty');
    if (emptyState) {
      emptyState.remove();
    }
    
    const messageEl = document.createElement('div');
    messageEl.className = `chat-message chat-message-${role}`;
    messageEl.innerHTML = `
      <div class="chat-message-role">${role === 'user' ? 'You' : 'Assistant'}</div>
      <div class="chat-message-content">${this.escapeHtml(content)}</div>
    `;
    
    this.messagesEl.appendChild(messageEl);
    
    // Store message
    this.messages.push({ role, content });
    
    // Scroll to bottom
    this.scrollToBottom();
    
    if (streaming) {
      return messageEl;
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
   * Set status message.
   * @param {string} message
   */
  setStatus(message) {
    this.statusEl.textContent = message;
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
