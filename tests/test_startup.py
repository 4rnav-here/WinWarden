import pytest

from optimizer.platform import IS_WINDOWS
from optimizer.tools.startup import _parse_exe_name, get_service_pids, get_startup_executables


# ── _parse_exe_name ────────────────────────────────────────────────────────────

class TestParseExeName:
    def test_unquoted_no_args(self):
        assert _parse_exe_name(r"C:\Windows\notepad.exe") == "notepad.exe"

    def test_unquoted_with_args(self):
        assert _parse_exe_name(r"C:\Windows\notepad.exe /flag") == "notepad.exe"

    def test_quoted_path_with_spaces(self):
        result = _parse_exe_name(r'"C:\Program Files\App\app.exe" --start')
        assert result == "app.exe"

    def test_quoted_no_args(self):
        result = _parse_exe_name(r'"C:\Program Files\Google\Update\GoogleUpdate.exe"')
        assert result == "googleupdate.exe"

    def test_empty_string(self):
        assert _parse_exe_name("") is None

    def test_whitespace_only(self):
        assert _parse_exe_name("   ") is None

    def test_case_is_lowered(self):
        assert _parse_exe_name(r"C:\Windows\Notepad.EXE") == "notepad.exe"


# ── get_startup_executables ────────────────────────────────────────────────────

def test_get_startup_executables_returns_set():
    result = get_startup_executables()
    assert isinstance(result, set)


def test_get_startup_executables_all_lowercase():
    for name in get_startup_executables():
        assert name == name.lower()


def test_get_startup_executables_cached():
    r1 = get_startup_executables()
    r2 = get_startup_executables()
    assert r1 is r2  # same object from cache


def test_get_startup_executables_empty_on_non_windows():
    if IS_WINDOWS:
        pytest.skip("Non-Windows only")
    assert get_startup_executables() == set()


# ── get_service_pids ──────────────────────────────────────────────────────────

def test_get_service_pids_returns_set():
    result = get_service_pids()
    assert isinstance(result, set)


def test_get_service_pids_all_ints():
    for pid in get_service_pids():
        assert isinstance(pid, int)
        assert pid > 0


def test_get_service_pids_cached():
    r1 = get_service_pids()
    r2 = get_service_pids()
    assert r1 is r2


def test_get_service_pids_empty_on_non_windows():
    if IS_WINDOWS:
        pytest.skip("Non-Windows only")
    assert get_service_pids() == set()


def test_get_service_pids_nonempty_on_windows():
    if not IS_WINDOWS:
        pytest.skip("Windows only")
    assert len(get_service_pids()) > 0
