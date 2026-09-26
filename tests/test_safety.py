import os

import pytest

from optimizer.models import ProcessRef
from optimizer.tools.safety import check_protection, looks_disguised, verify_identity
from tests.fakes import FakeProcess, FakeProcessProvider


def _ref(
    pid: int = 1234,
    create_time: float = 1000.0,
    name: str = "chrome.exe",
    exe: str = "C:\\Program Files\\Google\\Chrome\\chrome.exe",
) -> ProcessRef:
    return ProcessRef(pid=pid, create_time=create_time, name=name, exe=exe)


# ── check_protection ──────────────────────────────────────────────────────────

class TestCheckProtection:
    def test_kernel_pid_0(self):
        assert check_protection("system", "", "", 0) is not None

    def test_kernel_pid_4(self):
        reason = check_protection("system", "", "", 4)
        assert reason is not None
        assert "4" in reason

    def test_own_pid_refused(self):
        reason = check_protection("python.exe", "", "", os.getpid())
        assert reason is not None

    def test_protected_name_csrss(self):
        reason = check_protection("csrss.exe", "C:\\Windows\\csrss.exe", "", 500)
        assert reason is not None

    def test_protected_name_svchost(self):
        reason = check_protection("svchost.exe", "C:\\Windows\\System32\\svchost.exe", "", 888)
        assert reason is not None

    def test_protected_name_lsass(self):
        assert check_protection("lsass.exe", "", "", 700) is not None

    def test_service_account_system(self):
        reason = check_protection("service.exe", "", "NT AUTHORITY\\SYSTEM", 999)
        assert reason is not None

    def test_service_account_local_service(self):
        reason = check_protection("service.exe", "", "NT AUTHORITY\\LOCAL SERVICE", 999)
        assert reason is not None

    def test_service_account_network_service(self):
        reason = check_protection("service.exe", "", "NT AUTHORITY\\NETWORK SERVICE", 999)
        assert reason is not None

    def test_normal_user_process_allowed(self):
        reason = check_protection(
            "chrome.exe",
            "C:\\Program Files\\Google\\Chrome\\chrome.exe",
            "DESKTOP-ABC\\user",
            1234,
        )
        assert reason is None

    def test_normal_process_no_username(self):
        reason = check_protection("notepad.exe", "C:\\Windows\\notepad.exe", "", 2000)
        assert reason is None


# ── looks_disguised ───────────────────────────────────────────────────────────

class TestLooksDisguised:
    def test_svchost_in_temp(self):
        assert looks_disguised("svchost.exe", "C:\\Users\\bob\\AppData\\Local\\Temp\\svchost.exe") is True

    def test_svchost_in_windows_system32(self):
        assert looks_disguised("svchost.exe", "C:\\Windows\\System32\\svchost.exe") is False

    def test_svchost_in_windows_root(self):
        assert looks_disguised("svchost.exe", "C:\\Windows\\svchost.exe") is False

    def test_csrss_in_downloads(self):
        assert looks_disguised("csrss.exe", "C:\\Users\\bob\\Downloads\\csrss.exe") is True

    def test_non_protected_name_never_disguised(self):
        assert looks_disguised("chrome.exe", "C:\\Users\\bob\\AppData\\Temp\\chrome.exe") is False

    def test_empty_exe_not_disguised(self):
        # Can't tell without an exe path.
        assert looks_disguised("csrss.exe", "") is False

    def test_case_insensitive_name(self):
        assert looks_disguised("Svchost.EXE", "C:\\Temp\\svchost.exe") is True

    def test_case_insensitive_path(self):
        assert looks_disguised("svchost.exe", "C:\\WINDOWS\\System32\\svchost.exe") is False


# ── verify_identity ───────────────────────────────────────────────────────────

class TestVerifyIdentity:
    def _provider_with(self, **overrides) -> FakeProcessProvider:
        defaults = dict(
            pid=1234,
            create_time=1000.0,
            name="chrome.exe",
            exe="C:\\Program Files\\Google\\Chrome\\chrome.exe",
        )
        defaults.update(overrides)
        return FakeProcessProvider([FakeProcess(**defaults)])

    def test_ok(self):
        provider = self._provider_with()
        ref = _ref()
        assert verify_identity(ref, provider=provider) is None

    def test_process_gone(self):
        provider = FakeProcessProvider([])
        reason = verify_identity(_ref(), provider=provider)
        assert reason is not None
        assert "1234" in reason

    def test_pid_reused_different_create_time(self):
        provider = self._provider_with(create_time=9999.0)
        reason = verify_identity(_ref(create_time=1000.0), provider=provider)
        assert reason is not None
        assert "reused" in reason.lower()

    def test_name_changed(self):
        provider = self._provider_with(name="notepad.exe")
        reason = verify_identity(_ref(name="chrome.exe"), provider=provider)
        assert reason is not None
        assert "name" in reason.lower()

    def test_exe_changed(self):
        provider = self._provider_with(exe="C:\\Other\\chrome.exe")
        reason = verify_identity(
            _ref(exe="C:\\Program Files\\Google\\Chrome\\chrome.exe"),
            provider=provider,
        )
        assert reason is not None
        assert "exe" in reason.lower()

    def test_empty_ref_exe_skips_exe_check(self):
        # If the ref has no exe, we can't compare — accept the process.
        provider = self._provider_with(exe="C:\\Windows\\chrome.exe")
        ref = _ref(exe="")
        assert verify_identity(ref, provider=provider) is None

    def test_create_time_zero_is_valid(self):
        # Timestamp of 0 must not be treated as falsy.
        provider = FakeProcessProvider([
            FakeProcess(pid=1, create_time=0.0, name="proc.exe", exe="C:\\proc.exe"),
        ])
        ref = ProcessRef(pid=1, create_time=0.0, name="proc.exe", exe="C:\\proc.exe")
        assert verify_identity(ref, provider=provider) is None

    def test_reused_pid_with_zero_original_create_time(self):
        provider = FakeProcessProvider([
            FakeProcess(pid=1, create_time=500.0, name="proc.exe", exe="C:\\proc.exe"),
        ])
        ref = ProcessRef(pid=1, create_time=0.0, name="proc.exe", exe="C:\\proc.exe")
        reason = verify_identity(ref, provider=provider)
        assert reason is not None
        assert "reused" in reason.lower()
