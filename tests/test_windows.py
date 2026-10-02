import os

import pytest

from optimizer.platform import IS_WINDOWS
from optimizer.tools.windows import get_foreground_pid, get_process_windows, has_windowed_ancestor, is_hung


def test_get_foreground_pid_returns_int_or_none():
    result = get_foreground_pid()
    assert result is None or isinstance(result, int)


def test_get_foreground_pid_positive_on_windows():
    if not IS_WINDOWS:
        pytest.skip("Windows only")
    result = get_foreground_pid()
    # A foreground window should exist while the test runner is active.
    # Could be None in headless CI; just verify the type.
    assert result is None or result > 0


def test_get_process_windows_returns_dict():
    result = get_process_windows()
    assert isinstance(result, dict)


def test_get_process_windows_values_are_lists():
    result = get_process_windows()
    for pid, hwnds in result.items():
        assert isinstance(pid, int)
        assert isinstance(hwnds, list)
        assert all(isinstance(h, int) for h in hwnds)


def test_is_hung_returns_bool():
    result = is_hung(os.getpid())
    assert isinstance(result, bool)


def test_is_hung_test_runner_not_hung():
    assert is_hung(os.getpid()) is False


def test_is_hung_unknown_pid():
    assert is_hung(99_999_999) is False


# ── Non-Windows fallback ───────────────────────────────────────────────────────

def test_non_windows_foreground_pid_is_none():
    if IS_WINDOWS:
        pytest.skip("Non-Windows only")
    assert get_foreground_pid() is None


def test_non_windows_process_windows_is_empty():
    if IS_WINDOWS:
        pytest.skip("Non-Windows only")
    assert get_process_windows() == {}


def test_non_windows_is_hung_is_false():
    if IS_WINDOWS:
        pytest.skip("Non-Windows only")
    assert is_hung(1) is False


# ── has_windowed_ancestor ──────────────────────────────────────────────────────

def test_has_windowed_ancestor_returns_bool():
    import os
    result = has_windowed_ancestor(os.getpid())
    assert isinstance(result, bool)


def test_has_windowed_ancestor_nonexistent_pid():
    # Must not raise — returns False on any access error.
    assert has_windowed_ancestor(99_999_999) is False


def test_non_windows_has_windowed_ancestor_false():
    if IS_WINDOWS:
        pytest.skip("Non-Windows only")
    assert has_windowed_ancestor(1) is False
