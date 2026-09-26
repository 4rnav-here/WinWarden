"""
get_system_pressure() — cheap, read-only snapshot of whole-PC stress.
Windows-only fields (commit_ratio, hard_faults_per_s) return None elsewhere.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import time

import psutil

from optimizer.models import SystemPressure
from optimizer.platform import IS_WINDOWS, pdh, psapi

# Prime the CPU sampler so the first real call has a delta to measure.
psutil.cpu_percent(interval=None)


# ── Commit ratio via GetPerformanceInfo (psapi) ───────────────────────────────

class _PERFORMANCE_INFORMATION(ctypes.Structure):
    # https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-performance_information
    _fields_ = [
        ("cb",                ctypes.wintypes.DWORD),
        ("CommitTotal",       ctypes.c_size_t),
        ("CommitLimit",       ctypes.c_size_t),
        ("CommitPeak",        ctypes.c_size_t),
        ("PhysicalTotal",     ctypes.c_size_t),
        ("PhysicalAvailable", ctypes.c_size_t),
        ("SystemCache",       ctypes.c_size_t),
        ("KernelTotal",       ctypes.c_size_t),
        ("KernelPaged",       ctypes.c_size_t),
        ("KernelNonpaged",    ctypes.c_size_t),
        ("PageSize",          ctypes.c_size_t),
        ("HandleCount",       ctypes.wintypes.DWORD),
        ("ProcessCount",      ctypes.wintypes.DWORD),
        ("ThreadCount",       ctypes.wintypes.DWORD),
    ]


if IS_WINDOWS and psapi is not None:
    psapi.GetPerformanceInfo.restype = ctypes.wintypes.BOOL
    psapi.GetPerformanceInfo.argtypes = [
        ctypes.POINTER(_PERFORMANCE_INFORMATION),
        ctypes.wintypes.DWORD,
    ]


def _get_commit_ratio() -> float | None:
    if not IS_WINDOWS or psapi is None:
        return None
    info = _PERFORMANCE_INFORMATION()
    info.cb = ctypes.sizeof(_PERFORMANCE_INFORMATION)
    if psapi.GetPerformanceInfo(ctypes.byref(info), info.cb) and info.CommitLimit > 0:
        return info.CommitTotal / info.CommitLimit
    return None


# ── Hard faults via PDH ───────────────────────────────────────────────────────

_PDH_FMT_DOUBLE = 0x00000200
_COUNTER_PATH = "\\Memory\\Pages Input/sec"


class _PdhFmtCounterValue(ctypes.Structure):
    # DWORD CStatus + 4-byte pad (natural alignment) + double doubleValue = 16 bytes.
    _fields_ = [
        ("CStatus",     ctypes.wintypes.DWORD),
        ("doubleValue", ctypes.c_double),
    ]


if IS_WINDOWS and pdh is not None:
    pdh.PdhOpenQueryW.restype = ctypes.c_long
    pdh.PdhOpenQueryW.argtypes = [
        ctypes.wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    pdh.PdhAddEnglishCounterW.restype = ctypes.c_long
    pdh.PdhAddEnglishCounterW.argtypes = [
        ctypes.c_void_p,
        ctypes.wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    pdh.PdhCollectQueryData.restype = ctypes.c_long
    pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
    pdh.PdhGetFormattedCounterValue.restype = ctypes.c_long
    pdh.PdhGetFormattedCounterValue.argtypes = [
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(ctypes.wintypes.DWORD),
        ctypes.POINTER(_PdhFmtCounterValue),
    ]
    pdh.PdhCloseQuery.restype = ctypes.c_long
    pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]


class _HardFaultSampler:
    """Keeps a PDH query alive across calls. Rate counters need two samples."""

    def __init__(self) -> None:
        self._hQuery = ctypes.c_void_p()
        self._hCounter = ctypes.c_void_p()
        self._ok = False
        self._prime()

    def _prime(self) -> None:
        if not IS_WINDOWS or pdh is None:
            return
        if pdh.PdhOpenQueryW(None, None, ctypes.byref(self._hQuery)) != 0:
            return
        if pdh.PdhAddEnglishCounterW(
            self._hQuery, _COUNTER_PATH, None, ctypes.byref(self._hCounter)
        ) != 0:
            return
        # First collection establishes the baseline; value is not yet valid.
        pdh.PdhCollectQueryData(self._hQuery)
        self._ok = True

    def sample(self) -> float | None:
        """Collect second (or later) sample and return the computed rate."""
        if not self._ok:
            return None
        if pdh.PdhCollectQueryData(self._hQuery) != 0:
            return None
        val = _PdhFmtCounterValue()
        if (
            pdh.PdhGetFormattedCounterValue(
                self._hCounter, _PDH_FMT_DOUBLE, None, ctypes.byref(val)
            ) != 0
            or val.CStatus != 0
        ):
            return None
        return val.doubleValue


_sampler: _HardFaultSampler | None = None


def _hard_fault_sampler() -> _HardFaultSampler:
    global _sampler
    if _sampler is None:
        _sampler = _HardFaultSampler()
    return _sampler


# ── Disk busy via psutil delta ────────────────────────────────────────────────

_last_disk_io: object | None = None  # psutil.sdiskio namedtuple
_last_disk_ts: float | None = None


def _get_disk_busy_percent() -> float | None:
    global _last_disk_io, _last_disk_ts
    try:
        counters = psutil.disk_io_counters()
        if counters is None:
            return None
        now = time.monotonic()
        if _last_disk_io is not None and _last_disk_ts is not None:
            elapsed = now - _last_disk_ts
            if elapsed > 0:
                prev = _last_disk_io
                delta_ms = (
                    (counters.read_time + counters.write_time)
                    - (prev.read_time + prev.write_time)  # type: ignore[union-attr]
                )
                busy = (delta_ms / 1000.0) / elapsed * 100.0
                busy = max(0.0, min(100.0, busy))
                _last_disk_io = counters
                _last_disk_ts = now
                return busy
        _last_disk_io = counters
        _last_disk_ts = now
        return None
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def get_system_pressure() -> SystemPressure:
    return SystemPressure(
        cpu_percent=psutil.cpu_percent(interval=None),
        ram_percent=psutil.virtual_memory().percent,
        commit_ratio=_get_commit_ratio(),
        hard_faults_per_s=_hard_fault_sampler().sample(),
        disk_busy_percent=_get_disk_busy_percent(),
    )
