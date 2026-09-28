"""
Fake process provider for tests. Implements the same interface as the real
psutil/ctypes layer so action tools can be tested without running real processes.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeProcess:
    pid: int
    create_time: float
    name: str
    exe: str
    username: str = ""
    priority: int = 32          # NORMAL_PRIORITY_CLASS
    suspended: bool = False
    has_window: bool = False
    efficiency_mode: bool = False


class FakeProcessProvider:
    """Records every mutating call; never touches the real OS."""

    def __init__(self, processes: list[FakeProcess] | None = None) -> None:
        self._processes: dict[int, FakeProcess] = {}
        self.calls: list[tuple] = []
        for p in processes or []:
            self._processes[p.pid] = p

    # ── setup helpers ──────────────────────────────────────────────────────

    def add(self, process: FakeProcess) -> None:
        self._processes[process.pid] = process

    def remove(self, pid: int) -> None:
        self._processes.pop(pid, None)

    def get(self, pid: int) -> FakeProcess | None:
        return self._processes.get(pid)

    # ── ProcessProvider protocol ───────────────────────────────────────────

    def get_process_snapshot(self, pid: int) -> dict | None:
        """Return {pid, create_time, name, exe} or None (mirrors psutil.Process)."""
        p = self._processes.get(pid)
        if p is None:
            return None
        return {
            "pid": p.pid,
            "create_time": p.create_time,
            "name": p.name,
            "exe": p.exe,
            "username": p.username,
        }

    # ── read helpers (used by action tools) ───────────────────────────────

    def get_priority(self, pid: int) -> int | None:
        p = self._processes.get(pid)
        return p.priority if p else None

    def has_window(self, pid: int) -> bool:
        p = self._processes.get(pid)
        return p.has_window if p else False

    def get_windows(self, pid: int) -> list[int]:
        """Return a fake list of HWNDs if the process has a window."""
        p = self._processes.get(pid)
        return [1000 + pid] if (p is not None and p.has_window) else []

    # ── mutating ops (recorded, never touch the OS) ───────────────────────

    def set_priority(self, pid: int, priority: int) -> None:
        self.calls.append(("set_priority", pid, priority))
        if pid in self._processes:
            self._processes[pid].priority = priority

    def set_efficiency_mode(self, pid: int, on: bool) -> None:
        self.calls.append(("set_efficiency_mode", pid, on))
        if pid in self._processes:
            self._processes[pid].efficiency_mode = on

    def suspend(self, pid: int) -> None:
        self.calls.append(("suspend", pid))
        if pid in self._processes:
            self._processes[pid].suspended = True

    def resume(self, pid: int) -> None:
        self.calls.append(("resume", pid))
        if pid in self._processes:
            self._processes[pid].suspended = False

    def post_wm_close(self, pid: int) -> bool:
        self.calls.append(("post_wm_close", pid))
        p = self._processes.get(pid)
        return p is not None and p.has_window

    def terminate(self, pid: int) -> None:
        self.calls.append(("terminate", pid))
        self._processes.pop(pid, None)
