"""
Action tools — the ONLY module that changes process state.
Every function runs safety checks itself before acting, regardless of what
the caller already checked.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes

import psutil

from optimizer import journal
from optimizer.models import ProcessRef, ToolResult
from optimizer.platform import IS_WINDOWS, kernel32, user32
from optimizer.tools.safety import check_protection, verify_identity
from optimizer.tools.windows import get_process_windows

# ── Windows constants ──────────────────────────────────────────────────────────

_BELOW_NORMAL  = getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", 10)
_IDLE          = getattr(psutil, "IDLE_PRIORITY_CLASS", 19)
_NORMAL        = getattr(psutil, "NORMAL_PRIORITY_CLASS", 32)
_WM_CLOSE      = 0x0010
_OPEN_FLAGS    = 0x0200 | 0x1000   # PROCESS_SET_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION
_PPTL_CLASS    = 4                  # ProcessPowerThrottling info class
_PPTL_SPEED    = 0x1                # PROCESS_POWER_THROTTLING_EXECUTION_SPEED


class _ProcessPowerThrottlingState(ctypes.Structure):
    _fields_ = [
        ("Version",     ctypes.c_ulong),
        ("ControlMask", ctypes.c_ulong),
        ("StateMask",   ctypes.c_ulong),
    ]


if IS_WINDOWS and kernel32 is not None:
    kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [
        ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD,
    ]
    kernel32.SetProcessInformation.restype = ctypes.wintypes.BOOL
    kernel32.SetProcessInformation.argtypes = [
        ctypes.wintypes.HANDLE, ctypes.c_int,
        ctypes.c_void_p, ctypes.wintypes.DWORD,
    ]
    kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
    kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]

if IS_WINDOWS and user32 is not None:
    user32.PostMessageW.restype  = ctypes.wintypes.BOOL
    user32.PostMessageW.argtypes = [
        ctypes.wintypes.HWND, ctypes.wintypes.UINT,
        ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
    ]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _username(ref: ProcessRef, provider) -> str:
    if provider is not None:
        snap = provider.get_process_snapshot(ref.pid)
        return (snap or {}).get("username", "")
    try:
        return psutil.Process(ref.pid).username()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""


def _safety(ref: ProcessRef, provider) -> str | None:
    reason = check_protection(ref.name, ref.exe, _username(ref, provider), ref.pid)
    if reason:
        return reason
    return verify_identity(ref, provider=provider)


def _get_priority(pid: int, provider) -> int:
    if provider is not None:
        return provider.get_priority(pid) or _NORMAL
    try:
        return int(psutil.Process(pid).nice()) or _NORMAL
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return _NORMAL


def _set_priority(pid: int, priority: int, provider) -> None:
    if provider is not None:
        provider.set_priority(pid, priority)
    else:
        psutil.Process(pid).nice(priority)


def _eco_qos(pid: int, on: bool) -> str | None:
    """Apply or clear EcoQoS via SetProcessInformation. Returns an error string or None."""
    if not IS_WINDOWS or kernel32 is None:
        return "EcoQoS requires Windows"
    handle = kernel32.OpenProcess(_OPEN_FLAGS, False, pid)
    if not handle:
        return f"OpenProcess failed (error {ctypes.get_last_error()})"
    try:
        state = _ProcessPowerThrottlingState()
        state.Version = 1
        if on:
            state.ControlMask = _PPTL_SPEED
            state.StateMask   = _PPTL_SPEED
        else:
            state.ControlMask = 0
            state.StateMask   = 0
        ok = kernel32.SetProcessInformation(
            handle, _PPTL_CLASS, ctypes.byref(state), ctypes.sizeof(state)
        )
        return None if ok else f"SetProcessInformation failed (error {ctypes.get_last_error()})"
    finally:
        kernel32.CloseHandle(handle)


# ── Action tools ──────────────────────────────────────────────────────────────

def lower_priority(
    ref: ProcessRef, *, dry_run: bool = False, provider=None
) -> ToolResult:
    """Set priority to Below Normal. Frees CPU for active apps; process keeps running."""
    if reason := _safety(ref, provider):
        return ToolResult(ok=False, reason=reason)

    old = _get_priority(ref.pid, provider)
    undo = {"fn": "restore_priority", "priority": old}

    if dry_run:
        journal.record(ref, "lower_priority", "dry_run", undo)
        return ToolResult(ok=True, reason="dry run", undo=undo)

    entry_id = journal.record(ref, "lower_priority", "pending", undo)
    try:
        _set_priority(ref.pid, _BELOW_NORMAL, provider)
        journal.update_status(entry_id, "active")
        return ToolResult(ok=True, undo=undo)
    except (psutil.NoSuchProcess, psutil.AccessDenied, PermissionError) as exc:
        journal.update_status(entry_id, "failed")
        return ToolResult(ok=False, reason=str(exc))


def set_efficiency_mode(
    ref: ProcessRef, *, on: bool = True, dry_run: bool = False, provider=None
) -> ToolResult:
    """
    Enable or disable Task Manager Efficiency Mode (Idle priority + EcoQoS).
    When on=True, saves old priority so it can be restored on undo.
    """
    if reason := _safety(ref, provider):
        return ToolResult(ok=False, reason=reason)

    old_priority = _get_priority(ref.pid, provider)
    undo = {"fn": "restore_efficiency_mode", "priority": old_priority}

    if dry_run:
        journal.record(ref, "set_efficiency_mode", "dry_run", undo)
        return ToolResult(ok=True, reason="dry run", undo=undo)

    entry_id = journal.record(ref, "set_efficiency_mode", "pending", undo)
    try:
        if on:
            _set_priority(ref.pid, _IDLE, provider)
        # else: priority is restored by restore_efficiency_mode during undo

        if provider is not None:
            provider.set_efficiency_mode(ref.pid, on)
        else:
            if err := _eco_qos(ref.pid, on):
                journal.update_status(entry_id, "failed")
                return ToolResult(ok=False, reason=err)

        journal.update_status(entry_id, "active" if on else "done")
        return ToolResult(ok=True, undo=undo if on else {})
    except (psutil.NoSuchProcess, psutil.AccessDenied, PermissionError) as exc:
        journal.update_status(entry_id, "failed")
        return ToolResult(ok=False, reason=str(exc))


def suspend(
    ref: ProcessRef,
    *,
    expires_at: float | None = None,
    dry_run: bool = False,
    provider=None,
) -> ToolResult:
    """Suspend the process, halting CPU use without freeing memory."""
    if reason := _safety(ref, provider):
        return ToolResult(ok=False, reason=reason)

    undo = {"fn": "resume"}

    if dry_run:
        journal.record(ref, "suspend", "dry_run", undo)
        return ToolResult(ok=True, reason="dry run", undo=undo)

    entry_id = journal.record(ref, "suspend", "pending", undo, expires_at=expires_at)
    try:
        if provider is not None:
            provider.suspend(ref.pid)
        else:
            psutil.Process(ref.pid).suspend()
        journal.update_status(entry_id, "active")
        return ToolResult(ok=True, undo=undo)
    except (psutil.NoSuchProcess, psutil.AccessDenied, PermissionError) as exc:
        journal.update_status(entry_id, "failed")
        return ToolResult(ok=False, reason=str(exc))


def close_gracefully(
    ref: ProcessRef, *, dry_run: bool = False, provider=None
) -> ToolResult:
    """Post WM_CLOSE to each top-level window — like clicking X. Not reversible."""
    if reason := _safety(ref, provider):
        return ToolResult(ok=False, reason=reason)

    if provider is not None:
        hwnds = provider.get_windows(ref.pid)
    else:
        hwnds = get_process_windows().get(ref.pid, [])

    if not hwnds:
        return ToolResult(ok=False, reason="Process has no top-level windows to close")

    if dry_run:
        journal.record(ref, "close_gracefully", "dry_run", {})
        return ToolResult(ok=True, reason="dry run")

    entry_id = journal.record(ref, "close_gracefully", "pending", {})
    try:
        if provider is not None:
            provider.post_wm_close(ref.pid)
        else:
            if not IS_WINDOWS or user32 is None:
                raise OSError("close_gracefully requires Windows")
            for hwnd in hwnds:
                user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
        journal.update_status(entry_id, "done")
        return ToolResult(ok=True)
    except Exception as exc:
        journal.update_status(entry_id, "failed")
        return ToolResult(ok=False, reason=str(exc))


def terminate(
    ref: ProcessRef, *, dry_run: bool = False, provider=None
) -> ToolResult:
    """Force-kill the process (TerminateProcess on Windows). Irreversible."""
    if reason := _safety(ref, provider):
        return ToolResult(ok=False, reason=reason)

    if dry_run:
        journal.record(ref, "terminate", "dry_run", {})
        return ToolResult(ok=True, reason="dry run")

    entry_id = journal.record(ref, "terminate", "pending", {})
    try:
        if provider is not None:
            provider.terminate(ref.pid)
        else:
            proc = psutil.Process(ref.pid)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                pass
        journal.update_status(entry_id, "done")
        return ToolResult(ok=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied, PermissionError) as exc:
        journal.update_status(entry_id, "failed")
        return ToolResult(ok=False, reason=str(exc))


# ── Undo tools ────────────────────────────────────────────────────────────────

def restore_priority(
    ref: ProcessRef, priority: int, *, dry_run: bool = False, provider=None
) -> ToolResult:
    """Restore a previously saved priority class. Called by journal.undo()."""
    if reason := _safety(ref, provider):
        return ToolResult(ok=False, reason=reason)

    if dry_run:
        return ToolResult(ok=True, reason="dry run")

    entry_id = journal.record(ref, "restore_priority", "pending", {})
    try:
        _set_priority(ref.pid, priority, provider)
        journal.update_status(entry_id, "done")
        return ToolResult(ok=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied, PermissionError) as exc:
        journal.update_status(entry_id, "failed")
        return ToolResult(ok=False, reason=str(exc))


def resume(
    ref: ProcessRef, *, dry_run: bool = False, provider=None
) -> ToolResult:
    """Resume a suspended process. Called by journal.undo()."""
    if reason := _safety(ref, provider):
        return ToolResult(ok=False, reason=reason)

    if dry_run:
        return ToolResult(ok=True, reason="dry run")

    entry_id = journal.record(ref, "resume", "pending", {})
    try:
        if provider is not None:
            provider.resume(ref.pid)
        else:
            psutil.Process(ref.pid).resume()
        journal.update_status(entry_id, "done")
        return ToolResult(ok=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied, PermissionError) as exc:
        journal.update_status(entry_id, "failed")
        return ToolResult(ok=False, reason=str(exc))
