import sys
import ctypes

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    kernel32: ctypes.WinDLL = ctypes.WinDLL("kernel32", use_last_error=True)
    user32: ctypes.WinDLL = ctypes.WinDLL("user32", use_last_error=True)
    psapi: ctypes.WinDLL = ctypes.WinDLL("psapi", use_last_error=True)
    pdh: ctypes.WinDLL = ctypes.WinDLL("pdh", use_last_error=True)
else:
    kernel32 = None  # type: ignore[assignment]
    user32 = None    # type: ignore[assignment]
    psapi = None     # type: ignore[assignment]
    pdh = None       # type: ignore[assignment]
