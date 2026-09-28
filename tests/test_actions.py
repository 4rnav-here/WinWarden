import os
import time

import psutil
import pytest

from optimizer import journal
from optimizer.models import ProcessRef
from optimizer.tools.actions import (
    close_gracefully,
    lower_priority,
    resume,
    restore_priority,
    set_efficiency_mode,
    suspend,
    terminate,
)
from tests.fakes import FakeProcess, FakeProcessProvider

pytestmark = pytest.mark.usefixtures("tmp_journal")

_NORMAL = getattr(psutil, "NORMAL_PRIORITY_CLASS", 32)
_BELOW  = getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", 10)
_IDLE   = getattr(psutil, "IDLE_PRIORITY_CLASS", 19)


def _make_proc(pid=5000, priority=_NORMAL, has_window=False, **kw) -> FakeProcess:
    return FakeProcess(
        pid=pid, create_time=1000.0, name="app.exe",
        exe="C:\\App\\app.exe", username="DESKTOP\\user",
        priority=priority, has_window=has_window, **kw,
    )


def _ref(proc: FakeProcess) -> ProcessRef:
    return ProcessRef(
        pid=proc.pid, create_time=proc.create_time,
        name=proc.name, exe=proc.exe,
    )


# ── Protection: every action refuses protected processes ──────────────────────

@pytest.mark.parametrize("action_fn", [
    lower_priority, set_efficiency_mode, suspend, terminate,
])
def test_protected_name_refused(action_fn):
    provider = FakeProcessProvider([
        FakeProcess(pid=500, create_time=1.0, name="csrss.exe", exe="C:\\Windows\\csrss.exe"),
    ])
    ref = ProcessRef(pid=500, create_time=1.0, name="csrss.exe", exe="C:\\Windows\\csrss.exe")
    result = action_fn(ref, provider=provider)
    assert not result.ok
    assert result.reason


def test_close_gracefully_refused_for_protected():
    provider = FakeProcessProvider([
        FakeProcess(pid=500, create_time=1.0, name="explorer.exe",
                    exe="C:\\Windows\\explorer.exe", has_window=True),
    ])
    ref = ProcessRef(pid=500, create_time=1.0, name="explorer.exe", exe="C:\\Windows\\explorer.exe")
    result = close_gracefully(ref, provider=provider)
    assert not result.ok


# ── Identity: reused PID refused ─────────────────────────────────────────────

def test_reused_pid_refused():
    provider = FakeProcessProvider([
        FakeProcess(pid=5000, create_time=9999.0, name="app.exe", exe="C:\\app.exe"),
    ])
    ref = ProcessRef(pid=5000, create_time=1000.0, name="app.exe", exe="C:\\app.exe")
    result = lower_priority(ref, provider=provider)
    assert not result.ok
    assert "reused" in result.reason.lower()


# ── Dry run: records to journal, changes nothing ──────────────────────────────

def test_dry_run_records_and_no_change():
    p = _make_proc(priority=_NORMAL)
    provider = FakeProcessProvider([p])
    result = lower_priority(_ref(p), dry_run=True, provider=provider)

    assert result.ok
    assert result.reason == "dry run"
    assert p.priority == _NORMAL          # unchanged
    assert not any(c[0] == "set_priority" for c in provider.calls)

    entries = journal._conn().execute(
        "SELECT status FROM journal WHERE action = 'lower_priority'"
    ).fetchall()
    assert any(row["status"] == "dry_run" for row in entries)


# ── lower_priority ────────────────────────────────────────────────────────────

def test_lower_priority_sets_below_normal():
    p = _make_proc(priority=_NORMAL)
    provider = FakeProcessProvider([p])
    result = lower_priority(_ref(p), provider=provider)

    assert result.ok
    assert p.priority == _BELOW
    assert result.undo == {"fn": "restore_priority", "priority": _NORMAL}


def test_lower_priority_journal_active():
    p = _make_proc()
    provider = FakeProcessProvider([p])
    lower_priority(_ref(p), provider=provider)

    entries = journal.undoable()
    assert any(e.action == "lower_priority" and e.status == "active" for e in entries)


# ── set_efficiency_mode ───────────────────────────────────────────────────────

def test_efficiency_mode_on_sets_idle_priority():
    p = _make_proc(priority=_NORMAL)
    provider = FakeProcessProvider([p])
    result = set_efficiency_mode(_ref(p), on=True, provider=provider)

    assert result.ok
    assert p.priority == _IDLE
    assert p.efficiency_mode is True


def test_efficiency_mode_undo_restores_priority():
    p = _make_proc(priority=_NORMAL)
    provider = FakeProcessProvider([p])

    # Enable
    result = set_efficiency_mode(_ref(p), on=True, provider=provider)
    assert result.ok
    assert result.undo["priority"] == _NORMAL

    # Undo: turn off EcoQoS and restore priority
    set_efficiency_mode(_ref(p), on=False, provider=provider)
    restore_priority(_ref(p), result.undo["priority"], provider=provider)

    assert p.efficiency_mode is False
    assert p.priority == _NORMAL


# ── suspend / resume ──────────────────────────────────────────────────────────

def test_suspend_suspends_process():
    p = _make_proc()
    provider = FakeProcessProvider([p])
    result = suspend(_ref(p), provider=provider)

    assert result.ok
    assert p.suspended is True
    assert result.undo == {"fn": "resume"}


def test_resume_resumes_process():
    p = _make_proc(suspended=True)
    provider = FakeProcessProvider([p])
    result = resume(_ref(p), provider=provider)

    assert result.ok
    assert p.suspended is False


# ── close_gracefully ──────────────────────────────────────────────────────────

def test_close_gracefully_succeeds_with_window():
    p = _make_proc(has_window=True)
    provider = FakeProcessProvider([p])
    result = close_gracefully(_ref(p), provider=provider)

    assert result.ok
    assert any(c[0] == "post_wm_close" for c in provider.calls)


def test_close_gracefully_fails_without_window():
    p = _make_proc(has_window=False)
    provider = FakeProcessProvider([p])
    result = close_gracefully(_ref(p), provider=provider)

    assert not result.ok
    assert "window" in result.reason.lower()


# ── terminate ─────────────────────────────────────────────────────────────────

def test_terminate_removes_process():
    p = _make_proc()
    provider = FakeProcessProvider([p])
    result = terminate(_ref(p), provider=provider)

    assert result.ok
    assert provider.get(p.pid) is None  # evicted from fake provider


# ── journal crash recovery ────────────────────────────────────────────────────

def test_undo_all_clears_pending_for_gone_process():
    ghost = ProcessRef(pid=99_999_999, create_time=1.0, name="ghost.exe", exe="C:\\ghost.exe")
    entry_id = journal.record(ghost, "lower_priority", "pending",
                               {"fn": "restore_priority", "priority": _NORMAL})
    journal.undo_all()

    conn = journal._conn()
    row = conn.execute("SELECT status FROM journal WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "undone"
