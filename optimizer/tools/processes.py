"""
list_processes() and get_process_details() — read-only process snapshots.
"""
from __future__ import annotations

import time
from typing import Any

import psutil

from optimizer.models import ProcessInfo

# Keyed by (pid, create_time) so PID reuse is detected automatically.
# Entries for dead processes are evicted after each list_processes() call.
_proc_cache: dict[tuple[int, float], psutil.Process] = {}

# Memory cached separately: GetProcessMemoryInfo costs ~3ms per process on Windows.
# At 340 processes, that's ~1 second per scan. Cache for 30s so steady-state scans
# cost ~2ms instead of ~920ms.
_MEM_CACHE_TTL = 30.0
_mem_cache: dict[tuple[int, float], tuple[float, float, float]] = {}
# (pid, create_time) → (private_mb, wset_mb, fetched_at)


def _cached_proc(pid: int, create_time: float) -> psutil.Process:
    key = (pid, create_time)
    if key not in _proc_cache:
        _proc_cache[key] = psutil.Process(pid)
    return _proc_cache[key]


def _evict(alive: set[tuple[int, float]]) -> None:
    for key in list(_proc_cache):
        if key not in alive:
            del _proc_cache[key]
    for key in list(_mem_cache):
        if key not in alive:
            del _mem_cache[key]


def _get_memory(pid: int, create_time: float) -> tuple[float, float]:
    """(private_mb, wset_mb) — served from cache if fresh, else fetched live."""
    key = (pid, create_time)
    now = time.time()
    cached = _mem_cache.get(key)
    if cached is not None and now - cached[2] < _MEM_CACHE_TTL:
        return cached[0], cached[1]
    try:
        mi = psutil.Process(pid).memory_info()
        priv = _private_mb(mi)
        wset = mi.rss / 1_048_576
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        priv = wset = 0.0
    _mem_cache[key] = (priv, wset, now)
    return priv, wset


def _private_mb(mi: Any) -> float:
    """Windows exposes .private; Linux/macOS fall back to .rss."""
    private = getattr(mi, "private", None)
    if private is not None:
        return private / 1_048_576
    return mi.rss / 1_048_576


def _build_info(
    pid: int,
    create_time: float,
    name: str,
    cpu_pct: float,
    proc: psutil.Process,
) -> ProcessInfo:
    """Fill all ProcessInfo fields from a live psutil.Process (inside oneshot)."""
    try:
        exe = proc.exe()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        exe = ""

    try:
        username = proc.username()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        username = ""

    try:
        ppid = proc.ppid()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        ppid = 0

    try:
        mi = proc.memory_info()
        private_mb = _private_mb(mi)
        wset_mb = mi.rss / 1_048_576
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        private_mb = 0.0
        wset_mb = 0.0

    try:
        io = proc.io_counters()
        io_bytes = io.read_bytes + io.write_bytes
    except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
        io_bytes = 0

    try:
        num_threads = proc.num_threads()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        num_threads = 0

    try:
        priority = proc.nice()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        priority = None

    return ProcessInfo(
        pid=pid,
        create_time=create_time,
        name=name,
        exe=exe,
        username=username,
        ppid=ppid,
        cpu_percent=cpu_pct,
        private_mb=private_mb,
        wset_mb=wset_mb,
        io_bytes_total=io_bytes,
        num_threads=num_threads,
        priority=priority,
    )


# Minimal batch attributes — only what Windows can enumerate cheaply.
# memory_info costs ~3ms/process via OpenProcess; fetched from _mem_cache instead.
_ITER_ATTRS = ["pid", "name", "create_time", "ppid", "num_threads", "nice"]


def list_processes() -> list[ProcessInfo]:
    """
    Snapshot every running process in one pass.
    cpu_percent reflects CPU since the previous call.
    Memory values come from a 30s cache; first call is slow (~1s), subsequent are ~2ms.
    exe/username/io_bytes left empty; use get_process_details() when you need them.
    """
    results: list[ProcessInfo] = []
    alive: set[tuple[int, float]] = set()

    for proc in psutil.process_iter(_ITER_ATTRS):
        try:
            info = proc.info
            pid: int = info["pid"]
            create_time: float = info["create_time"]
            if create_time is None:
                continue
            name: str = info["name"] or ""

            alive.add((pid, create_time))
            cpu_pct = _cached_proc(pid, create_time).cpu_percent(interval=None)
            private_mb, wset_mb = _get_memory(pid, create_time)

            results.append(ProcessInfo(
                pid=pid,
                create_time=create_time,
                name=name,
                exe="",
                username="",
                ppid=info.get("ppid") or 0,
                cpu_percent=cpu_pct,
                private_mb=private_mb,
                wset_mb=wset_mb,
                io_bytes_total=0,
                num_threads=info.get("num_threads") or 0,
                priority=info.get("nice"),
            ))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    _evict(alive)
    return results


def get_process_details(pid: int) -> ProcessInfo | None:
    """
    Detailed snapshot for a single process, including parent name and uptime.
    Returns None if the process has exited or is inaccessible.
    """
    try:
        proc = psutil.Process(pid)
        with proc.oneshot():
            try:
                create_time = proc.create_time()
                name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return None

            cpu_pct = _cached_proc(pid, create_time).cpu_percent(interval=None)
            info = _build_info(pid, create_time, name, cpu_pct, proc)

            # Enrich with parent name and uptime.
            parent_name = ""
            try:
                ppid = proc.ppid()
                if ppid:
                    parent_name = psutil.Process(ppid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            uptime_s = time.time() - create_time if create_time is not None else None

            return info.model_copy(update={"parent_name": parent_name, "uptime_s": uptime_s})

    except psutil.NoSuchProcess:
        return None
    except psutil.AccessDenied:
        return None
