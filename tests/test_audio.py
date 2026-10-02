import os

import pytest

from optimizer.platform import IS_WINDOWS
from optimizer.tools.audio import get_audio_pids


def test_get_audio_pids_returns_frozenset():
    result = get_audio_pids()
    assert isinstance(result, frozenset)


def test_get_audio_pids_contains_ints():
    result = get_audio_pids()
    assert all(isinstance(p, int) for p in result)


def test_get_audio_pids_no_zero_pid():
    # PID 0 is the system sounds session — we explicitly skip it.
    result = get_audio_pids()
    assert 0 not in result


def test_get_audio_pids_own_pid_absent():
    # The test runner is not playing audio.
    result = get_audio_pids()
    assert os.getpid() not in result


@pytest.mark.skipif(not IS_WINDOWS, reason="Windows only")
def test_get_audio_pids_positive_pids_on_windows():
    result = get_audio_pids()
    assert all(p > 0 for p in result)
