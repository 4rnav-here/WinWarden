"""
lookup_known_process() — match against data/known_processes.json.
"""
from __future__ import annotations

import json
from pathlib import Path

from optimizer.models import KnownProcess

_DATA_FILE = Path(__file__).parent.parent.parent / "data" / "known_processes.json"

# Loaded once; maps lower-case name → ordered list of entries (path_hint entries first).
_db: dict[str, list[KnownProcess]] | None = None


def _load() -> dict[str, list[KnownProcess]]:
    global _db
    if _db is not None:
        return _db
    with _DATA_FILE.open(encoding="utf-8") as f:
        raw = json.load(f)
    db: dict[str, list[KnownProcess]] = {}
    for entry in raw:
        kp = KnownProcess(**entry)
        db.setdefault(kp.name.lower(), []).append(kp)
    _db = db
    return _db


def lookup_known_process(name: str, exe: str) -> KnownProcess | None:
    """
    Return the first entry that matches name (case-insensitive).
    If the entry has path_hint, the exe path must contain it (also case-insensitive).
    Returns None if nothing matches.
    """
    db = _load()
    for kp in db.get(name.lower(), []):
        if kp.path_hint and kp.path_hint.lower() not in exe.lower():
            continue
        return kp
    return None
