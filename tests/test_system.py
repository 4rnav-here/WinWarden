import pytest

from optimizer.models import SystemPressure
from optimizer.platform import IS_WINDOWS
from optimizer.tools.system import get_system_pressure


def test_returns_system_pressure():
    sp = get_system_pressure()
    assert isinstance(sp, SystemPressure)


def test_cpu_percent_in_range():
    sp = get_system_pressure()
    # psutil can return > 100 on multi-core, but never negative.
    assert sp.cpu_percent >= 0.0


def test_ram_percent_in_range():
    sp = get_system_pressure()
    assert 0.0 <= sp.ram_percent <= 100.0


def test_windows_only_fields_none_on_non_windows():
    if IS_WINDOWS:
        pytest.skip("Non-Windows behaviour only")
    sp = get_system_pressure()
    assert sp.commit_ratio is None
    assert sp.hard_faults_per_s is None


def test_windows_commit_ratio_non_negative():
    if not IS_WINDOWS:
        pytest.skip("Windows only")
    sp = get_system_pressure()
    if sp.commit_ratio is not None:
        assert sp.commit_ratio > 0.0


def test_multiple_calls_do_not_crash():
    """Disk-busy and hard-fault deltas require two calls; second must not crash."""
    get_system_pressure()
    sp2 = get_system_pressure()
    assert isinstance(sp2, SystemPressure)


def test_disk_busy_in_range_after_second_call():
    get_system_pressure()
    sp = get_system_pressure()
    if sp.disk_busy_percent is not None:
        assert 0.0 <= sp.disk_busy_percent <= 100.0
