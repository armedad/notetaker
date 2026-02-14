/**
 * Theme management utility for Notetaker.
 * Handles theme detection, application, and persistence.
 * 
 * This script should be loaded early (before other scripts) to prevent
 * flash of wrong theme on page load.
 */

(function() {
  'use strict';

  const STORAGE_KEY = 'notetaker-theme';
  const VALID_THEMES = ['light', 'dark', 'system'];

  /**
   * Get the current theme preference from localStorage.
   * @returns {string} 'light', 'dark', or 'system'
   */
  function getStoredTheme() {
    const stored = localStorage.getItem(STORAGE_KEY);
    return VALID_THEMES.includes(stored) ? stored : 'system';
  }

  /**
   * Save theme preference to localStorage.
   * @param {string} theme - 'light', 'dark', or 'system'
   */
  function setStoredTheme(theme) {
    if (VALID_THEMES.includes(theme)) {
      localStorage.setItem(STORAGE_KEY, theme);
    }
  }

  /**
   * Detect system color scheme preference.
   * @returns {string} 'dark' or 'light'
   */
  function getSystemTheme() {
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return 'dark';
    }
    return 'light';
  }

  /**
   * Apply theme to the document.
   * @param {string} theme - 'light', 'dark', or 'system'
   */
  function applyTheme(theme) {
    // Set data-theme attribute on html element
    // This is used by CSS to apply the correct variables
    document.documentElement.dataset.theme = theme;
    
    // Also add a class for any JS that needs to detect theme
    document.documentElement.classList.remove('theme-light', 'theme-dark', 'theme-system');
    document.documentElement.classList.add('theme-' + theme);
  }

  /**
   * Get the effective theme (resolves 'system' to actual light/dark).
   * @param {string} theme - 'light', 'dark', or 'system'
   * @returns {string} 'light' or 'dark'
   */
  function getEffectiveTheme(theme) {
    if (theme === 'system') {
      return getSystemTheme();
    }
    return theme;
  }

  /**
   * Initialize theme on page load.
   */
  function initTheme() {
    const theme = getStoredTheme();
    applyTheme(theme);
    
    // Listen for system theme changes (only relevant when theme is 'system')
    if (window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {
        const currentTheme = getStoredTheme();
        if (currentTheme === 'system') {
          // Re-apply to trigger CSS media query update
          applyTheme('system');
        }
      });
    }
  }

  /**
   * Set and apply a new theme.
   * @param {string} theme - 'light', 'dark', or 'system'
   */
  function setTheme(theme) {
    if (!VALID_THEMES.includes(theme)) {
      console.warn('Invalid theme:', theme);
      return;
    }
    setStoredTheme(theme);
    applyTheme(theme);
  }

  /**
   * Sync theme with server settings.
   * Called after API fetch returns theme preference.
   * @param {string} theme - 'light', 'dark', or 'system'
   */
  function syncThemeFromServer(theme) {
    if (VALID_THEMES.includes(theme)) {
      const currentStored = getStoredTheme();
      if (currentStored !== theme) {
        setStoredTheme(theme);
        applyTheme(theme);
      }
    }
  }

  // Apply theme immediately on script load (before DOM ready)
  initTheme();

  // Expose global API for other scripts to use
  window.NotetakerTheme = {
    get: getStoredTheme,
    set: setTheme,
    getEffective: function() {
      return getEffectiveTheme(getStoredTheme());
    },
    syncFromServer: syncThemeFromServer,
    VALID_THEMES: VALID_THEMES
  };
})();
