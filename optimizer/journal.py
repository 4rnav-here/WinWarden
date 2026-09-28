"""
SQLite action journal. Writes a pending row before every action so a crash
leaves enough information to undo. undo_all() runs on startup.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from optimizer.models import ProcessRef

_DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "journal.db"
_DB_PATH: Path = _DEFAULT_DB_PATH
_connection: sqlite3.Connection | None = None

# Only these actions produce reversible journal entries.
_UNDOABLE_ACTIONS = ("lower_priority", "set_efficiency_mode", "suspend")


def init(path: str | Path | None = None) -> None:
    """
    Configure the journal DB path. Call with a temp path in tests.
    Call with no args (or None) to reset to the default location.
    Closes any open connection so the next call picks up the new path.
    """
    global _DB_PATH, _connection
    if _connection is not None:
        try:
            _connection.close()
        except Exception:
            pass
        _connection = None
    _DB_PATH = Path(path) if path is not None else _DEFAULT_DB_PATH


def _conn() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _connection = sqlite3.connect(str(_DB_PATH))
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA journal_mode=WAL")
        _connection.execute("""
            CREATE TABLE IF NOT EXISTS journal (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL    NOT NULL,
                pid         INTEGER NOT NULL,
                create_time REAL    NOT NULL,
                name        TEXT    NOT NULL,
                exe         TEXT    NOT NULL,
                action      TEXT    NOT NULL,
                status      TEXT    NOT NULL,
                undo_json   TEXT    NOT NULL DEFAULT '{}',
                expires_at  REAL,
                note        TEXT    NOT NULL DEFAULT ''
            )
        """)
        _connection.commit()
    return _connection


@dataclass
class JournalEntry:
    id: int
    ts: float
    pid: int
    create_time: float
    name: str
    exe: str
    action: str
    status: str
    undo_json: dict
    expires_at: float | None
    note: str


def _row_to_entry(row: sqlite3.Row) -> JournalEntry:
    return JournalEntry(
        id=row["id"],
        ts=row["ts"],
        pid=row["pid"],
        create_time=row["create_time"],
        name=row["name"],
        exe=row["exe"],
        action=row["action"],
        status=row["status"],
        undo_json=json.loads(row["undo_json"] or "{}"),
        expires_at=row["expires_at"],
        note=row["note"],
    )


def record(
    ref: ProcessRef,
    action: str,
    status: str,
    undo: dict | None = None,
    expires_at: float | None = None,
    note: str = "",
) -> int:
    """Insert a journal row. Returns the row id."""
    db = _conn()
    cur = db.execute(
        """
        INSERT INTO journal (ts, pid, create_time, name, exe, action, status,
                             undo_json, expires_at, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            time.time(), ref.pid, ref.create_time, ref.name, ref.exe,
            action, status, json.dumps(undo or {}), expires_at, note,
        ),
    )
    db.commit()
    return cur.lastrowid  # type: ignore[return-value]


def update_status(entry_id: int, status: str) -> None:
    db = _conn()
    db.execute("UPDATE journal SET status = ? WHERE id = ?", (status, entry_id))
    db.commit()


def undoable() -> list[JournalEntry]:
    """Entries in pending/active state for the reversible action types."""
    placeholders = ",".join("?" * len(_UNDOABLE_ACTIONS))
    rows = _conn().execute(
        f"""
        SELECT * FROM journal
        WHERE status IN ('pending', 'active')
          AND action IN ({placeholders})
        ORDER BY id
        """,
        _UNDOABLE_ACTIONS,
    ).fetchall()
    return [_row_to_entry(r) for r in rows]


def due(now: float) -> list[JournalEntry]:
    """Active entries whose expires_at has passed — use for auto-resume of suspends."""
    rows = _conn().execute(
        "SELECT * FROM journal WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at <= ?",
        (now,),
    ).fetchall()
    return [_row_to_entry(r) for r in rows]


def undo(entry: JournalEntry) -> None:
    """
    Reverse a single journal entry. Re-checks identity first; marks undone
    even if the process is already gone (crash-recovery path).
    """
    from optimizer.tools import actions  # late import — actions imports journal

    ref = ProcessRef(
        pid=entry.pid,
        create_time=entry.create_time,
        name=entry.name,
        exe=entry.exe,
    )

    fn = entry.undo_json.get("fn", "")

    if fn == "restore_priority":
        priority = entry.undo_json.get("priority", 32)
        result = actions.restore_priority(ref, priority)

    elif fn == "resume":
        result = actions.resume(ref)

    elif fn == "restore_efficiency_mode":
        priority = entry.undo_json.get("priority", 32)
        r1 = actions.set_efficiency_mode(ref, on=False)
        r2 = actions.restore_priority(ref, priority)
        # If process is gone, both fail with "no longer exists" — that's fine.
        gone = _is_gone(r1) or _is_gone(r2)
        update_status(entry.id, "undone" if (r1.ok or gone) else "failed")
        return

    else:
        # No undo registered (irreversible action or unknown).
        update_status(entry.id, "undone")
        return

    update_status(entry.id, "undone" if (result.ok or _is_gone(result)) else "failed")


def _is_gone(result: object) -> bool:
    from optimizer.models import ToolResult
    if not isinstance(result, ToolResult):
        return False
    r = result.reason.lower()
    return "no longer exists" in r or "access denied" in r or "not found" in r


def undo_all() -> None:
    """Undo every pending/active reversible entry. Call on startup for crash recovery."""
    for entry in undoable():
        undo(entry)
