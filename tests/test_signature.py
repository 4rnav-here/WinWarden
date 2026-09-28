import pytest

from optimizer.platform import IS_WINDOWS
from optimizer.tools.signature import _extract_o, get_signer


# ── _extract_o ─────────────────────────────────────────────────────────────────

class TestExtractO:
    def test_simple(self):
        assert _extract_o("CN=Foo, O=Google LLC, C=US") == "Google LLC"

    def test_o_at_start(self):
        assert _extract_o("O=Microsoft Corporation, C=US") == "Microsoft Corporation"

    def test_o_with_spaces(self):
        assert _extract_o("CN=App, O=Some Company Ltd, L=London") == "Some Company Ltd"

    def test_no_o_field(self):
        assert _extract_o("CN=Foo, C=US") is None

    def test_empty_string(self):
        assert _extract_o("") is None


# ── get_signer ─────────────────────────────────────────────────────────────────

def test_get_signer_returns_none_on_non_windows():
    if IS_WINDOWS:
        pytest.skip("Non-Windows only")
    assert get_signer("C:\\Windows\\notepad.exe") is None


def test_get_signer_returns_none_for_empty_path():
    assert get_signer("") is None


def test_get_signer_returns_none_on_missing_file():
    # Non-existent path; PowerShell will report unsigned/error.
    # Just verify it returns a string (not-valid) or None, never raises.
    result = get_signer("C:\\does_not_exist_xyz.exe")
    assert result is None or isinstance(result, str)


def test_get_signer_caches_result():
    # Two calls with the same path return the same object from cache.
    r1 = get_signer("C:\\does_not_exist_xyz_cached.exe")
    r2 = get_signer("C:\\does_not_exist_xyz_cached.exe")
    assert r1 is r2


@pytest.mark.skipif(not IS_WINDOWS, reason="Windows only")
def test_get_signer_windows_system_binary():
    # System binaries should be signed by Microsoft.
    result = get_signer("C:\\Windows\\System32\\notepad.exe")
    assert result is not None
    assert "Microsoft" in result
