"""
get_foreground_pid(), get_process_windows(), is_hung(), has_windowed_ancestor() — read-only window queries.
All return None/empty/{}/False on non-Windows.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes

import psutil

from optimizer.platform import IS_WINDOWS, user32

_GW_OWNER = 4

if IS_WINDOWS and user32 is not None:
    # GetForegroundWindow() -> HWND
    user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
    user32.GetForegroundWindow.argtypes = []

    # GetWindowThreadProcessId(hWnd, lpdwProcessId) -> thread_id
    user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.POINTER(ctypes.wintypes.DWORD),
    ]

    # EnumWindows(lpEnumFunc, lParam) -> BOOL
    _WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.wintypes.HWND,
        ctypes.wintypes.LPARAM,
    )
    user32.EnumWindows.restype = ctypes.wintypes.BOOL
    user32.EnumWindows.argtypes = [_WNDENUMPROC, ctypes.wintypes.LPARAM]

    # IsWindowVisible(hWnd) -> BOOL
    user32.IsWindowVisible.restype = ctypes.wintypes.BOOL
    user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]

    # GetWindowTextLengthW(hWnd) -> int
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextLengthW.argtypes = [ctypes.wintypes.HWND]

    # GetWindow(hWnd, uCmd) -> HWND
    user32.GetWindow.restype = ctypes.wintypes.HWND
    user32.GetWindow.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.UINT]

    # IsHungAppWindow(hWnd) -> BOOL
    user32.IsHungAppWindow.restype = ctypes.wintypes.BOOL
    user32.IsHungAppWindow.argtypes = [ctypes.wintypes.HWND]


def get_foreground_pid() -> int | None:
    """PID of the process that owns the foreground window, or None."""
    if not IS_WINDOWS or user32 is None:
        return None
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = ctypes.wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value if pid.value else None


def get_process_windows() -> dict[int, list[int]]:
    """
    Map of pid → list of visible, titled, top-level (unowned) window handles.
    These are the windows that appear on the taskbar and may hold unsaved work.
    """
    if not IS_WINDOWS or user32 is None:
        return {}

    result: dict[int, list[int]] = {}

    def _callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindowTextLengthW(hwnd) <= 0:
            return True
        if user32.GetWindow(hwnd, _GW_OWNER) != 0:
            return True
        pid = ctypes.wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value:
            result.setdefault(pid.value, []).append(hwnd)
        return True

    user32.EnumWindows(_WNDENUMPROC(_callback), 0)
    return result


def is_hung(pid: int) -> bool:
    """True if any top-level window of the process is not responding."""
    if not IS_WINDOWS or user32 is None:
        return False
    windows = get_process_windows()
    return any(user32.IsHungAppWindow(hwnd) for hwnd in windows.get(pid, []))


def has_windowed_ancestor(pid: int, max_depth: int = 3) -> bool:
    """
    True if any ancestor process (up to max_depth levels up) owns a visible window.
    Protects compiler/subprocess children of IDEs and other windowed parents.
    Returns False on non-Windows or any access error.
    """
    if not IS_WINDOWS or user32 is None:
        return False
    windowed = get_process_windows()
    try:
        proc = psutil.Process(pid)
        for _ in range(max_depth):
            ppid = proc.ppid()
            if ppid in (0, 4):
                break
            if ppid in windowed:
                return True
            proc = psutil.Process(ppid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False
