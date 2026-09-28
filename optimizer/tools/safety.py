"""
Protection and identity checks. Read-only — nothing here changes a process.
All action tools call check_protection and verify_identity before acting.
"""
from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

import psutil

from optimizer.models import ProcessRef


# Processes whose termination can cause an immediate BSOD or break the desktop.
_PROTECTED_NAMES: frozenset[str] = frozenset({
    "csrss.exe",
    "lsass.exe",
    "wininit.exe",
    "winlogon.exe",
    "services.exe",
    "smss.exe",
    "svchost.exe",
    "dwm.exe",
    "explorer.exe",
    "fontdrvhost.exe",
    "audiodg.exe",
    "sihost.exe",
    "ctfmon.exe",
    "runtimebroker.exe",
    "memory compression",  # virtual process, no .exe
    "registry",            # virtual process, no .exe
    "msmpeng.exe",
    "securityhealthservice.exe",
    "taskmgr.exe",
    # Ollama inference stack
    "ollama.exe",
    "ollama_llama_server.exe",
    # Kernel virtual PIDs are caught by PID check, but include names too
    "system idle process",
    "system",
    "secure system",
})

# Windows service accounts — processes running as these are managed by SCM.
_SERVICE_ACCOUNTS: frozenset[str] = frozenset({
    "nt authority\\system",
    "nt authority\\local service",
    "nt authority\\network service",
    # Alternate forms without domain prefix that psutil may return
    "local service",
    "network service",
})

# Protected Windows binaries must live under this prefix.
_WINDOWS_ROOT = "c:\\windows\\"

# Cached at module load; optimizer won't change its own PID mid-run.
_OWN_PID: int = os.getpid()
_OWN_PARENT_PID: int | None = None


def _own_parent_pid() -> int | None:
    global _OWN_PARENT_PID
    if _OWN_PARENT_PID is None:
        try:
            _OWN_PARENT_PID = psutil.Process(_OWN_PID).ppid()
        except Exception:
            pass
    return _OWN_PARENT_PID


@runtime_checkable
class ProcessProvider(Protocol):
    """Minimal interface the safety and action layers use to look up a process."""

    def get_process_snapshot(self, pid: int) -> dict | None:
        """Return {pid, create_time, name, exe} or None if the process is gone."""
        ...


def check_protection(name: str, exe: str, username: str, pid: int) -> str | None:
    """Return a human-readable reason this process must never be touched, or None."""
    if pid in (0, 4):
        return f"PID {pid} is a kernel process"

    if pid == _OWN_PID:
        return "Cannot act on the optimizer's own process"

    parent = _own_parent_pid()
    if parent is not None and pid == parent:
        return "Cannot act on the optimizer's parent process"

    if name.lower() in _PROTECTED_NAMES:
        return f"{name!r} is a protected system process"

    if username and username.lower() in _SERVICE_ACCOUNTS:
        return f"Process runs as service account {username!r}"

    return None


def looks_disguised(name: str, exe: str) -> bool:
    """True when a protected Windows name runs from outside C:\\Windows\\."""
    if name.lower() not in _PROTECTED_NAMES:
        return False
    if not exe:
        return False
    # Pure string check — works cross-platform so tests run anywhere.
    return not exe.lower().startswith(_WINDOWS_ROOT)


def verify_identity(ref: ProcessRef, provider: ProcessProvider | None = None) -> str | None:
    """
    Confirm the process at ref.pid is still the same process that was inspected.
    Returns a refusal reason or None. Called immediately before every action.

    Pass a provider to use injected (fake) data in tests; omit to use psutil.
    """
    if provider is not None:
        snap = provider.get_process_snapshot(ref.pid)
        if snap is None:
            return f"Process {ref.pid} no longer exists"
        if snap["create_time"] != ref.create_time:
            return (
                f"PID {ref.pid} has been reused "
                f"(expected create_time {ref.create_time}, got {snap['create_time']})"
            )
        if snap["name"].lower() != ref.name.lower():
            return f"Process name changed: expected {ref.name!r}, got {snap['name']!r}"
        if ref.exe and snap["exe"].lower() != ref.exe.lower():
            return f"Process exe changed: expected {ref.exe!r}, got {snap['exe']!r}"
        return None

    # Real psutil path.
    try:
        proc = psutil.Process(ref.pid)
        with proc.oneshot():
            actual_create_time = proc.create_time()
            if actual_create_time != ref.create_time:
                return (
                    f"PID {ref.pid} has been reused "
                    f"(expected create_time {ref.create_time}, got {actual_create_time})"
                )

            actual_name = proc.name()
            if actual_name.lower() != ref.name.lower():
                return f"Process name changed: expected {ref.name!r}, got {actual_name!r}"

            if ref.exe:
                try:
                    actual_exe = proc.exe()
                    if actual_exe.lower() != ref.exe.lower():
                        return f"Process exe changed: expected {ref.exe!r}, got {actual_exe!r}"
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass  # Can't verify exe path; not a blocking failure.

        return None

    except psutil.NoSuchProcess:
        return f"Process {ref.pid} no longer exists"
    except psutil.AccessDenied:
        return f"Access denied to process {ref.pid}"
