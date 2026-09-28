"""
get_startup_executables() and get_service_pids() — read-only, cached.
"""
from __future__ import annotations

import shlex
import time
from pathlib import Path

import psutil

from optimizer.platform import IS_WINDOWS

_RUN_KEYS = [
    # (hive_constant_name, subkey)
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\Run"),
    ("HKLM", r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
]

_STARTUP_TTL = 600.0   # 10 minutes
_SERVICE_TTL = 300.0   # 5 minutes

_startup_cache: tuple[set[str], float] | None = None
_service_cache: tuple[set[int], float] | None = None


def _parse_exe_name(cmdline: str) -> str | None:
    """Extract the lower-case exe filename from a registry Run value string."""
    cmdline = cmdline.strip()
    if not cmdline:
        return None
    try:
        parts = shlex.split(cmdline, posix=False)
        exe = parts[0].strip('"\'') if parts else cmdline
    except ValueError:
        exe = cmdline.split()[0].strip('"\'')
    name = Path(exe).name
    return name.lower() if name else None


def get_startup_executables() -> set[str]:
    """
    Lower-case exe names from the three standard Run registry keys.
    Returns an empty set on non-Windows. Cached for ~10 minutes.
    """
    global _startup_cache
    now = time.monotonic()
    if _startup_cache is not None and now < _startup_cache[1]:
        return _startup_cache[0]

    names: set[str] = set()

    if IS_WINDOWS:
        import winreg
        hive_map = {
            "HKCU": winreg.HKEY_CURRENT_USER,
            "HKLM": winreg.HKEY_LOCAL_MACHINE,
        }
        for hive_key, subkey in _RUN_KEYS:
            try:
                with winreg.OpenKey(hive_map[hive_key], subkey) as key:
                    i = 0
                    while True:
                        try:
                            _, value, _ = winreg.EnumValue(key, i)
                            name = _parse_exe_name(str(value))
                            if name:
                                names.add(name)
                            i += 1
                        except OSError:
                            break
            except OSError:
                continue

    _startup_cache = (names, now + _STARTUP_TTL)
    return names


def get_service_pids() -> set[int]:
    """
    PIDs of all running Windows services.
    Returns an empty set on non-Windows. Cached for ~5 minutes.
    """
    global _service_cache
    now = time.monotonic()
    if _service_cache is not None and now < _service_cache[1]:
        return _service_cache[0]

    pids: set[int] = set()

    if IS_WINDOWS:
        try:
            for svc in psutil.win_service_iter():
                try:
                    pid = svc.pid()
                    if pid:
                        pids.add(pid)
                except Exception:
                    continue
        except AttributeError:
            pass  # psutil on non-Windows won't have win_service_iter

    _service_cache = (pids, now + _SERVICE_TTL)
    return pids
