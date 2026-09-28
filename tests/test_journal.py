import time

import pytest

from optimizer import journal
from optimizer.models import ProcessRef


pytestmark = pytest.mark.usefixtures("tmp_journal")

_REF = ProcessRef(pid=1234, create_time=1000.0, name="chrome.exe", exe="C:\\chrome.exe")


def test_record_and_retrieve():
    entry_id = journal.record(_REF, "lower_priority", "pending", {"fn": "restore_priority", "priority": 32})
    assert isinstance(entry_id, int)
    entries = journal.undoable()
    assert any(e.id == entry_id for e in entries)


def test_update_status():
    entry_id = journal.record(_REF, "lower_priority", "pending", {"fn": "restore_priority", "priority": 32})
    journal.update_status(entry_id, "active")
    entries = journal.undoable()
    match = next(e for e in entries if e.id == entry_id)
    assert match.status == "active"


def test_undoable_filters_by_action():
    # close_gracefully and terminate are NOT in _UNDOABLE_ACTIONS.
    journal.record(_REF, "close_gracefully", "done", {})
    journal.record(_REF, "terminate", "done", {})
    journal.record(_REF, "lower_priority", "active", {"fn": "restore_priority", "priority": 32})
    undoable = journal.undoable()
    assert all(e.action in ("lower_priority", "set_efficiency_mode", "suspend") for e in undoable)


def test_undoable_excludes_dry_run():
    journal.record(_REF, "lower_priority", "dry_run", {})
    undoable = journal.undoable()
    assert not any(e.status == "dry_run" for e in undoable)


def test_due_returns_expired_suspends():
    now = time.time()
    entry_id = journal.record(
        _REF, "suspend", "active", {"fn": "resume"}, expires_at=now - 10
    )
    due = journal.due(now)
    assert any(e.id == entry_id for e in due)


def test_due_skips_future_expiry():
    now = time.time()
    entry_id = journal.record(
        _REF, "suspend", "active", {"fn": "resume"}, expires_at=now + 9999
    )
    due = journal.due(now)
    assert not any(e.id == entry_id for e in due)


def test_undo_all_marks_missing_process_as_undone():
    # Insert a pending lower_priority entry for a PID that doesn't exist.
    ghost_ref = ProcessRef(pid=99_999_999, create_time=1.0, name="ghost.exe", exe="C:\\ghost.exe")
    entry_id = journal.record(ghost_ref, "lower_priority", "pending",
                               {"fn": "restore_priority", "priority": 32})
    journal.undo_all()
    # The row must be marked undone (process was gone → treated as already reversed).
    conn = journal._conn()
    row = conn.execute("SELECT status FROM journal WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "undone"


def test_undo_json_round_trips():
    undo = {"fn": "restore_priority", "priority": 12345}
    entry_id = journal.record(_REF, "lower_priority", "pending", undo)
    entry = next(e for e in journal.undoable() if e.id == entry_id)
    assert entry.undo_json == undo


def test_expires_at_stored_and_retrieved():
    ts = time.time() + 60
    entry_id = journal.record(_REF, "suspend", "active", {"fn": "resume"}, expires_at=ts)
    due_later = journal.due(ts - 1)   # not yet due
    due_now   = journal.due(ts + 1)   # now due
    assert not any(e.id == entry_id for e in due_later)
    assert any(e.id == entry_id for e in due_now)
