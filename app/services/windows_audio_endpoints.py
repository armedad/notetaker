"""Windows Core Audio active capture endpoints (ctypes, no extra deps)."""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import (
    POINTER,
    Structure,
    Union,
    WINFUNCTYPE,
    byref,
    c_int,
    c_uint,
    c_ushort,
    c_void_p,
    c_wchar_p,
)
from ctypes.wintypes import BYTE, DWORD, WORD
from functools import lru_cache

_logger = logging.getLogger("notetaker.audio")

CLSCTX_ALL = 0x17
COINIT_APARTMENTTHREADED = 0x2
EDataFlow_eCapture = 1
DEVICE_STATE_ACTIVE = 0x1
STGM_READ = 0

CLSID_MMDeviceEnumerator = (
    0x95,
    0x03,
    0xDE,
    0xBC,
    0x2F,
    0xE5,
    0x7C,
    0x46,
    0x8E,
    0x3D,
    0xC4,
    0x57,
    0x92,
    0x91,
    0x69,
    0x2E,
)
IID_IMMDeviceEnumerator = (
    0xD2,
    0x64,
    0x56,
    0xA9,
    0x14,
    0x96,
    0x35,
    0x4F,
    0xA7,
    0x46,
    0xDE,
    0x8D,
    0xB6,
    0x36,
    0x17,
    0xE6,
)


class GUID(Structure):
    _fields_ = [
        ("Data1", DWORD),
        ("Data2", WORD),
        ("Data3", WORD),
        ("Data4", BYTE * 8),
    ]


class PROPERTYKEY(Structure):
    _fields_ = [("fmtid", GUID), ("pid", DWORD)]


PKEY_Device_FriendlyName = PROPERTYKEY(
    GUID(
        0xA45C254E,
        0xDF1C,
        0x4EFD,
        (BYTE * 8)(0x80, 0x20, 0x67, 0xD1, 0x46, 0xA8, 0x50, 0xE0),
    ),
    14,
)


class _PropVariantUnion(Union):
    _fields_ = [("pwszVal", c_wchar_p), ("blob", BYTE * 16)]


class PROPVARIANT(Structure):
    _anonymous_ = ("value",)
    _fields_ = [
        ("vt", c_ushort),
        ("wReserved1", c_ushort),
        ("wReserved2", c_ushort),
        ("wReserved3", c_ushort),
        ("value", _PropVariantUnion),
    ]


VT_LPWSTR = 31
HRESULT = c_int
ole32 = ctypes.OleDLL("ole32")
ole32.CoInitializeEx.argtypes = [c_void_p, DWORD]
ole32.CoInitializeEx.restype = HRESULT
ole32.CoCreateInstance.argtypes = [POINTER(GUID), c_void_p, DWORD, POINTER(GUID), POINTER(c_void_p)]
ole32.CoCreateInstance.restype = HRESULT

_com_initialized = False


def _ensure_com() -> None:
    global _com_initialized
    if _com_initialized:
        return
    hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    if hr not in (0, 1):
        raise OSError(f"CoInitializeEx failed: {hr:#x}")
    _com_initialized = True


def _guid_from_bytes(data: tuple[int, ...]) -> GUID:
    return GUID.from_buffer_copy(bytes(data))


def _vtbl_method(interface: c_void_p, index: int, restype, argtypes):
    vtable = ctypes.cast(interface, POINTER(c_void_p)).contents
    fn_addr = ctypes.cast(vtable, POINTER(c_void_p))[index]
    prototype = WINFUNCTYPE(restype, c_void_p, *argtypes)
    return prototype(fn_addr)


def _active_capture_friendly_names() -> set[str]:
    _ensure_com()
    enumerator = c_void_p()
    hr = ole32.CoCreateInstance(
        byref(_guid_from_bytes(CLSID_MMDeviceEnumerator)),
        None,
        CLSCTX_ALL,
        byref(_guid_from_bytes(IID_IMMDeviceEnumerator)),
        byref(enumerator),
    )
    if hr:
        raise OSError(f"CoCreateInstance(MMDeviceEnumerator) failed: {hr:#x}")

    collection = c_void_p()
    enum_endpoints = _vtbl_method(enumerator, 3, HRESULT, [c_int, c_uint, POINTER(c_void_p)])
    hr = enum_endpoints(enumerator, EDataFlow_eCapture, DEVICE_STATE_ACTIVE, byref(collection))
    if hr:
        raise OSError(f"EnumAudioEndpoints failed: {hr:#x}")

    get_count = _vtbl_method(collection, 3, HRESULT, [POINTER(c_uint)])
    item = _vtbl_method(collection, 4, HRESULT, [c_uint, POINTER(c_void_p)])

    count = c_uint()
    hr = get_count(collection, byref(count))
    if hr:
        raise OSError(f"IMMDeviceCollection.GetCount failed: {hr:#x}")

    names: set[str] = set()
    for idx in range(count.value):
        endpoint = c_void_p()
        hr = item(collection, idx, byref(endpoint))
        if hr:
            _logger.debug("IMMDeviceCollection.Item(%s) failed: %s", idx, hr)
            continue

        store = c_void_p()
        open_store = _vtbl_method(endpoint, 4, HRESULT, [c_uint, POINTER(c_void_p)])
        hr = open_store(endpoint, STGM_READ, byref(store))
        if hr:
            _logger.debug("OpenPropertyStore failed for endpoint %s: %s", idx, hr)
            continue

        prop = PROPVARIANT()
        get_value = _vtbl_method(store, 5, HRESULT, [POINTER(PROPERTYKEY), POINTER(PROPVARIANT)])
        hr = get_value(store, byref(PKEY_Device_FriendlyName), byref(prop))
        if hr or prop.vt != VT_LPWSTR or not prop.pwszVal:
            _logger.debug("GetValue(FriendlyName) failed for endpoint %s: %s", idx, hr)
            continue
        names.add(prop.pwszVal.strip())

    return names


@lru_cache(maxsize=1)
def active_capture_endpoint_names() -> frozenset[str]:
    """Friendly names of Windows capture endpoints in DEVICE_STATE_ACTIVE."""
    if sys.platform != "win32":
        return frozenset()
    try:
        names = frozenset(_active_capture_friendly_names())
        _logger.debug("Windows active capture endpoints: %s", sorted(names))
        return names
    except Exception as exc:
        _logger.debug("Active capture endpoint query failed: %s", exc)
        return frozenset()


def clear_active_capture_cache() -> None:
    active_capture_endpoint_names.cache_clear()
