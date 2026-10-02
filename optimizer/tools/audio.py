"""
Queries active WASAPI audio sessions via COM vtable calls.
Returns an empty frozenset on any failure — non-Windows, COM error, access denied.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes

from optimizer.platform import IS_WINDOWS

_HRESULT     = ctypes.c_long
_S_OK        = 0
_CLSCTX_ALL  = 23
_eRender     = 0   # EDataFlow: output device
_eConsole    = 0   # ERole: default device
# CoInitialize already called with a different apartment model — still usable.
_RPC_E_CHANGED_MODE: int = -2147417850


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(s: str) -> _GUID:
    s = s.strip("{}")
    p = s.split("-")
    g = _GUID()
    g.Data1 = int(p[0], 16)
    g.Data2 = int(p[1], 16)
    g.Data3 = int(p[2], 16)
    tail = bytes.fromhex(p[3] + p[4])
    for i, b in enumerate(tail):
        g.Data4[i] = b
    return g


_CLSID_MMDeviceEnumerator  = _guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
_IID_IMMDeviceEnumerator   = _guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
_IID_IAudioSessionManager2 = _guid("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
_IID_IAudioSessionControl2 = _guid("{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}")


def _vtbl(ptr: int) -> ctypes.Array:
    """Return the vtable function-pointer array for a COM interface pointer."""
    vtable_addr = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    return ctypes.cast(vtable_addr, ctypes.POINTER(ctypes.c_void_p))


def _release(ptr: int) -> None:
    if not ptr:
        return
    # IUnknown::Release is always at vtable index 2.
    fn = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(_vtbl(ptr)[2])
    fn(ptr)


def get_audio_pids() -> frozenset[int]:
    """PIDs of all processes with active WASAPI audio sessions. Empty on any error."""
    if not IS_WINDOWS:
        return frozenset()
    try:
        return _query()
    except Exception:
        return frozenset()


def _query() -> frozenset[int]:
    ole32 = ctypes.windll.ole32
    hr = ole32.CoInitialize(None)
    uninit = hr != _RPC_E_CHANGED_MODE

    enum_ptr = ctypes.c_void_p()
    try:
        hr = ole32.CoCreateInstance(
            ctypes.byref(_CLSID_MMDeviceEnumerator), None, _CLSCTX_ALL,
            ctypes.byref(_IID_IMMDeviceEnumerator), ctypes.byref(enum_ptr),
        )
        if hr != _S_OK or not enum_ptr.value:
            return frozenset()
        return _from_enumerator(enum_ptr.value)
    finally:
        if enum_ptr.value:
            _release(enum_ptr.value)
        if uninit:
            ole32.CoUninitialize()


def _from_enumerator(e: int) -> frozenset[int]:
    # IMMDeviceEnumerator::GetDefaultAudioEndpoint at vtable[4]
    fn = ctypes.WINFUNCTYPE(
        _HRESULT, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
    )(_vtbl(e)[4])
    dev = ctypes.c_void_p()
    if fn(e, _eRender, _eConsole, ctypes.byref(dev)) != _S_OK or not dev.value:
        return frozenset()
    try:
        return _from_device(dev.value)
    finally:
        _release(dev.value)


def _from_device(d: int) -> frozenset[int]:
    # IMMDevice::Activate at vtable[3]
    fn = ctypes.WINFUNCTYPE(
        _HRESULT, ctypes.c_void_p,
        ctypes.POINTER(_GUID), ctypes.c_ulong,
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    )(_vtbl(d)[3])
    mgr = ctypes.c_void_p()
    if fn(d, ctypes.byref(_IID_IAudioSessionManager2), _CLSCTX_ALL, None, ctypes.byref(mgr)) != _S_OK or not mgr.value:
        return frozenset()
    try:
        return _from_manager(mgr.value)
    finally:
        _release(mgr.value)


def _from_manager(m: int) -> frozenset[int]:
    # IAudioSessionManager2::GetSessionEnumerator at vtable[5]
    fn = ctypes.WINFUNCTYPE(
        _HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    )(_vtbl(m)[5])
    se = ctypes.c_void_p()
    if fn(m, ctypes.byref(se)) != _S_OK or not se.value:
        return frozenset()
    try:
        return _from_session_enum(se.value)
    finally:
        _release(se.value)


def _from_session_enum(se: int) -> frozenset[int]:
    v = _vtbl(se)
    # IAudioSessionEnumerator::GetCount at vtable[3]
    count = ctypes.c_int(0)
    fn_count = ctypes.WINFUNCTYPE(_HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))(v[3])
    if fn_count(se, ctypes.byref(count)) != _S_OK:
        return frozenset()

    # IAudioSessionEnumerator::GetSession at vtable[4]
    fn_get = ctypes.WINFUNCTYPE(
        _HRESULT, ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p),
    )(v[4])

    pids: set[int] = set()
    for i in range(count.value):
        ctrl = ctypes.c_void_p()
        if fn_get(se, i, ctypes.byref(ctrl)) != _S_OK or not ctrl.value:
            continue

        # IUnknown::QueryInterface for IAudioSessionControl2, vtable[0]
        ctrl2 = ctypes.c_void_p()
        fn_qi = ctypes.WINFUNCTYPE(
            _HRESULT, ctypes.c_void_p,
            ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p),
        )(_vtbl(ctrl.value)[0])
        hr = fn_qi(ctrl.value, ctypes.byref(_IID_IAudioSessionControl2), ctypes.byref(ctrl2))
        _release(ctrl.value)
        if hr != _S_OK or not ctrl2.value:
            continue

        # IAudioSessionControl2::GetProcessId at vtable[14]
        pid = ctypes.c_ulong(0)
        fn_pid = ctypes.WINFUNCTYPE(
            _HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong),
        )(_vtbl(ctrl2.value)[14])
        if fn_pid(ctrl2.value, ctypes.byref(pid)) == _S_OK and pid.value:
            pids.add(pid.value)
        _release(ctrl2.value)

    return frozenset(pids)
