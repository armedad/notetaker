"""
Debug Flags System - Backend Module

Provides configurable debug logging with per-feature flags.
Flags are persisted to config.json and can be toggled via the Settings UI.

Usage:
    from app.services.debug import debug_log, is_debug_enabled, DEBUG
    
    debug_log('TRANSCRIPTION', 'Processing audio chunk: %d bytes', len(chunk))
    
    if is_debug_enabled('LLM'):
        # expensive debug operation
        ...

License: MIT
"""

import json
import logging
import os
from typing import Any, Optional

# ============================================================================
# Flag Definitions
# ============================================================================

FLAG_DEFINITIONS = {
    'TRANSCRIPTION': {'default': False, 'desc': 'Live and final transcription'},
    'DIARIZATION': {'default': False, 'desc': 'Speaker identification'},
    'SUMMARIZATION': {'default': False, 'desc': 'LLM summary generation'},
    'CHAT': {'default': False, 'desc': 'Chat queries and RAG'},
    'AUDIO': {'default': False, 'desc': 'Audio capture and processing'},
    'SSE': {'default': False, 'desc': 'Server-Sent Events'},
    'MEETINGS': {'default': False, 'desc': 'Meeting CRUD operations'},
    'LLM': {'default': False, 'desc': 'LLM provider calls'},
    'API': {'default': False, 'desc': 'API request/response'},
}

# Master switch - when False, all debug logging is disabled regardless of individual flags
DEBUG_ENABLED = False

# Current flag states
DEBUG = {flag: defn['default'] for flag, defn in FLAG_DEFINITIONS.items()}

# ============================================================================
# Config file path
# ============================================================================

def _get_config_path() -> str:
    """Get the path to config.json in the current working directory."""
    return os.path.join(os.getcwd(), 'config.json')

# ============================================================================
# Load/Save from config.json
# ============================================================================

def load_debug_flags() -> None:
    """Load debug flags from config.json."""
    global DEBUG_ENABLED, DEBUG
    
    config_path = _get_config_path()
    if not os.path.exists(config_path):
        return
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        debug_config = config.get('debug', {})
        DEBUG_ENABLED = debug_config.get('enabled', False)
        
        flags = debug_config.get('flags', {})
        for flag in FLAG_DEFINITIONS:
            if flag in flags:
                DEBUG[flag] = bool(flags[flag])
    except Exception as e:
        logging.getLogger('notetaker.debug').warning('Failed to load debug flags: %s', e)


def save_debug_flags() -> None:
    """Save debug flags to config.json."""
    config_path = _get_config_path()
    
    # Load existing config or start fresh
    config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception:
            pass
    
    # Update debug section
    config['debug'] = {
        'enabled': DEBUG_ENABLED,
        'flags': dict(DEBUG),
    }
    
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        logging.getLogger('notetaker.debug').warning('Failed to save debug flags: %s', e)


def set_debug_enabled(enabled: bool) -> None:
    """Set the master debug switch."""
    global DEBUG_ENABLED
    DEBUG_ENABLED = enabled
    save_debug_flags()


def set_debug_flag(flag: str, enabled: bool) -> None:
    """Set a specific debug flag."""
    if flag in FLAG_DEFINITIONS:
        DEBUG[flag] = enabled
        save_debug_flags()


def set_all_debug_flags(enabled: bool) -> None:
    """Set all debug flags to the same value."""
    for flag in FLAG_DEFINITIONS:
        DEBUG[flag] = enabled
    save_debug_flags()


def get_debug_state() -> dict:
    """Get the current debug state for API responses."""
    return {
        'enabled': DEBUG_ENABLED,
        'flags': dict(DEBUG),
        'definitions': {
            flag: {'default': defn['default'], 'desc': defn['desc']}
            for flag, defn in FLAG_DEFINITIONS.items()
        },
    }

# ============================================================================
# Logger setup
# ============================================================================

_logger = logging.getLogger('notetaker.debug')

# ============================================================================
# Public API
# ============================================================================

def is_debug_enabled(flag: str) -> bool:
    """
    Check if a feature flag is enabled.
    Returns False if master switch is off or flag doesn't exist.
    """
    if not DEBUG_ENABLED:
        return False
    return DEBUG.get(flag, False)


def debug_log(flag: str, message: str, *args: Any, **kwargs: Any) -> None:
    """
    Log a message if the feature flag is enabled.
    
    Args:
        flag: Feature flag name (e.g., 'TRANSCRIPTION', 'LLM')
        message: Log message (can include % formatting)
        *args: Format arguments for message
    
    Example:
        debug_log('TRANSCRIPTION', 'Processing chunk: %d bytes', chunk_size)
        debug_log('LLM', 'Request to %s: %s', provider, model)
    """
    if not DEBUG_ENABLED or not DEBUG.get(flag, False):
        return
    
    formatted = f'[{flag}] {message}'
    if args:
        try:
            formatted = formatted % args
        except Exception:
            formatted = f'{formatted} {args}'
    
    _logger.info(formatted)


def debug_warn(flag: str, message: str, *args: Any) -> None:
    """Log a warning if the feature flag is enabled."""
    if not DEBUG_ENABLED or not DEBUG.get(flag, False):
        return
    
    formatted = f'[{flag}] {message}'
    if args:
        try:
            formatted = formatted % args
        except Exception:
            formatted = f'{formatted} {args}'
    
    _logger.warning(formatted)


def debug_error(flag: str, message: str, *args: Any) -> None:
    """Log an error if the feature flag is enabled."""
    if not DEBUG_ENABLED or not DEBUG.get(flag, False):
        return
    
    formatted = f'[{flag}] {message}'
    if args:
        try:
            formatted = formatted % args
        except Exception:
            formatted = f'{formatted} {args}'
    
    _logger.error(formatted)


# ============================================================================
# Initialize on import
# ============================================================================

load_debug_flags()
