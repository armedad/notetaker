"""Curated PortAudio input device list and system-default resolution."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import sounddevice as sd

_logger = logging.getLogger("notetaker.audio")

# Virtual routers — covered by "Use system settings", not shown as separate mics.
_SKIP_NAME_FRAGMENTS = (
    "sound mapper",
    "primary sound capture",
    "primary capture driver",
)

# Prefer WASAPI on Windows; MME/DirectSound duplicates are dropped.
_HOSTAPI_PRIORITY = {
    "wasapi": 4,
    "wdm-ks": 3,
    "directsound": 2,
    "mme": 1,
}

_BTH_FRIENDLY_RE = re.compile(r";\(([^)]*)\)\)?\s*$", re.DOTALL)
_EMPTY_LABEL_RE = re.compile(r"^(?:input|headset|microphone)?\s*\(\s*\)\s*$", re.IGNORECASE)


def _hostapi_name(hostapi_index: int | None, hostapis: list[dict[str, Any]]) -> str:
    if hostapi_index is None:
        return ""
    try:
        return str(hostapis[int(hostapi_index)].get("name", ""))
    except (IndexError, TypeError, ValueError):
        return ""


def _hostapi_priority(hostapi: str) -> int:
    lowered = hostapi.lower()
    for key, priority in _HOSTAPI_PRIORITY.items():
        if key in lowered:
            return priority
    return 0


def _should_skip_name(name: str) -> bool:
    lowered = name.lower()
    return any(fragment in lowered for fragment in _SKIP_NAME_FRAGMENTS)


def _balance_parentheses(name: str) -> str:
    """Close truncated PortAudio labels so dedup keys match WASAPI names."""
    stripped = name.strip()
    missing = stripped.count("(") - stripped.count(")")
    if missing > 0:
        stripped += ")" * missing
    return stripped


def _extract_bth_friendly_name(name: str) -> str | None:
    """Turn WDM-KS bthhfenum resource strings into Headset/Microphone (Device)."""
    compact = name.replace("\r\n", "").replace("\n", "")
    match = _BTH_FRIENDLY_RE.search(compact)
    if not match:
        return None
    device = match.group(1).strip()
    if not device:
        return None
    lowered = compact.lower()
    if "headset" in lowered or "hands-free" in lowered:
        return f"Headset ({device})"
    return f"Microphone ({device})"


def _friendly_label(name: str) -> str:
    """User-facing label: strip host-API tags and resolve Bluetooth resource strings."""
    stripped = name.strip()
    bth = _extract_bth_friendly_name(stripped)
    if bth:
        return bth

    cleaned = re.sub(
        r"\s*\((?:MME|DirectSound|WASAPI|WDM-KS)\)\s*$",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    return _balance_parentheses(cleaned or stripped)


def _display_name(name: str) -> str:
    """Alias kept for callers; same as friendly label."""
    return _friendly_label(name)


def _normalize_key(name: str) -> str:
    return re.sub(r"\s+", " ", _friendly_label(name).lower()).strip()


def _default_input_index() -> int | None:
    default = sd.default.device
    candidate = None
    if hasattr(default, "__getitem__"):
        try:
            candidate = default[0]
        except (IndexError, TypeError):
            candidate = None
    elif hasattr(default, "input"):
        candidate = default.input
    elif isinstance(default, (list, tuple)):
        candidate = default[0]
    else:
        candidate = default
    if candidate is None:
        return None
    try:
        index = int(candidate)
    except (TypeError, ValueError):
        return None
    return index if index >= 0 else None


def resolve_system_input_device_index() -> int:
    """Return PortAudio index for the OS default input device."""
    candidate = _default_input_index()
    if candidate is not None:
        return candidate

    devices = sd.query_devices()
    for idx, device in enumerate(devices):
        name = str(device.get("name", ""))
        if device.get("max_input_channels", 0) > 0 and "sound mapper" in name.lower():
            return idx

    for idx, device in enumerate(devices):
        if device.get("max_input_channels", 0) > 0:
            return idx

    raise RuntimeError("No audio input device available")


def resolve_input_device_index(device_index: int | None) -> int:
    """Resolve None to system default; validate explicit indices."""
    if device_index is None:
        return resolve_system_input_device_index()
    info = sd.query_devices(device_index)
    if int(info.get("max_input_channels", 0)) < 1:
        raise RuntimeError("Selected device has no input channels")
    return int(device_index)


def describe_device(device_index: int) -> dict[str, Any]:
    info = sd.query_devices(device_index)
    name = str(info.get("name", ""))
    return {
        "index": device_index,
        "name": name,
        "display_name": _friendly_label(name),
        "max_input_channels": int(info.get("max_input_channels", 0)),
        "default_samplerate": float(info.get("default_samplerate", 0)),
    }


def _active_capture_names() -> frozenset[str]:
    if sys.platform != "win32":
        return frozenset()
    from app.services.windows_audio_endpoints import active_capture_endpoint_names

    return active_capture_endpoint_names()


def _matches_active_endpoint(label: str, active_names: frozenset[str]) -> bool:
    if not active_names:
        return True

    balanced = _balance_parentheses(label)
    candidates = {label, balanced, _friendly_label(label)}
    for candidate in candidates:
        if candidate in active_names:
            return True

    key = _normalize_key(label)
    for active in active_names:
        if _normalize_key(active) == key:
            return True
        active_key = _normalize_key(active)
        if key and (active_key.startswith(key) or key.startswith(active_key)):
            return True
    return False


def _should_skip_inactive(label: str, active_names: frozenset[str]) -> bool:
    if not active_names:
        return False
    return not _matches_active_endpoint(label, active_names)


def _is_nameless_endpoint(label: str) -> bool:
    return bool(_EMPTY_LABEL_RE.match(label.strip()))


def _format_device_line(
    *,
    index: int | None = None,
    display_name: str,
    portaudio_name: str | None = None,
    hostapi: str = "",
    channels: int | None = None,
    note: str = "",
) -> str:
    parts = []
    if index is not None:
        parts.append(f"index={index}")
    parts.append(f"label={display_name!r}")
    if portaudio_name and portaudio_name != display_name:
        parts.append(f"portaudio={portaudio_name!r}")
    if hostapi:
        parts.append(f"hostapi={hostapi}")
    if channels is not None:
        parts.append(f"channels={channels}")
    if note:
        parts.append(note)
    return "  " + " ".join(parts)


def log_dropdown_devices(
    devices: list[dict[str, Any]],
    *,
    system_default: dict[str, Any] | None = None,
) -> None:
    """Log the device list as presented in Settings (plus system-default hint)."""
    if not _logger.isEnabledFor(logging.DEBUG):
        return

    lines = ["Settings input dropdown:"]
    lines.append(_format_device_line(display_name="Use system settings", note="UI-only first option"))
    if system_default:
        lines.append(
            _format_device_line(
                index=system_default.get("index"),
                display_name=str(system_default.get("display_name", "")),
                portaudio_name=str(system_default.get("name", "")),
                channels=system_default.get("max_input_channels"),
                note="resolved OS default (hint text when system option selected)",
            )
        )
    else:
        lines.append("  (system default unavailable)")

    if not devices:
        lines.append("  (no curated input devices)")
    else:
        for device in devices:
            lines.append(
                _format_device_line(
                    index=device.get("index"),
                    display_name=str(device.get("display_name", "")),
                    portaudio_name=str(device.get("name", "")),
                    hostapi=str(device.get("hostapi", "")),
                    channels=device.get("max_input_channels"),
                )
            )

    _logger.debug("\n".join(lines))


def list_input_devices() -> list[dict[str, Any]]:
    """Return deduplicated input devices (one entry per physical/virtual source)."""
    hostapis = sd.query_hostapis()
    candidates: list[dict[str, Any]] = []
    skipped_virtual: list[str] = []
    skipped_inactive: list[str] = []
    skipped_nameless: list[str] = []
    dropped_duplicates: list[str] = []

    active_names = _active_capture_names()
    all_devices = sd.query_devices()
    for idx, device in enumerate(all_devices):
        max_in = int(device.get("max_input_channels", 0))
        name = str(device.get("name", ""))
        if max_in < 1:
            continue
        if _should_skip_name(name):
            skipped_virtual.append(
                _format_device_line(
                    index=idx,
                    display_name=_friendly_label(name),
                    portaudio_name=name,
                    note="hidden (virtual router)",
                )
            )
            continue

        label = _friendly_label(name)
        if _is_nameless_endpoint(label):
            skipped_nameless.append(
                _format_device_line(index=idx, display_name=label, portaudio_name=name, note="hidden (no device name)")
            )
            continue
        if _should_skip_inactive(label, active_names):
            skipped_inactive.append(
                _format_device_line(
                    index=idx,
                    display_name=label,
                    portaudio_name=name,
                    hostapi=_hostapi_name(device.get("hostapi"), hostapis),
                    note="hidden (not an active Windows capture endpoint)",
                )
            )
            continue

        ha_name = _hostapi_name(device.get("hostapi"), hostapis)
        if active_names and "wasapi" not in ha_name.lower():
            continue

        candidates.append(
            {
                "index": idx,
                "name": name,
                "display_name": label,
                "max_input_channels": max_in,
                "default_samplerate": float(device.get("default_samplerate", 0)),
                "hostapi": ha_name,
                "_priority": _hostapi_priority(ha_name),
                "_key": _normalize_key(name),
            }
        )

    best_by_key: dict[str, dict[str, Any]] = {}
    for item in candidates:
        key = item["_key"]
        existing = best_by_key.get(key)
        if existing is None:
            best_by_key[key] = item
            continue
        if item["_priority"] > existing["_priority"]:
            dropped_duplicates.append(
                _format_device_line(
                    index=existing["index"],
                    display_name=existing["display_name"],
                    portaudio_name=existing["name"],
                    hostapi=existing["hostapi"],
                    channels=existing["max_input_channels"],
                    note=f"dropped (kept index={item['index']} {item['hostapi']})",
                )
            )
            best_by_key[key] = item
        else:
            dropped_duplicates.append(
                _format_device_line(
                    index=item["index"],
                    display_name=item["display_name"],
                    portaudio_name=item["name"],
                    hostapi=item["hostapi"],
                    channels=item["max_input_channels"],
                    note=f"dropped (kept index={existing['index']} {existing['hostapi']})",
                )
            )

    result = sorted(
        best_by_key.values(),
        key=lambda d: d["display_name"].lower(),
    )
    for item in result:
        item.pop("_priority", None)
        item.pop("_key", None)

    if _logger.isEnabledFor(logging.DEBUG):
        raw_input_count = sum(
            1 for d in all_devices if int(d.get("max_input_channels", 0)) > 0
        )
        audit = [
            f"Audio device curation: {raw_input_count} PortAudio input(s), "
            f"{len(skipped_virtual)} hidden virtual router(s), "
            f"{len(skipped_inactive)} inactive/disconnected, "
            f"{len(skipped_nameless)} nameless, "
            f"{len(dropped_duplicates)} duplicate(s) dropped, "
            f"{len(result)} in dropdown",
        ]
        if active_names:
            audit.append(f"Windows active capture endpoints: {sorted(active_names)}")
        if skipped_virtual:
            audit.append("Hidden from dropdown (use 'Use system settings' instead):")
            audit.extend(skipped_virtual)
        if skipped_inactive:
            audit.append("Hidden inactive or disconnected endpoints:")
            audit.extend(skipped_inactive)
        if skipped_nameless:
            audit.append("Hidden nameless endpoints:")
            audit.extend(skipped_nameless)
        if dropped_duplicates:
            audit.append("Dropped duplicates (same label, lower-priority host API):")
            audit.extend(dropped_duplicates)
        _logger.debug("\n".join(audit))

    return result
