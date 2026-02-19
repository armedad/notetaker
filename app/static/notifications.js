/**
 * Notification Center - Persistent notification system for Notetaker
 * 
 * Features:
 * - Bell icon with unread count badge
 * - Bubble notifications that appear near the bell
 * - History panel with last 200 notifications
 * - Persists to localStorage across sessions
 * 
 * Usage:
 *   NotificationCenter.init();  // Call once on page load
 *   NotificationCenter.notify("Message", "success");  // success, error, or info
 */

const NotificationCenter = {
  MAX_HISTORY: 200,
  BUBBLE_DURATION: 5000,
  STORAGE_KEY: "notetaker_notifications",
  
  history: [],
  initialized: false,
  
  /**
   * Initialize the notification center. Call once on DOMContentLoaded.
   */
  init() {
    if (this.initialized) return;
    this.initialized = true;
    
    // Load history from localStorage
    try {
      const stored = localStorage.getItem(this.STORAGE_KEY);
      this.history = stored ? JSON.parse(stored) : [];
    } catch (e) {
      console.warn("Failed to load notification history:", e);
      this.history = [];
    }
    
    // Wire up event handlers
    this._wireUpHandlers();
    
    // Initial render
    this._renderBadge();
  },
  
  /**
   * Show a notification.
   * @param {string} message - The notification message
   * @param {string} type - 'success', 'error', or 'info'
   * @param {number} duration - How long to show bubble (ms), 0 to skip bubble
   */
  notify(message, type = "info", duration = null) {
    const notification = {
      id: Date.now() + Math.random().toString(36).substr(2, 9),
      message,
      type,
      timestamp: new Date().toISOString(),
      read: false,
    };
    
    // Add to history (newest first)
    this.history.unshift(notification);
    
    // Limit history size
    if (this.history.length > this.MAX_HISTORY) {
      this.history = this.history.slice(0, this.MAX_HISTORY);
    }
    
    // Save to localStorage
    this._save();
    
    // Show bubble notification
    if (duration !== 0) {
      this._showBubble(notification, duration || this.BUBBLE_DURATION);
    }
    
    // Update badge
    this._renderBadge();
    
    // If panel is open, re-render it
    const panel = document.getElementById("notification-panel");
    if (panel && panel.style.display !== "none") {
      this._renderHistory();
    }
    
    return notification;
  },
  
  /**
   * Show a success notification (green)
   */
  success(message, duration) {
    return this.notify(message, "success", duration);
  },
  
  /**
   * Show an error notification (red)
   */
  error(message, duration) {
    return this.notify(message, "error", duration || 8000);
  },
  
  /**
   * Show an info notification (neutral)
   */
  info(message, duration) {
    return this.notify(message, "info", duration);
  },
  
  /**
   * Mark all notifications as read
   */
  markAllRead() {
    this.history.forEach(n => n.read = true);
    this._save();
    this._renderBadge();
    this._renderHistory();
  },
  
  /**
   * Clear all notification history
   */
  clearHistory() {
    this.history = [];
    this._save();
    this._renderBadge();
    this._renderHistory();
  },
  
  /**
   * Get count of unread notifications
   */
  getUnreadCount() {
    return this.history.filter(n => !n.read).length;
  },
  
  // ---- Private methods ----
  
  _save() {
    try {
      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(this.history));
    } catch (e) {
      console.warn("Failed to save notification history:", e);
    }
  },
  
  _wireUpHandlers() {
    // Toggle button
    const toggleBtn = document.getElementById("notification-toggle");
    if (toggleBtn) {
      toggleBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._togglePanel();
      });
    }
    
    // Mark all read button
    const markAllBtn = document.getElementById("mark-all-read");
    if (markAllBtn) {
      markAllBtn.addEventListener("click", () => this.markAllRead());
    }
    
    // Clear history button
    const clearBtn = document.getElementById("clear-notifications");
    if (clearBtn) {
      clearBtn.addEventListener("click", () => this.clearHistory());
    }
    
    // Close panel when clicking outside
    document.addEventListener("click", (e) => {
      const panel = document.getElementById("notification-panel");
      const toggle = document.getElementById("notification-toggle");
      if (panel && panel.style.display !== "none") {
        if (!panel.contains(e.target) && !toggle?.contains(e.target)) {
          panel.style.display = "none";
        }
      }
    });
  },
  
  _togglePanel() {
    const panel = document.getElementById("notification-panel");
    if (!panel) return;
    
    const isVisible = panel.style.display !== "none";
    if (isVisible) {
      panel.style.display = "none";
    } else {
      panel.style.display = "block";
      this._renderHistory();
    }
  },
  
  _renderBadge() {
    const badge = document.getElementById("notification-badge");
    if (!badge) return;
    
    const unread = this.getUnreadCount();
    if (unread > 0) {
      badge.textContent = unread > 99 ? "99+" : unread;
      badge.style.display = "flex";
    } else {
      badge.style.display = "none";
    }
  },
  
  _renderHistory() {
    const list = document.getElementById("notification-list");
    if (!list) return;
    
    if (this.history.length === 0) {
      list.innerHTML = '<div class="notification-empty">No notifications</div>';
      return;
    }
    
    list.innerHTML = this.history.map(n => {
      const time = this._formatTime(n.timestamp);
      const unreadClass = n.read ? "" : "unread";
      const typeClass = n.type || "info";
      const icon = this._getIcon(n.type);
      
      return `
        <div class="notification-item ${unreadClass} ${typeClass}" data-id="${n.id}">
          <span class="notification-icon">${icon}</span>
          <div class="notification-content">
            <span class="notification-message">${this._escapeHtml(n.message)}</span>
            <span class="notification-time">${time}</span>
          </div>
        </div>
      `;
    }).join("");
    
    // Mark as read when clicked
    list.querySelectorAll(".notification-item").forEach(item => {
      item.addEventListener("click", () => {
        const id = item.dataset.id;
        const notification = this.history.find(n => n.id === id);
        if (notification && !notification.read) {
          notification.read = true;
          this._save();
          this._renderBadge();
          item.classList.remove("unread");
        }
      });
    });
  },
  
  _showBubble(notification, duration) {
    let container = document.getElementById("notification-bubbles");
    if (!container) {
      container = document.createElement("div");
      container.id = "notification-bubbles";
      container.className = "notification-bubbles";
      document.body.appendChild(container);
    }
    
    const bubble = document.createElement("div");
    bubble.className = `notification-bubble ${notification.type}`;
    
    const icon = this._getIcon(notification.type);
    bubble.innerHTML = `
      <span class="bubble-icon">${icon}</span>
      <span class="bubble-message">${this._escapeHtml(notification.message)}</span>
      <button class="bubble-dismiss" title="Dismiss">&times;</button>
    `;
    
    container.appendChild(bubble);
    
    // Dismiss button
    const dismissBtn = bubble.querySelector(".bubble-dismiss");
    dismissBtn.addEventListener("click", () => this._removeBubble(bubble));
    
    // Auto-dismiss
    setTimeout(() => this._removeBubble(bubble), duration);
  },
  
  _removeBubble(bubble) {
    if (!bubble || !bubble.parentNode) return;
    
    bubble.classList.add("bubble-out");
    setTimeout(() => {
      if (bubble.parentNode) {
        bubble.parentNode.removeChild(bubble);
      }
    }, 300);
  },
  
  _getIcon(type) {
    switch (type) {
      case "success": return "✓";
      case "error": return "✕";
      default: return "ℹ";
    }
  },
  
  _formatTime(timestamp) {
    try {
      const date = new Date(timestamp);
      const now = new Date();
      const diffMs = now - date;
      const diffMins = Math.floor(diffMs / 60000);
      const diffHours = Math.floor(diffMs / 3600000);
      const diffDays = Math.floor(diffMs / 86400000);
      
      if (diffMins < 1) return "Just now";
      if (diffMins < 60) return `${diffMins}m ago`;
      if (diffHours < 24) return `${diffHours}h ago`;
      if (diffDays < 7) return `${diffDays}d ago`;
      
      return date.toLocaleDateString();
    } catch (e) {
      return "";
    }
  },
  
  _escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  },
};

// Auto-initialize when DOM is ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => NotificationCenter.init());
} else {
  NotificationCenter.init();
}
