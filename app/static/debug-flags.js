/**
 * Debug Flags - Frontend Module
 * 
 * Provides configurable debug logging with per-feature flags.
 * Flags are synced with the server and persisted to localStorage for quick access.
 * 
 * Usage in other JS files:
 *   <script src="/static/debug-flags.js"></script>
 *   
 *   NotetakerDebug.log('CHAT', 'Message sent:', payload);
 *   if (NotetakerDebug.isEnabled('LLM')) { ... }
 */

(function() {
  'use strict';

  // ============================================================================
  // Flag Definitions (must match backend)
  // ============================================================================

  const FLAG_DEFINITIONS = {
    TRANSCRIPTION: { default: false, desc: 'Live and final transcription' },
    DIARIZATION: { default: false, desc: 'Speaker identification' },
    SUMMARIZATION: { default: false, desc: 'LLM summary generation' },
    CHAT: { default: false, desc: 'Chat queries and RAG' },
    AUDIO: { default: false, desc: 'Audio capture and processing' },
    SSE: { default: false, desc: 'Server-Sent Events' },
    MEETINGS: { default: false, desc: 'Meeting CRUD operations' },
    LLM: { default: false, desc: 'LLM provider calls' },
    API: { default: false, desc: 'API request/response' },
  };

  const STORAGE_KEY = 'notetaker_debug_flags';
  const STORAGE_ENABLED_KEY = 'notetaker_debug_enabled';

  // ============================================================================
  // State
  // ============================================================================

  let debugEnabled = false;
  let flags = {};

  // Initialize flags with defaults
  for (const [key, def] of Object.entries(FLAG_DEFINITIONS)) {
    flags[key] = def.default;
  }

  // ============================================================================
  // LocalStorage persistence
  // ============================================================================

  function loadFromStorage() {
    try {
      const enabledStr = localStorage.getItem(STORAGE_ENABLED_KEY);
      if (enabledStr !== null) {
        debugEnabled = enabledStr === 'true';
      }

      const savedFlags = localStorage.getItem(STORAGE_KEY);
      if (savedFlags) {
        const parsed = JSON.parse(savedFlags);
        for (const [key, value] of Object.entries(parsed)) {
          if (key in flags) {
            flags[key] = !!value;
          }
        }
      }
    } catch (e) {
      console.warn('[DEBUG] Failed to load debug flags from localStorage:', e);
    }
  }

  function saveToStorage() {
    try {
      localStorage.setItem(STORAGE_ENABLED_KEY, debugEnabled ? 'true' : 'false');
      localStorage.setItem(STORAGE_KEY, JSON.stringify(flags));
    } catch (e) {
      console.warn('[DEBUG] Failed to save debug flags to localStorage:', e);
    }
  }

  // ============================================================================
  // Server sync
  // ============================================================================

  async function loadFromServer() {
    try {
      const response = await fetch('/api/settings/debug');
      if (!response.ok) return;
      
      const data = await response.json();
      debugEnabled = !!data.enabled;
      
      if (data.flags) {
        for (const [key, value] of Object.entries(data.flags)) {
          if (key in flags) {
            flags[key] = !!value;
          }
        }
      }
      
      saveToStorage();
    } catch (e) {
      console.warn('[DEBUG] Failed to load debug flags from server:', e);
    }
  }

  async function saveToServer() {
    try {
      const response = await fetch('/api/settings/debug', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled: debugEnabled,
          flags: flags,
        }),
      });
      if (!response.ok) {
        console.warn('[DEBUG] Failed to save debug flags to server:', response.status);
      }
    } catch (e) {
      console.warn('[DEBUG] Failed to save debug flags to server:', e);
    }
  }

  // ============================================================================
  // Public API
  // ============================================================================

  function isEnabled(flag) {
    if (!debugEnabled) return false;
    return !!flags[flag];
  }

  function log(flag, ...args) {
    if (!isEnabled(flag)) return;
    console.log(`[${flag}]`, ...args);
  }

  function warn(flag, ...args) {
    if (!isEnabled(flag)) return;
    console.warn(`[${flag}]`, ...args);
  }

  function error(flag, ...args) {
    if (!isEnabled(flag)) return;
    console.error(`[${flag}]`, ...args);
  }

  function setEnabled(enabled) {
    debugEnabled = !!enabled;
    saveToStorage();
    saveToServer();
  }

  function setFlag(flag, enabled) {
    if (flag in FLAG_DEFINITIONS) {
      flags[flag] = !!enabled;
      saveToStorage();
      saveToServer();
    }
  }

  function setAllFlags(enabled) {
    for (const key of Object.keys(FLAG_DEFINITIONS)) {
      flags[key] = !!enabled;
    }
    saveToStorage();
    saveToServer();
  }

  function getState() {
    return {
      enabled: debugEnabled,
      flags: { ...flags },
    };
  }

  function getDefinitions() {
    return FLAG_DEFINITIONS;
  }

  function syncFromServer(serverState) {
    debugEnabled = !!serverState.enabled;
    if (serverState.flags) {
      for (const [key, value] of Object.entries(serverState.flags)) {
        if (key in flags) {
          flags[key] = !!value;
        }
      }
    }
    saveToStorage();
  }

  // ============================================================================
  // Initialize
  // ============================================================================

  loadFromStorage();

  // ============================================================================
  // Expose global API
  // ============================================================================

  window.NotetakerDebug = {
    isEnabled,
    log,
    warn,
    error,
    setEnabled,
    setFlag,
    setAllFlags,
    getState,
    getDefinitions,
    syncFromServer,
    loadFromServer,
  };

})();
