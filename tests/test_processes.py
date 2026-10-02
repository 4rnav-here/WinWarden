import os
import time

import psutil
import pytest

from optimizer.models import ProcessInfo
from optimizer.tools.processes import _evict, _proc_cache, get_process_details, list_processes


def test_list_processes_returns_nonempty_list():
    procs = list_processes()
    assert isinstance(procs, list)
    assert len(procs) > 0


def test_list_processes_includes_self():
    own_pid = os.getpid()
    procs = list_processes()
    assert any(p.pid == own_pid for p in procs)


def test_list_processes_all_valid_fields():
    procs = list_processes()
    for p in procs:
        assert isinstance(p, ProcessInfo)
        assert p.pid >= 0
        assert isinstance(p.name, str)  # kernel threads may have empty names
        assert p.cpu_percent >= 0.0
        assert p.private_mb >= 0.0
        assert p.wset_mb >= 0.0
        assert p.io_bytes_total >= 0
        assert p.num_threads >= 0


def test_list_processes_no_detail_fields():
    """list_processes leaves parent_name and uptime_s at their defaults."""
    procs = list_processes()
    for p in procs:
        assert p.parent_name == ""
        assert p.uptime_s is None


def test_cpu_percent_delta_on_second_call():
    """After priming, cpu_percent must be a valid float (>= 0)."""
    list_processes()
    time.sleep(0.05)
    procs = list_processes()
    assert all(p.cpu_percent >= 0.0 for p in procs)


def test_list_processes_cache_eviction():
    """Dead PIDs are removed from the cache after a full scan."""
    list_processes()
    _proc_cache[(999_999_999, 0.0)] = psutil.Process(os.getpid())
    list_processes()
    # The key invariant: the manually inserted stale entry is gone.
    assert (999_999_999, 0.0) not in _proc_cache


def test_list_processes_multiple_calls_stable():
    """Three consecutive calls should not crash."""
    for _ in range(3):
        procs = list_processes()
        assert len(procs) > 0


# ── get_process_details ────────────────────────────────────────────────────────

def test_get_process_details_self():
    own_pid = os.getpid()
    info = get_process_details(own_pid)
    assert info is not None
    assert info.pid == own_pid
    assert info.name != ""


def test_get_process_details_has_uptime():
    own_pid = os.getpid()
    info = get_process_details(own_pid)
    assert info is not None
    assert info.uptime_s is not None
    assert info.uptime_s > 0.0


def test_get_process_details_has_parent_name():
    own_pid = os.getpid()
    info = get_process_details(own_pid)
    assert info is not None
    # parent_name may be empty if we can't access the parent, but should be a string.
    assert isinstance(info.parent_name, str)


def test_get_process_details_nonexistent_pid():
    assert get_process_details(99_999_999) is None


def test_get_process_details_all_valid_fields():
    own_pid = os.getpid()
    info = get_process_details(own_pid)
    assert info is not None
    assert info.cpu_percent >= 0.0
    assert info.private_mb >= 0.0
    assert info.wset_mb >= 0.0
    assert info.io_bytes_total >= 0
    assert info.num_threads >= 1
