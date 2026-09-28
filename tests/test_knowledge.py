from optimizer.models import KnownProcess
from optimizer.tools.knowledge import lookup_known_process


def test_lookup_known_process_returns_known_process():
    result = lookup_known_process("chrome.exe", "C:\\Program Files\\Google\\Chrome\\chrome.exe")
    assert isinstance(result, KnownProcess)
    assert result.name == "chrome.exe"


def test_lookup_case_insensitive():
    assert lookup_known_process("Chrome.EXE", "C:\\Chrome\\chrome.exe") is not None


def test_lookup_unknown_returns_none():
    assert lookup_known_process("definitely_not_a_known_process.exe", "") is None


def test_lookup_path_hint_matches():
    # "updater.exe" with path_hint="Google" should match a Google path.
    result = lookup_known_process(
        "updater.exe",
        "C:\\Program Files (x86)\\Google\\Update\\1.3.36\\updater.exe",
    )
    assert result is not None
    assert "Google" in result.description


def test_lookup_path_hint_skips_wrong_path():
    # "updater.exe" with path_hint="Google" must NOT match a non-Google path;
    # falls through to the generic entry (path_hint="").
    result = lookup_known_process("updater.exe", "C:\\SomeApp\\updater.exe")
    assert result is not None
    assert "Google" not in result.description


def test_lookup_path_hint_empty_matches_any():
    # An entry with path_hint="" matches any exe path.
    result = lookup_known_process("onedrive.exe", "C:\\Users\\bob\\OneDrive\\onedrive.exe")
    assert result is not None


def test_category_is_valid_literal():
    valid = {"core_system", "security", "driver_helper", "user_app", "useful_background", "bloat"}
    for exe_name in ("chrome.exe", "steam.exe", "msmpeng.exe"):
        result = lookup_known_process(exe_name, "")
        if result is not None:
            assert result.category in valid


def test_description_is_nonempty_string():
    result = lookup_known_process("discord.exe", "")
    assert result is not None
    assert len(result.description) > 10
